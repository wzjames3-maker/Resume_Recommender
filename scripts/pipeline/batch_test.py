#!/usr/bin/env python3
"""Batch upload all resumes + index vectors + search tests"""
import json, os, httpx, time, traceback

BASE = "http://localhost:8000"

# Login
resp = httpx.post(BASE+"/api/v1/auth/login", json={"username":"admin","password":"admin123"})
token = resp.json()["token"]
auth = {"Authorization": "Bearer " + token}
headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

print("=" * 60)
print("PHASE 1: Upload all resumes")
print("=" * 60)

resume_files = [
    "test_resumes/zhangsan.json",
    "test_resumes/lisi.json",
    "test_resumes/wangwu.json",
    "test_resumes/zhaoliu.json",
    "test_resumes/sunqi.json",
]

uploaded_ids = []
for rf in resume_files:
    if not os.path.exists(rf):
        print("[SKIP]", rf, "not found")
        continue
    with open(rf, "r", encoding="utf-8") as f:
        rd = f.read()
    files = {"file": (os.path.basename(rf), rd, "application/json")}
    try:
        r = httpx.post(BASE+"/api/v1/resumes/upload", headers=auth, files=files, timeout=120)
        data = r.json()
        rid = data.get("resume_id", "?")
        msg = data.get("message", "")
        status = data.get("parse_status", "")
        print("[UPLOAD]", os.path.basename(rf), "-> rid=" + str(rid)[:20], "status=" + str(r.status_code), "parse=" + status, "msg=" + msg[:50])
        if rid and rid != "?":
            uploaded_ids.append(rid)
    except Exception as e:
        print("[ERR]", rf, str(e)[:100])

print("\nUploaded:", len(uploaded_ids), "resumes")

print("\n" + "=" * 60)
print("PHASE 2: Index vectors in Milvus")
print("=" * 60)

from src.vector_index.embedding_generator import get_embedding_generator
from src.vector_index.index import get_vector_index
from src.resume_store.connection import get_mongodb
from src.resume_parser.segmenter import get_segmenter

db = get_mongodb().get_database()
gen = get_embedding_generator()
idx = get_vector_index()
seg = get_segmenter()

# Get all resumes from MongoDB
all_resumes = list(db["resumes"].find())
print("Resumes in MongoDB:", len(all_resumes))

total_chunks = 0
for doc in all_resumes:
    rid = str(doc.get("resume_id", str(doc.get("_id"))))
    raw = doc.get("raw_text", "")
    name = doc.get("personal_info", {})
    if isinstance(name, dict):
        name = name.get("full_name", "?")
    else:
        name = "?"
    
    if not raw:
        print("  [SKIP]", name, "no raw_text")
        continue
    
    # Check if already indexed
    try:
        existing = idx.hybrid_search_small(
            query_dense=[0.0]*1024,
            query_sparse={0: 1.0},
            top_k=1,
            expr='resume_id == "' + rid + '"',
        )
        if existing:
            print("  [SKIP]", name, "rid=" + rid[:12], "already indexed")
            continue
    except:
        pass
    
    # Segment and index
    result = seg.segment(raw)
    count = 0
    for i, s in enumerate(result.segments):
        text = s.content
        chunks_list = []
        if len(text) > 500:
            lines = text.split("\n")
            buf = ""
            for ln in lines:
                if len(buf) + len(ln) > 300 and buf:
                    chunks_list.append(buf.strip())
                    buf = ln
                else:
                    buf += "\n" + ln if buf else ln
            if buf.strip():
                chunks_list.append(buf.strip())
        else:
            chunks_list.append(text)
        
        for j, ct in enumerate(chunks_list):
            emb = gen.generate(ct)
            data = [{
                "chunk_id": rid + "_s" + str(i) + "_c" + str(j),
                "resume_id": rid,
                "chunk_level": "small",
                "parent_chunk_id": rid + "_s" + str(i),
                "section_type": s.segment_type.value,
                "dense_vector": emb.dense,
                "sparse_vector": emb.sparse,
                "content": ct[:2000],
                "metadata": {},
            }]
            idx.insert_chunks(data)
            count += 1
    total_chunks += count
    print("  [INDEXED]", name, "rid=" + rid[:12], "chunks=" + str(count))

# Reload collection
from pymilvus import Collection, connections
from src.common.config import get_settings
s = get_settings()
connections.connect(alias="default", uri=s.milvus.MILVUS_URI)
col = Collection("resume_chunks")
col.release()
col.load()
print("\nCollection reloaded, total entities:", col.num_entities)

print("\n" + "=" * 60)
print("PHASE 3: Search tests")
print("=" * 60)

search_queries = [
    "帮我找一个有Java开发经验的候选人",
    "推荐前端开发工程师",
    "有没有AI算法工程师",
    "需要DevOps运维工程师",
    "找产品经理",
    "有腾讯工作经验的人",
    "会Docker和Kubernetes的",
    "清华大学毕业的",
]

for q in search_queries:
    try:
        r2 = httpx.post(BASE+"/api/v1/chat", headers=headers, json={"message": q}, timeout=120)
        msgs = []
        for ln in r2.text.strip().split("\n"):
            if ln.strip().startswith("data: "):
                try: msgs.append(json.loads(ln.strip()[6:]))
                except: pass
        full = "".join(m.get("content","") for m in msgs if m.get("type")=="token")
        errs = [m for m in msgs if m.get("type")=="error"]
        if errs:
            print("[ERR]", q, "->", errs[0].get("message","")[:100])
        else:
            print("[OK]", q)
            print("    ->", full[:200])
    except Exception as e:
        print("[ERR]", q, "->", str(e)[:100])
    print()

print("=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)
