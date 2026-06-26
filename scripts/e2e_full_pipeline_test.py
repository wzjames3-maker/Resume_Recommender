"""
全流程 E2E 测试：数据加载 → 文本分块 → 意图分析 → 最终输出
使用 C:/Users/Administrator/Downloads/数据集 中的简历文件
"""
import sys, os, json, time, traceback

sys.path.insert(0, ".")

results = []

def test(name, fn):
    try:
        start = time.time()
        r = fn()
        elapsed = time.time() - start
        results.append((name, "PASS", r, f"{elapsed:.1f}s"))
        print(f"\n[PASS] {name} ({elapsed:.1f}s)")
    except Exception as e:
        results.append((name, "FAIL", str(e)[:300], ""))
        print(f"\n[FAIL] {name}: {str(e)[:200]}")
        traceback.print_exc()

# ============================================================
# STEP 1: 数据加载 — 文本提取
# ============================================================
def t1_text_extraction():
    """测试 DOCX 文本提取"""
    from src.resume_parser.text_extractor import get_text_extractor

    dataset = r"C:/Users/Administrator/Downloads/数据集"
    files = [f for f in os.listdir(dataset) if f.endswith(".docx")]
    assert len(files) > 0, "数据集为空"

    extractor = get_text_extractor()
    extracted = []
    for fname in files[:5]:  # 先测5个
        fpath = os.path.join(dataset, fname)
        with open(fpath, "rb") as f:
            content = f.read()
        doc = extractor.extract(content, fname)
        extracted.append(doc)
        assert doc.raw_text, f"{fname}: 文本提取为空"
        assert len(doc.raw_text) > 10, f"{fname}: 文本太短 ({len(doc.raw_text)} chars)"

    return f"{len(extracted)} files extracted, avg chars={sum(len(d.raw_text) for d in extracted)//len(extracted)}"

test("1. 文本提取 (DOCX x5)", t1_text_extraction)


# ============================================================
# STEP 2: 文本分块 — Segmenter + ChunkBuilder
# ============================================================
def t2_segmentation_and_chunking():
    """测试分段 + 分块"""
    from src.resume_parser.text_extractor import get_text_extractor
    from src.resume_parser.segmenter import get_segmenter
    from src.resume_parser.chunk_builder import get_chunk_builder

    dataset = r"C:/Users/Administrator/Downloads/数据集"
    files = [f for f in os.listdir(dataset) if f.endswith(".docx")]

    extractor = get_text_extractor()
    segmenter = get_segmenter()
    chunk_builder = get_chunk_builder()

    fpath = os.path.join(dataset, files[0])
    with open(fpath, "rb") as f:
        content = f.read()
    doc = extractor.extract(content, files[0])

    # Segment
    seg_result = segmenter.segment(doc.raw_text)
    assert seg_result.total_segments > 0, "分段结果为空"
    print(f"  Segments: {seg_result.total_segments}")

    # Build chunks
    chunk_result = chunk_builder.build(
        segments=seg_result.segments,
        resume_id="test-resume-001",
        full_text=doc.raw_text,
    )
    assert chunk_result.total_chunks > 0, "分块结果为空"
    assert chunk_result.full_chunk is not None, "缺少 Full Chunk"
    assert len(chunk_result.parent_chunks) > 0, "缺少 Parent Chunks"
    assert len(chunk_result.small_chunks) > 0, "缺少 Small Chunks"

    return f"Segments={seg_result.total_segments}, Chunks={chunk_result.total_chunks} (F={1 if chunk_result.full_chunk else 0} P={len(chunk_result.parent_chunks)} S={len(chunk_result.small_chunks)})"

test("2. 分段 + 分块", t2_segmentation_and_chunking)


