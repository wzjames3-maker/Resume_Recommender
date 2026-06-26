#!/usr/bin/env python3
import json, traceback, time

results = {}
def test(name, fn):
    try:
        r = fn()
        results[name] = ("PASS", str(r)[:500])
        print("[PASS] " + name + ": " + str(r)[:300])
    except Exception as e:
        results[name] = ("FAIL", str(e)[:200])
        traceback.print_exc()
        print("[FAIL] " + name + ": " + str(e)[:200])

# 1. Collection
def t_create():
    from src.vector_index.index_manager import get_index_manager
    mgr = get_index_manager()
    if mgr.has_collection():
        return "exists"
    mgr.create_collection()
    mgr.create_indexes()
    return "Created"
test("1.Create", t_create)

# 2. Load
def t_load():
    from pymilvus import Collection, connections
    from src.common.config import get_settings
    s = get_settings()
    connections.connect(alias="default", uri=s.milvus.MILVUS_URI)
    col = Collection("resume_chunks")
    col.load()
    return "entities=" + str(col.num_entities)
test("2.Load", t_load)

# 3. Find resume
def t_resume():
    from src.resume_store.connection import get_mongodb
    db = get_mongodb().get_database()
    doc = db["resumes"].find_one()
    if not doc:
        return "No resumes"
    rid = doc.get("resume_id", str(doc.get("_id")))
    nm = str(doc.get("personal_info", {}).get("full_name", "?"))
    rt = doc.get("raw_text", "")
    return "rid=" + str(rid) + " name=" + nm + " text_len=" + str(len(rt))
test("3.Resume", t_resume)

# 4. Segment + Chunk + Embed + Write
def t_write():
    from src.vector_index.embedding_generator import get_embedding_generator
    from src.vector_index.index import get_vector_index
    from src.resume_store.connection import get_mongodb
    from src.resume_parser.segmenter import get_segmenter
    db = get_mongodb().get_database()
    doc = db["resumes"].find_one()
    assert doc, "No resume"
    rid = str(doc.get("resume_id", str(doc.get("_id"))))
    raw = doc.get("raw_text", "")
    seg = get_segmenter()
    result = seg.segment(raw)
    segments = result.segments
    gen = get_embedding_generator()
    idx = get_vector_index()
    count = 0
    for i, seg_item in enumerate(segments[:20]):
        txt = seg_item.content
        emb = gen.generate(txt)
        data = [{
            "chunk_id": rid + "_s" + str(i),
            "resume_id": rid,
            "chunk_level": "section",
            "parent_chunk_id": "",
            "section_type": seg_item.segment_type.value if seg_item.segment_type else "other",
            "dense_vector": emb.dense,
            "sparse_vector": emb.sparse,
            "content": txt[:2000],
            "metadata": {},
        }]
        idx.insert_chunks(data)
        count += 1
    return "Wrote " + str(count) + " chunks for " + rid
test("4.WriteVectors", t_write)

# 5. Dense search
def t_search():
    time.sleep(2)
    from src.vector_index.embedding_generator import get_embedding_generator
    from src.vector_index.index import get_vector_index
    gen = get_embedding_generator()
    idx = get_vector_index()
    emb = gen.generate("Java Spring Boot 开发经验")
    r = idx.dense_search(emb.dense, top_k=5)
    return "results=" + str(len(r))
test("5.Search", t_search)

# 6. Chat E2E
def t_chat():
    import httpx
    B = "http://localhost:8000"
    r = httpx.post(B + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    tk = r.json()["token"]
    h = {"Authorization": "Bearer " + tk, "Content-Type": "application/json"}
    r2 = httpx.post(B + "/api/v1/chat", headers=h, json={"message": "帮我找Java开发经验候选人"}, timeout=120)
    msgs = []
    for ln in r2.text.strip().split("\n"):
        ln = ln.strip()
        if ln.startswith("data: "):
            try: msgs.append(json.loads(ln[6:]))
            except: pass
    full = "".join(m.get("content","") for m in msgs if m.get("type")=="token")
    errs = [m for m in msgs if m.get("type")=="error"]
    if errs:
        return "ERR: " + errs[0].get("message","")[:200]
    return "reply=" + full[:300]
test("6.ChatE2E", t_chat)

print()
print("=" * 60)
p = sum(1 for v in results.values() if v[0] == "PASS")
print("RESULT: " + str(p) + "/" + str(len(results)) + " PASS")
print("=" * 60)
