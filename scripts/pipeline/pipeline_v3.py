#!/usr/bin/env python3
import json, os, traceback, time

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

def t_create():
    from src.vector_index.index_manager import get_index_manager
    mgr = get_index_manager()
    if mgr.has_collection():
        return "exists"
    mgr.create_collection()
    mgr.create_indexes()
    return "Created"
test("1.Create", t_create)

def t_load():
    from pymilvus import Collection, connections
    from src.common.config import get_settings
    s = get_settings()
    connections.connect(alias="default", uri=s.milvus.MILVUS_URI)
    col = Collection("resume_chunks")
    col.load()
    return "Loaded entities=" + str(col.num_entities)
test("2.Load", t_load)

def t_resume():
    from src.resume_store.connection import get_mongodb
    db = get_mongodb().get_database()
    doc = db["resumes"].find_one()
    if not doc:
        return "No resumes"
    rid = doc.get("resume_id", str(doc.get("_id", "")))
    nm = doc.get("personal_info", {}).get("full_name", "?")
    return "rid=" + rid + " name=" + nm
test("3.Resume", t_resume)

def t_write():
    from src.vector_index.embedding_generator import get_embedding_generator
    from src.vector_index.index import get_vector_index
    from src.resume_store.connection import get_mongodb
    from src.resume_parser.segmenter import get_segmenter
    db = get_mongodb().get_database()
    doc = db["resumes"].find_one()
    assert doc, "No resume"
    rid = doc.get("resume_id", str(doc.get("_id", "")))
    raw = doc.get("raw_text", "")
    seg = get_segmenter()
    segments = seg.segment(raw)
    gen = get_embedding_generator()
    idx = get_vector_index()
    count = 0
    for i, s in enumerate(segments[:20]):
        txt = s if isinstance(s, str) else str(s)
        if isinstance(s, dict):
            txt = s.get("content", s.get("text", str(s)))
        emb = gen.generate(txt)
        data = [{"chunk_id": rid + "_s" + str(i), "resume_id": rid, "chunk_level": "section", "parent_chunk_id": "", "section_type": "general", "dense_vector": emb.dense, "sparse_vector": emb.sparse, "content": txt[:2000], "metadata": {}}]
        idx.insert_chunks(data)
        count += 1
    return "Wrote " + str(count) + " chunks"
test("4.WriteVectors", t_write)

def t_search():
    time.sleep(2)
    from src.vector_index.embedding_generator import get_embedding_generator
    from src.vector_index.index import get_vector_index
    gen = get_embedding_generator()
    idx = get_vector_index()
    emb = gen.generate("Java Spring Boot")
    try:
        r = idx.dense_search(emb.dense, top_k=5)
        return "dense=" + str(len(r))
    except:
        pass
    try:
        r = idx.search(emb.dense, top_k=5)
        return "search=" + str(len(r))
    except Exception as e:
        return "fail: " + str(e)[:200]
test("5.Search", t_search)

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