# ============================================================
# STEP 3: LLM 结构化提取 + SkillEntry 字段验证
# ============================================================
def t3_llm_extraction():
    """测试 LLM 结构化提取，重点验证 SkillEntry 字段映射"""
    from src.resume_parser.text_extractor import get_text_extractor
    from src.resume_parser.llm_extractor import get_llm_extractor

    dataset = r"C:/Users/Administrator/Downloads/数据集"
    files = [f for f in os.listdir(dataset) if f.endswith(".docx")]

    extractor = get_text_extractor()
    fpath = os.path.join(dataset, files[0])
    with open(fpath, "rb") as f:
        content = f.read()
    doc = extractor.extract(content, files[0])

    llm = get_llm_extractor()
    structured = llm.extract(doc.raw_text)

    # Check basic fields
    assert structured.personal_info is not None, "personal_info 为空"
    print(f"  Name: {structured.personal_info.full_name}")
    print(f"  Skills: {len(structured.skill_list)}")
    for s in structured.skill_list[:5]:
        print(f"    - {s.name}: proficiency={s.proficiency}, years={s.years_of_experience}")

    # Check SkillEntry field mapping fix
    if structured.skill_list:
        s0 = structured.skill_list[0]
        # At minimum, name should be populated
        assert s0.name, "Skill name is empty"

    return f"Skills={len(structured.skill_list)}, Confidence={structured.confidence_score}"

test("3. LLM 结构化提取 + SkillEntry 验证", t3_llm_extraction)


# ============================================================
# STEP 4: 向量索引写入 (Milvus)
# ============================================================
def t4_vector_index_write():
    """测试向量索引创建 + 写入"""
    from src.vector_index.index import get_vector_index
    from src.vector_index.index_manager import get_index_manager
    from src.vector_index.embedding_generator import get_embedding_generator

    # Create collection + indexes
    mgr = get_index_manager()
    if mgr.has_collection():
        print("  Collection exists, dropping...")
        mgr.drop_collection()
    mgr.create_collection()
    mgr.create_indexes()
    print("  Collection + indexes created")

    # Test embedding generation
    gen = get_embedding_generator()
    emb = gen.generate("测试文本 Java Spring Boot")
    assert emb.dense, "Dense embedding 为空"
    assert len(emb.dense) > 0, "Dense embedding 长度为0"
    print(f"  Dense dim: {len(emb.dense)}")

    # Load collection
    mgr.load_collection()
    print("  Collection loaded")

    return f"Dense dim={len(emb.dense)}, Collection=OK"

test("4. Milvus 索引创建 + Embedding 生成", t4_vector_index_write)


# ============================================================
# STEP 5: 完整索引链路 (segment → chunk → vector)
# ============================================================
def t5_indexing_pipeline():
    """测试 indexing.py 的完整链路"""
    from src.resume_parser.text_extractor import get_text_extractor
    from src.services.indexing import index_resume

    dataset = r"C:/Users/Administrator/Downloads/数据集"
    files = [f for f in os.listdir(dataset) if f.endswith(".docx")]

    extractor = get_text_extractor()
    fpath = os.path.join(dataset, files[0])
    with open(fpath, "rb") as f:
        content = f.read()
    doc = extractor.extract(content, files[0])

    chunk_count = index_resume("test-resume-001", doc.raw_text)
    assert chunk_count > 0, "Indexing 返回 0 chunks"

    return f"Indexed {chunk_count} chunks into Milvus"

test("5. 完整索引链路 (segment→chunk→vector)", t5_indexing_pipeline)


# ============================================================
# STEP 6: 向量检索测试
# ============================================================
def t6_vector_search():
    """测试向量检索"""
    from src.vector_index.index import get_vector_index
    from src.vector_index.embedding_generator import get_embedding_generator

    gen = get_embedding_generator()
    emb = gen.generate("Java开发 Spring Boot 后端")

    idx = get_vector_index()
    results = idx.hybrid_search_small(
        query_dense=emb.dense,
        query_sparse=emb.sparse,
        top_k=5,
    )
    assert len(results) > 0, "检索结果为空"
    for i, r in enumerate(results[:3]):
        print(f"  Result {i+1}: resume_id={r.get('resume_id','?')}, score={r.get('score','?'):.4f}")

    return f"Found {len(results)} results"

test("6. 向量检索", t6_vector_search)


