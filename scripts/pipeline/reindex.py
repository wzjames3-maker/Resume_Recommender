#!/usr/bin/env python3
"""Re-index resume with correct chunk_level='small'"""
import time
from src.vector_index.embedding_generator import get_embedding_generator
from src.vector_index.index import get_vector_index
from src.resume_store.connection import get_mongodb
from src.resume_parser.segmenter import get_segmenter

db = get_mongodb().get_database()
doc = db["resumes"].find_one()
assert doc, "No resume"
rid = str(doc.get("resume_id", str(doc.get("_id"))))
raw = doc.get("raw_text", "")

# Delete old chunks
idx = get_vector_index()
print("Deleting old chunks for:", rid)
idx.delete_chunks_by_resume(rid)

# Re-segment
result = get_segmenter().segment(raw)
gen = get_embedding_generator()
count = 0
for i, s in enumerate(result.segments):
    # Split into smaller chunks if content is long
    text = s.content
    chunks = []
    if len(text) > 500:
        # Split by lines, group into ~300 char chunks
        lines = text.split("\n")
        buf = ""
        for ln in lines:
            if len(buf) + len(ln) > 300 and buf:
                chunks.append(buf.strip())
                buf = ln
            else:
                buf += "\n" + ln if buf else ln
        if buf.strip():
            chunks.append(buf.strip())
    else:
        chunks.append(text)
    
    for j, chunk_text in enumerate(chunks):
        emb = gen.generate(chunk_text)
        data = [{
            "chunk_id": rid + "_seg" + str(i) + "_c" + str(j),
            "resume_id": rid,
            "chunk_level": "small",
            "parent_chunk_id": rid + "_seg" + str(i),
            "section_type": s.segment_type.value,
            "dense_vector": emb.dense,
            "sparse_vector": emb.sparse,
            "content": chunk_text[:2000],
            "metadata": {},
        }]
        idx.insert_chunks(data)
        count += 1

print("Wrote", count, "small chunks for", rid)

# Reload collection
from pymilvus import Collection, connections
from src.common.config import get_settings
s = get_settings()
connections.connect(alias="default", uri=s.milvus.MILVUS_URI)
col = Collection("resume_chunks")
col.release()
col.load()
print("Collection reloaded, entities:", col.num_entities)

# Test search
time.sleep(1)
emb = gen.generate("Java Spring Boot")
r = idx.hybrid_search_small(query_dense=emb.dense, query_sparse=emb.sparse, top_k=5)
print("Search results:", len(r))
for item in r[:3]:
    print("  -", item.get("content","")[:100])

# Test chat
import httpx, json
B = "http://localhost:8000"
resp = httpx.post(B+"/api/v1/auth/login", json={"username":"admin","password":"admin123"})
tk = resp.json()["token"]
h = {"Authorization": "Bearer "+tk, "Content-Type": "application/json"}
r2 = httpx.post(B+"/api/v1/chat", headers=h, json={"message":"帮我找Java开发经验候选人"}, timeout=120)
msgs = []
for ln in r2.text.strip().split("\n"):
    if ln.strip().startswith("data: "):
        try: msgs.append(json.loads(ln.strip()[6:]))
        except: pass
full = "".join(m.get("content","") for m in msgs if m.get("type")=="token")
errs = [m for m in msgs if m.get("type")=="error"]
if errs:
    print("CHAT ERR:", errs[0].get("message","")[:200])
else:
    print("CHAT REPLY:", full[:500])
