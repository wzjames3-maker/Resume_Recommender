#!/usr/bin/env python3
"""Full pipeline: create collection, index resume, search"""
import json, os, traceback

results = {}
def test(name, fn):
    try:
        r = fn()
        results[name] = ("PASS", str(r)[:500])
        print("[PASS] " + name + ": " + str(r)[:200])
    except Exception as e:
        results[name] = ("FAIL", str(e)[:200])
        traceback.print_exc()
        print("[FAIL] " + name + ": " + str(e)[:200])

# 1. Create Milvus collection
def t_create_collection():
    from src.vector_index.index_manager import get_index_manager
    mgr = get_index_manager()
    if mgr.has_collection():
        return "Collection already exists"
    mgr.create_collection()
    mgr.create_indexes()
    mgr.load_collection()
    return "Collection created + indexed + loaded"

test("1. Create Milvus Collection", t_create_collection)

# 2. Delete old resume + re-upload to get fresh ID
def t_upload():
    from src.resume_store.repository import get_resume_repository
    repo = get_resume_repository()
    # Delete existing test resumes
    existing = repo.find_by_filename("zhangsan.json")
    if existing:
        repo.delete(existing.id)
        print("  Deleted old resume: " + existing.id)

    import httpx
    BASE = "http://localhost:8000"
    resp = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = resp.json()["token"]
    auth = {"Authorization": "Bearer " + token}

    with open("test_resumes/zhangsan.json", "r", encoding="utf-8") as f:
        rd = f.read()
    files = {"file": ("zhangsan.json", rd, "application/json")}
    resp = httpx.post(BASE + "/api/v1/resumes/upload", headers=auth, files=files, timeout=120)
    data = resp.json()
    return json.dumps(data, ensure_ascii=False)

test("2. Upload Resume", t_upload)

# 3. Build chunks and write vectors
def t_index_resume():
    from src.resume_store.repository import get_resume_repository
    from src.services.indexing import index_resume

    repo = get_resume_repository()
    resume = repo.find_by_filename("zhangsan.json")
    assert resume, "Resume not found"
    print("  Resume ID: " + resume.id)

    assert resume.raw_text, "Resume has no raw_text"
    chunk_count = index_resume(resume.id, resume.raw_text)
    return "resume_id=" + resume.id + " chunks=" + str(chunk_count)

test("3. Index Resume Vectors", t_index_resume)

# 4. Search
def t_search():
    from src.vector_index.index import get_vector_index
    from src.vector_index.embedding_generator import get_embedding_generator

    gen = get_embedding_generator()
    emb = gen.generate("Java开发经验 Spring Boot")

    idx = get_vector_index()
    results = idx.hybrid_search_small(dense_vector=emb.dense, sparse_vector=emb.sparse, top_k=5)
    return "results=" + str(len(results)) + " first=" + str(results[0])[:200] if results else "no results"

test("4. Vector Search", t_search)

# 5. Full chat E2E
def t_chat_e2e():
    import httpx
    BASE = "http://localhost:8000"
    resp = httpx.post(BASE + "/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    token = resp.json()["token"]
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

    resp = httpx.post(BASE + "/api/v1/chat", headers=headers, json={
        "message": "帮我找有Java开发经验的候选人",
    }, timeout=120)
    assert resp.status_code == 200
    # Parse SSE
    msgs = []
    for line in resp.text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                msgs.append(json.loads(line[6:]))
            except:
                pass
    full = "".join(m.get("content", "") for m in msgs if m.get("type") == "token")
    errors = [m for m in msgs if m.get("type") == "error"]
    if errors:
        return "ERROR: " + errors[0].get("message", "")[:200]
    return "reply=" + full[:200]

test("5. Chat E2E", t_chat_e2e)

print()
print("=" * 60)
passed = sum(1 for v in results.values() if v[0] == "PASS")
print("PIPELINE RESULT: " + str(passed) + "/" + str(len(results)) + " PASS")
print("=" * 60)