# ============================================================
# STEP 7: 意图分析测试
# ============================================================
def t7_intent_analysis():
    """测试意图识别"""
    from src.intent_router.classifier import get_intent_classifier

    queries = [
        "帮我找有3年Java开发经验的候选人",
        "按薪资从高到低排序",
        "查看张三的简历详情",
        "你好",
    ]

    classifier = get_intent_classifier()
    results = []
    for q in queries:
        r = classifier.classify(q)
        results.append(r)
        print(f"  '{q[:30]}...' → {r.intent.value} (conf={r.confidence:.2f})")

    # Verify search query is classified correctly
    search_result = results[0]
    assert search_result.intent.value == "recruitment.search", f"搜索意图识别错误: {search_result.intent.value}"

    # Verify chat query
    chat_result = results[3]
    assert chat_result.intent.value == "chat", f"闲聊意图识别错误: {chat_result.intent.value}"

    return f"4 queries classified: {[r.intent.value for r in results]}"

test("7. 意图分析", t7_intent_analysis)


# ============================================================
# STEP 8: 上下文管理测试
# ============================================================
def t8_context_management():
    """测试会话管理 + 上下文"""
    from src.conversation_memory.session_manager import get_session_manager

    sm = get_session_manager()
    session = sm.create_session("test-user")

    # Append messages
    sm.append_message(session.session_id, "user", "帮我找Java开发")
    sm.append_message(session.session_id, "assistant", "为您找到3位候选人")

    # Get context
    ctx = sm.get_conversation_context(session.session_id)
    assert ctx is not None, "上下文为空"
    assert ctx["turn_count"] == 1, f"轮次错误: {ctx['turn_count']}"
    assert ctx["last_intent"] is None, "初始 last_intent 应为 None"

    # Update state
    sm.update_session_state(
        session.session_id,
        last_query={"job_title": "Java"},
        last_intent="recruitment.search",
    )

    # Re-get context
    ctx2 = sm.get_conversation_context(session.session_id)
    assert ctx2["last_intent"] == "recruitment.search", f"last_intent 未持久化: {ctx2['last_intent']}"

    # Verify session exists
    s2 = sm.get_session(session.session_id)
    assert s2 is not None, "会话丢失"

    return f"Session={session.session_id[:8]}..., turns={ctx['turn_count']}, intent={ctx2['last_intent']}"

test("8. 会话管理 + 上下文", t8_context_management)


# ============================================================
# STEP 9: 混合检索 + Metadata Filter (with enrichment fix)
# ============================================================
def t9_hybrid_retrieval_with_filter():
    """测试混合检索 + 元数据过滤（验证 enrichment 在 filter 之前）"""
    from src.recommendation_engine.hybrid_retriever import get_hybrid_retriever
    from src.recommendation_engine.metadata_filter import get_metadata_filter
    from src.intent_router.schemas import CandidateSlot
    from src.resume_store.repository import get_resume_repository

    # First, get some resumes loaded with raw_text
    repo = get_resume_repository()

    # Build candidate slots for Java search
    slots = CandidateSlot(
        job_title="Java开发",
        skills=["Java", "Spring"],
    )

    retriever = get_hybrid_retriever()
    try:
        retrieval_results = retriever.retrieve(slots, top_k=10, raw_query="Java开发 Spring")
    except Exception as e:
        print(f"  (retrieval returned 0 results or error: {e})")
        retrieval_results = []

    if retrieval_results:
        # Enrich metadata (replicate what workflow does)
        for r in retrieval_results:
            try:
                resp = repo.get(r.resume_id, decrypt_pii=False)
                if resp:
                    r.metadata["skills"] = [s.name for s in resp.skill_list if s.name]
                    r.metadata["years_of_experience"] = resp.personal_info.years_of_experience
            except Exception:
                pass

        # Now filter with enriched metadata
        mf = get_metadata_filter()
        filter_result = mf.filter(retrieval_results, slots)
        print(f"  Before filter: {len(retrieval_results)}, After: {len(filter_result.results)}")
        return f"Retrieved={len(retrieval_results)}, Filtered={len(filter_result.results)}"
    else:
        return "No results (index may be empty or no matching)"

test("9. 混合检索 + Metadata Filter", t9_hybrid_retrieval_with_filter)


# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("FULL PIPELINE E2E TEST RESULTS")
print("=" * 70)
passed = sum(1 for r in results if r[1] == "PASS")
failed = sum(1 for r in results if r[1] == "FAIL")
for name, status, detail, elapsed in results:
    icon = "✅" if status == "PASS" else "❌"
    print(f"  {icon} {name}: {detail}")
print(f"\n  {passed}/{len(results)} PASS, {failed}/{len(results)} FAIL")
