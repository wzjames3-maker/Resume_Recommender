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

def t_reload():
    from pymilvus import Collection, connections
    from src.common.config import get_settings
    s = get_settings()
    connections.connect(alias="default", uri=s.milvus.MILVUS_URI)
    col = Collection("resume_chunks")
    col.release()
    col.load()
    return "reloaded entities=" + str(col.num_entities)
test("1.Reload", t_reload)

def t_search():
    from src.vector_index.embedding_generator import get_embedding_generator
    from src.vector_index.index import get_vector_index
    gen = get_embedding_generator()
    idx = get_vector_index()
    emb = gen.generate("Java Spring Boot")
    r = idx.hybrid_search_small(query_dense=emb.dense, query_sparse=emb.sparse, top_k=5)
    return "results=" + str(len(r))
test("2.Search", t_search)

def t_chat():
    import httpx
    B = "http://localhost:8000"
    r = httpx.post(B+"/api/v1/auth/login", json={"username":"admin","password":"admin123"})
    tk = r.json()["token"]
    h = {"Authorization": "Bearer "+tk, "Content-Type": "application/json"}
    r2 = httpx.post(B+"/api/v1/chat", headers=h, json={"message":"帮我找Java开发经验候选人"}, timeout=120)
    msgs = []
    for ln in r2.text.strip().split("\n"):
        if ln.strip().startswith("data: "):
            try: msgs.append(json.loads(ln.strip()[6:]))
            except: pass
    full = "".join(m.get("content","") for m in msgs if m.get("type")=="token")
    errs = [m for m in msgs if m.get("type")=="error"]
    if errs: return "ERR: " + errs[0].get("message","")[:300]
    return "reply=" + full[:400]
test("3.ChatE2E", t_chat)

print()
print("="*60)
p = sum(1 for v in results.values() if v[0]=="PASS")
print("FINAL: "+str(p)+"/"+str(len(results))+" PASS")
print("="*60)
