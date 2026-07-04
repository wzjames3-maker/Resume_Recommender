"""
全流程端到端测试脚本

Flow:
  1. 从数据集目录解析 .docx 简历文件
  2. 文本提取 → LLM 结构化提取 → Chunk 构建
  3. Embedding 生成 (SiliconFlow API) → 写入 Milvus
  4. 查询测试 → 混合检索 → Rerank → 推荐理由生成
"""

import os
import sys
import time
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATASET_DIR = Path("/mnt/c/Users/Administrator/Downloads/数据集")
SAMPLE_COUNT = 2

os.environ.setdefault("APP_ENV", "dev")


def step(emoji: str, title: str):
    print(f"\n{'='*60}")
    print(f"  {emoji} {title}")
    print(f"{'='*60}")


def test_extract_text(filepath: Path):
    from src.resume_parser.text_extractor import TextExtractor

    extractor = TextExtractor()
    content = filepath.read_bytes()
    doc = extractor.extract(content, filepath.name)
    print(f"  提取文本: {len(doc.raw_text)} 字符")
    return doc


def test_llm_extract(doc):
    from src.resume_parser.llm_extractor import LLMExtractor

    extractor = LLMExtractor()
    print(f"  正在调用 LLM 提取结构化数据...")
    t0 = time.time()
    structured = extractor.extract(doc.raw_text)
    elapsed = time.time() - t0
    print(f"  LLM 提取完成: {elapsed:.1f}s")
    print(f"  教育经历: {len(structured.education_list)} 条")
    print(f"  工作经历: {len(structured.experience_list)} 条")
    print(f"  技能: {len(structured.skill_list)} 个")
    return structured


def test_build_chunks(structured, resume_id: str, raw_text: str):
    from src.resume_parser.chunk_builder import ChunkBuilder

    builder = ChunkBuilder()
    chunks = builder.generate_chunks(resume_id, structured, raw_text)
    print(f"  Chunk 总数: {len(chunks)}")
    levels = {}
    for c in chunks:
        levels[c.chunk_level.value] = levels.get(c.chunk_level.value, 0) + 1
    for lv, cnt in levels.items():
        print(f"    {lv}: {cnt}")
    return chunks


def test_write_vectors(chunks, resume_id: str):
    from src.vector_index.vector_writer import get_vector_writer

    writer = get_vector_writer()
    t0 = time.time()
    ids = writer.write_chunks(chunks, resume_id)
    elapsed = time.time() - t0
    print(f"  写入 {len(ids)} 条向量: {elapsed:.1f}s")
    return ids


def test_search(query_text: str, slots):
    from src.recommendation_engine.hybrid_retriever import get_hybrid_retriever

    retriever = get_hybrid_retriever()
    t0 = time.time()
    results = retriever.retrieve(slots, top_k=10, raw_query=query_text)
    elapsed = time.time() - t0
    print(f"  检索耗时: {elapsed:.1f}s")
    print(f"  命中: {len(results)} 条 (去重后)")
    return results


def test_rerank(results, query_text: str = ""):
    from src.recommendation_engine.reranker import get_reranker

    reranker = get_reranker()
    t0 = time.time()
    ranked = reranker.rerank(results, query_text=query_text)
    elapsed = time.time() - t0
    print(f"  Rerank 耗时: {elapsed:.1f}s")
    return ranked


def test_generate_reasons(ranked, slots):
    from src.recommendation_engine.reason_generator import get_reason_generator

    generator = get_reason_generator()
    t0 = time.time()
    reasons = []
    for r in ranked[:3]:
        reason = generator.generate(r, slots)
        reasons.append(reason)
    elapsed = time.time() - t0
    print(f"  生成推荐理由: {elapsed:.1f}s")
    return reasons


def main():
    # 1. 重置 Milvus Collection
    step("1", "重置 Collection (添加标量字段)")

    from pymilvus import utility, MilvusClient
    from src.vector_index.connection import get_milvus_connection

    conn = get_milvus_connection()
    conn.connect()
    if utility.has_collection("resume_chunks"):
        utility.drop_collection("resume_chunks")
        print("  旧 Collection 已删除")

    from src.vector_index.schema import get_collection_name, get_collection_schema
    from src.vector_index.index import Collection as PymilvusCollection
    schema = get_collection_schema()
    col = PymilvusCollection(name=get_collection_name(), schema=schema)
    print(f"  新 Collection 创建成功")

    from src.vector_index.index import get_vector_index
    vi = get_vector_index()
    vi.create_indexes()
    print(f"  索引创建成功")

    # 2. 处理数据集样本
    step("2", f"解析 {SAMPLE_COUNT} 份简历")

    docx_files = sorted(DATASET_DIR.glob("*.docx"))[:SAMPLE_COUNT]
    print(f"  选取文件: {[f.name for f in docx_files]}")

    resume_count = 0

    for filepath in docx_files:
        resume_id = filepath.stem
        print(f"\n  --- {filepath.name} ---")

        doc = test_extract_text(filepath)
        structured = test_llm_extract(doc)
        chunks = test_build_chunks(structured, resume_id, doc.raw_text)
        test_write_vectors(chunks, resume_id)
        resume_count += 1

    # 3. 查询测试
    step("3", "混合检索测试")

    from src.intent_router.schemas import CandidateSlot

    query_text = "需要一个会Python和Java的后端工程师，3年以上经验，本科及以上学历"
    slots = CandidateSlot(
        job_title="后端工程师",
        skills=["Python", "Java", "Go", "MySQL"],
        experience=3,
    )

    results = test_search(query_text, slots)

    if not results:
        print("\n  ❌ 无检索结果！跳过后续步骤")
        return

    # 4. Rerank
    step("4", "Rerank 精排")
    ranked = test_rerank(results, query_text=query_text)

    # 5. 打印排名
    step("5", "检索结果")

    for i, r in enumerate(ranked[:5]):
        meta = r.metadata or {}
        name = meta.get("candidate_name", "未知")
        score = r.score
        skills = meta.get("skills_normalized", [])[:5]
        print(f"  {i+1}. [{score:.4f}] {name} | {', '.join(skills) if skills else '无技能'}")

    # 6. 推荐理由生成
    step("6", "LLM 推荐理由")
    reasons = test_generate_reasons(ranked, slots)

    for i, reason in enumerate(reasons[:3]):
        print(f"\n  --- 候选人 {i+1} ---")
        reason_text = getattr(reason, "reason", str(reason))
        print(f"  {reason_text[:300]}{'...' if len(reason_text) > 300 else ''}")

    print(f"\n{'='*60}")
    print(f"  ✅ 全流程测试完成！")
    print(f"  {resume_count} 份简历入库, {len(results)} 条命中, {len(ranked)} 条重排")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
