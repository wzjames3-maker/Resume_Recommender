import sys, os, json, time, traceback
sys.path.insert(0, ".")
DATASET = r"C:\Users\Administrator\Downloads\数据集"
results = []

def test(name, fn):
    try:
        start = time.time()
        r = fn()
        elapsed = time.time() - start
        results.append((name, "PASS", str(r)[:300], f"{elapsed:.1f}s"))
        print(f"\n[PASS] {name} ({elapsed:.1f}s): {str(r)[:150]}")
    except Exception as e:
        results.append((name, "FAIL", str(e)[:300], ""))
        print(f"\n[FAIL] {name}: {str(e)[:200]}")
        traceback.print_exc()

def t1():
    from src.resume_parser.text_extractor import get_text_extractor
    files = [f for f in os.listdir(DATASET) if f.endswith(".docx")]
    assert len(files) > 0, "Empty"
    ex = get_text_extractor()
    out = []
    for fn in files[:5]:
        with open(os.path.join(DATASET, fn), "rb") as f:
            doc = ex.extract(f.read(), fn)
        out.append(doc)
        assert doc.raw_text and len(doc.raw_text) > 10, f"{fn}: short"
    avg = sum(len(d.raw_text) for d in out) // len(out)
    return f"{len(out)} files, avg {avg} chars"
test("1. TEXT Extract", t1)

def t2():
    from src.resume_parser.text_extractor import get_text_extractor
    from src.resume_parser.segmenter import get_segmenter
    from src.resume_parser.chunk_builder import get_chunk_builder
    files = [f for f in os.listdir(DATASET) if f.endswith(".docx")]
    ex = get_text_extractor()
    with open(os.path.join(DATASET, files[0]), "rb") as f:
        doc = ex.extract(f.read(), files[0])
    seg = get_segmenter().segment(doc.raw_text)
    print(f"  Segments: {seg.total_segments}")
    assert seg.total_segments > 0
    ck = get_chunk_builder().build(segments=seg.segments, resume_id="t2", full_text=doc.raw_text)
    assert ck.total_chunks > 0 and ck.full_chunk and ck.parent_chunks and ck.small_chunks
    return f"Seg={seg.total_segments} Chunks=F1+P{len(ck.parent_chunks)}+S{len(ck.small_chunks)}={ck.total_chunks}"
test("2. Segment+Chunk", t2)

def t3():
    from src.resume_parser.text_extractor import get_text_extractor
    from src.resume_parser.llm_extractor import get_llm_extractor
    files = [f for f in os.listdir(DATASET) if f.endswith(".docx")]
    ex = get_text_extractor()
    with open(os.path.join(DATASET, files[0]), "rb") as f:
        doc = ex.extract(f.read(), files[0])
    s = get_llm_extractor().extract(doc.raw_text)
    print(f"  Name: {s.personal_info.full_name}, Skills: {len(s.skill_list)}")
    for sk in s.skill_list[:5]:
        print(f"    {sk.name}: prof={sk.proficiency}, yrs={sk.years_of_experience}")
    return f"Skills={len(s.skill_list)}, conf={s.confidence_score}"
test("3. LLM+SkillEntry", t3)

def t4():
    from src.vector_index.index_manager import get_index_manager
    from src.vector_index.embedding_generator import get_embedding_generator
    mgr = get_index_manager()
    if mgr.has_collection():
        mgr.drop_collection()
    mgr.create_collection()
    mgr.create_indexes()
    emb = get_embedding_generator().generate("Java Spring")
    assert emb.dense and len(emb.dense) > 0
    mgr.load_collection()
    return f"Dense dim={len(emb.dense)}"
test("4. Milvus+Embedding", t4)

def t5():
    from src.resume_parser.text_extractor import get_text_extractor
    from src.services.indexing import index_resume
    files = [f for f in os.listdir(DATASET) if f.endswith(".docx")]
    ex = get_text_extractor()
    with open(os.path.join(DATASET, files[0]), "rb") as f:
        doc = ex.extract(f.read(), files[0])
    cnt = index_resume("t5-resume", doc.raw_text)
    assert cnt > 0
    return f"{cnt} chunks indexed"
test("5. Index Pipeline", t5)

def t6():
    from src.vector_index.index import get_vector_index
    from src.vector_index.embedding_generator import get_embedding_generator
    emb = get_embedding_generator().generate("Java Spring")
    r = get_vector_index().hybrid_search_small(query_dense=emb.dense, query_sparse=emb.sparse, top_k=3)
    assert len(r) > 0
    for i, x in enumerate(r):
        print(f"  #{i+1}: id={str(x.get('resume_id','?'))[:20]} score={x.get('score',0):.4f}")
    return f"{len(r)} results"
test("6. Vector Search", t6)

def t7():
    from src.intent_router.classifier import get_intent_classifier
    c = get_intent_classifier()
    queries = ["帮我找3年Java开发", "按薪资排序", "你好"]
    out = []
    for q in queries:
        r = c.classify(q)
        out.append(r.intent.value)
        print(f'  "{q}" -> {r.intent.value} (conf={r.confidence:.2f})')
    assert out[0] == "recruitment.search", f"Wrong: {out[0]}"
    assert out[2] == "chat", f"Wrong: {out[2]}"
    return str(out)
test("7. Intent Analysis", t7)

def t8():
    from src.conversation_memory.session_manager import get_session_manager
    sm = get_session_manager()
    s = sm.create_session("t8")
    sm.append_message(s.session_id, "user", "找Java")
    sm.append_message(s.session_id, "assistant", "找到3位")
    sm.update_session_state(s.session_id, last_query={"job_title":"Java"}, last_intent="recruitment.search")
    ctx = sm.get_conversation_context(s.session_id)
    assert ctx["turn_count"] == 1
    assert ctx["last_intent"] == "recruitment.search"
    return f"turns={ctx['turn_count']}, intent={ctx['last_intent']}"
test("8. Context Mgmt", t8)

def t9():
    from src.recommendation_engine.hybrid_retriever import get_hybrid_retriever
    from src.recommendation_engine.metadata_filter import get_metadata_filter
    from src.resume_store.repository import get_resume_repository
    from src.intent_router.schemas import CandidateSlot
    slots = CandidateSlot(job_title="Java", skills=["Java","Spring"])
    rr = get_hybrid_retriever().retrieve(slots, top_k=5, raw_query="Java Spring")
    if rr:
        repo = get_resume_repository()
        for r in rr:
            try:
                resp = repo.get(r.resume_id, decrypt_pii=False)
                if resp:
                    r.metadata["skills"] = [s.name for s in resp.skill_list if s.name]
                    r.metadata["years_of_experience"] = resp.personal_info.years_of_experience
            except: pass
        fr = get_metadata_filter().filter(rr, slots)
        return f"Retrieved={len(rr)}, Filtered={len(fr.results)}"
    return "No results"
test("9. Hybrid Retr+Filter", t9)

print()
print("=" * 70)
passed = sum(1 for r in results if r[1] == "PASS")
for name, status, detail, elapsed in results:
    print(f"  [{status}] {name}: {detail}")
print(f"  => {passed}/{len(results)} PASS")
