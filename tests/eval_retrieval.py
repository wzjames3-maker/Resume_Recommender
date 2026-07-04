"""
回召率 & Ranking Loss 评估脚本

策略:
  - 用 extracted_profiles.json 提供结构化数据 (skills / years / education / city)
  - 用 raw_text 填充 full chunk 内容
  - 跳过 LLM 提取 (快速索引 33 份简历)
  - 对 21 条 ground-truth 查询逐一检索、计算 IR 指标

用法:
  python tests/eval_retrieval.py [--fast] [--full]
    --fast : 只索引 evaluation triplets 中涉及的简历 (8 份), 默认
    --full : 索引全部 33 份简历
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("APP_ENV", "dev")

DATASET_DIR = Path("/mnt/c/Users/Administrator/Downloads/数据集")
TRIPLETS_PATH = PROJECT_ROOT / "data" / "evaluation" / "evaluation_triplets.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "evaluation" / "extracted_profiles.json"
REPORT_PATH = PROJECT_ROOT / "data" / "evaluation" / "evaluation_report.json"

# ── metrics ──────────────────────────────────────────────────────────

def compute_metrics(
    queries: List[Dict],
) -> Dict[str, Any]:
    metrics: Dict[str, float] = {}
    k_list = [1, 3, 5, 10, 20]

    # 1. Recall@K
    for k in k_list:
        values = [q["recalls"][k] for q in queries]
        metrics[f"avg_recall@{k}"] = round(sum(values) / len(values), 4)
        metrics[f"max_recall@{k}"] = round(max(values), 4)

    # 2. Precision@K
    for k in k_list:
        values = [q["precisions"][k] for q in queries]
        metrics[f"avg_precision@{k}"] = round(sum(values) / len(values), 4)
        metrics[f"max_precision@{k}"] = round(max(values), 4)

    # 3. MRR
    mrr_values = [q["mrr"] for q in queries]
    metrics["avg_mrr"] = round(sum(mrr_values) / len(mrr_values), 4)
    metrics["max_mrr"] = round(max(mrr_values), 4)

    # 4. NDCG@K
    for k in k_list:
        values = [q["ndcgs"][k] for q in queries]
        metrics[f"avg_ndcg@{k}"] = round(sum(values) / len(values), 4)
        metrics[f"max_ndcg@{k}"] = round(max(values), 4)

    # 5. MAP
    ap_values = [q["ap"] for q in queries]
    metrics["avg_map"] = round(sum(ap_values) / len(ap_values), 4)

    # 6. Hit Rate (至少命中 1 个 relevant @K)
    for k in k_list:
        hit = sum(1 for q in queries if q["recalls"][k] > 0)
        metrics[f"hit_rate@{k}"] = round(hit / len(queries), 4)

    # 7. Loss 指标 ─────────────────────────────────────────────────
    # Pairwise Ranking Loss: 对每个 query，统计 "相关但排在非相关后面" 的对数
    total_swaps = 0
    total_pairs = 0
    for q in queries:
        swaps, pairs = q.get("pairwise_loss", (0, 0))
        total_swaps += swaps
        total_pairs += pairs
    metrics["pairwise_ranking_loss"] = round(total_swaps / max(total_pairs, 1), 4)

    # Coverage: 被检索到的唯一 resume 数量 / 语料库大小
    all_found = set()
    for q in queries:
        all_found.update(q["retrieved"])
    corpus_unique = set()
    for q in queries:
        for r in q.get("relevant_list", []):
            corpus_unique.add(r["resume_id"])
    metrics["coverage"] = round(len(all_found & corpus_unique) / max(len(corpus_unique), 1), 4)

    return metrics


def compute_per_query_metrics(
    retrieved: List[str],
    relevant_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """为单个 query 计算全部指标"""
    q = {"retrieved": retrieved, "relevant_list": relevant_list}

    relevant_ids = {r["resume_id"] for r in relevant_list}
    relevance_map = {r["resume_id"]: r["relevance"] for r in relevant_list}
    k_list = [1, 3, 5, 10, 20]
    recalls: Dict[int, float] = {}
    precisions: Dict[int, float] = {}
    ndcgs: Dict[int, float] = {}

    for k in k_list:
        top_k = retrieved[:k]
        hits = len(relevant_ids & set(top_k))
        recalls[k] = round(hits / max(len(relevant_ids), 1), 4)
        precisions[k] = round(hits / k, 4)

        import math
        dcg = 0.0
        for i, rid in enumerate(top_k):
            rel = relevance_map.get(rid, 0.0)
            dcg += rel / math.log2(i + 2)
        ideal_rels = sorted(relevance_map.values(), reverse=True)[:k]
        idcg = 0.0
        for i, rel in enumerate(ideal_rels):
            idcg += rel / math.log2(i + 2)
        ndcgs[k] = round(dcg / idcg, 4) if idcg > 0 else 0.0

    q["recalls"] = recalls
    q["precisions"] = precisions
    q["ndcgs"] = ndcgs

    # MRR: 1 / rank of first relevant result
    mrr = 0.0
    for i, rid in enumerate(retrieved):
        if rid in relevant_ids:
            mrr = 1.0 / (i + 1)
            break
    q["mrr"] = mrr

    # AP (Average Precision)
    ap = 0.0
    correct = 0
    for i, rid in enumerate(retrieved):
        if rid in relevant_ids:
            correct += 1
            ap += correct / (i + 1)
    q["ap"] = round(ap / max(len(relevant_ids), 1), 4)

    # Pairwise ranking loss: count (rel_lo, rel_hi) pairs where rel_lo > rel_hi
    # but ranking is reversed
    swaps = 0
    pairs = 0
    ranked_map = {rid: idx for idx, rid in enumerate(retrieved)}
    sorted_rel = sorted(relevant_list, key=lambda r: r["relevance"], reverse=True)
    for i in range(len(sorted_rel)):
        for j in range(i + 1, len(sorted_rel)):
            ra = sorted_rel[i]
            rb = sorted_rel[j]
            if ra["relevance"] == rb["relevance"]:
                continue
            pairs += 1
            rank_a = ranked_map.get(ra["resume_id"], len(retrieved))
            rank_b = ranked_map.get(rb["resume_id"], len(retrieved))
            if (ra["relevance"] > rb["relevance"] and rank_a > rank_b) or \
               (ra["relevance"] < rb["relevance"] and rank_a < rank_b):
                swaps += 1
    q["pairwise_loss"] = (swaps, pairs)

    return q


# ── slot 解析 ────────────────────────────────────────────────────────

def parse_query_slot(query_text: str, query_type: str) -> Tuple[str, Dict]:
    """从 query 文本提取 CandidateSlot 参数"""
    years_match = re.search(r'(\d+)\s*年(以上)?', query_text)
    experience = int(years_match.group(1)) if years_match else 0

    skills: List[str] = []
    city: str = ""

    # 提取技能关键词
    if "会" in query_text:
        # "找会SKILL_A SKILL_B SKILL_C的候选人" 或 "找N年以上SKILL_A SKILL_B 经验"
        after_hui = query_text.split("会", 1)[1] if "会" in query_text else query_text
        skill_end = re.search(r'(的候选人|经验|$)', after_hui)
        if skill_end:
            skill_text = after_hui[:skill_end.start()].strip()
        else:
            skill_text = after_hui.strip()
        # 用中文顿号或空格分割
        raw_skills = re.split(r'[、，,]\s*', skill_text)
        for s in raw_skills:
            s = s.strip()
            if s and len(s) > 1 and not s.startswith("以上"):
                skills.append(s)

    # "要求X Y Z" 模式
    if "要求" in query_text:
        req_part = query_text.split("要求", 1)[1].strip()
        req_skills = re.split(r'[\s、，,]+', req_part)
        for s in req_skills:
            s = s.strip()
            if s and len(s) > 1 and s not in skills:
                skills.append(s)

    # 城市
    city_match = re.search(r'(北京|上海|深圳|广州|杭州|成都|武汉)', query_text)
    if city_match:
        city = city_match.group(1)

    # 职位
    job_title = ""
    title_match = re.search(r'(高级工程师|工程师|设计师|产品经理|架构师|前端|后端|全栈)', query_text)
    if title_match:
        job_title = title_match.group(1)

    return query_text, dict(
        job_title=job_title,
        skills=skills,
        experience=experience,
        city=city,
    )


# ── index ─────────────────────────────────────────────────────────────

def load_profiles() -> Dict[str, dict]:
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        profiles = json.load(f)
    return {p["resume_id"]: p for p in profiles}


def build_structured(profile: dict) -> Any:
    """从 extracted_profiles.json 重建 ResumeStructured 对象"""
    from src.resume_parser.llm_extractor import (
        ResumeStructured, PersonalInfo, EducationEntry,
        ExperienceEntry, ProjectEntry, SkillEntry,
    )

    personal = PersonalInfo(
        full_name=profile.get("name", ""),
        years_of_experience=profile.get("years_of_experience", 0),
        city=profile.get("city", ""),
    )
    education = []
    for e in profile.get("education", []):
        education.append(EducationEntry(
            school=e.get("school", ""),
            degree=e.get("degree", ""),
            major=e.get("major", ""),
        ))
    skills = []
    for s in profile.get("skill_details", []) or profile.get("skills", []):
        if isinstance(s, str):
            skills.append(SkillEntry(name=s))
        else:
            skills.append(SkillEntry(
                name=s.get("name", s),
                proficiency=s.get("proficiency"),
                years_of_experience=s.get("years"),
            ))
    return ResumeStructured(
        personal_info=personal,
        education_list=education,
        experience_list=[],
        project_list=[],
        skill_list=skills,
    )


def reset_milvus():
    from pymilvus import utility
    from src.vector_index.connection import get_milvus_connection

    conn = get_milvus_connection()
    conn.connect()
    if utility.has_collection("resume_chunks"):
        utility.drop_collection("resume_chunks")

    from src.vector_index.schema import get_collection_name, get_collection_schema
    from src.vector_index.index import Collection as PymilvusCollection
    schema = get_collection_schema()
    col = PymilvusCollection(name=get_collection_name(), schema=schema)

    from src.vector_index.index import get_vector_index
    vi = get_vector_index()
    vi.create_indexes()

    return col


def index_resumes(resume_ids: List[str], profiles: Dict[str, dict]):
    from src.resume_parser.text_extractor import TextExtractor
    from src.resume_parser.chunk_builder import ChunkBuilder
    from src.vector_index.vector_writer import get_vector_writer

    extractor = TextExtractor()
    builder = ChunkBuilder()
    writer = get_vector_writer()

    total = 0
    for resume_id in resume_ids:
        filepath = DATASET_DIR / f"{resume_id}.docx"
        if not filepath.exists():
            print(f"  [SKIP] {resume_id} (文件不存在)")
            continue

        content = filepath.read_bytes()
        doc = extractor.extract(content, filepath.name)
        profile = profiles.get(resume_id, {})
        structured = build_structured(profile)

        chunks = builder.generate_chunks(resume_id, structured, doc.raw_text)
        ids = writer.write_chunks(chunks, resume_id)
        total += len(ids)

    print(f"  索引完成: {total} 条 chunk")


# ── search ────────────────────────────────────────────────────────────

def search_query(
    query_text: str,
    slot_kwargs: Dict[str, Any],
    top_k: int = 20,
) -> List[str]:
    """执行一次检索，返回 resume_id 列表"""
    from src.intent_router.schemas import CandidateSlot
    from src.recommendation_engine.hybrid_retriever import get_hybrid_retriever

    slot = CandidateSlot(**slot_kwargs)
    retriever = get_hybrid_retriever()
    results = retriever.retrieve(slot, top_k=top_k, raw_query=query_text)

    seen = set()
    ids = []
    for r in results:
        if r.resume_id not in seen:
            seen.add(r.resume_id)
            ids.append(r.resume_id)
    return ids


# ── main ──────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="索引全部 33 份简历")
    parser.add_argument("--fast", action="store_true", default=True, help="只索引 evaluation 涉及的 8 份简历 (默认)")
    args = parser.parse_args()

    # 1. Load data
    with open(TRIPLETS_PATH, "r", encoding="utf-8") as f:
        triplets = json.load(f)

    profiles = load_profiles()

    # 确定要索引的 resume 集合
    if args.full:
        resume_ids = sorted(profiles.keys())
    else:
        eval_ids = set()
        for t in triplets:
            eval_ids.add(t["source_resume_id"])
            for r in t["relevant_resumes"]:
                eval_ids.add(r["resume_id"])
        resume_ids = sorted(eval_ids)

    print(f"{'='*60}")
    print(f"  回召率 & Loss 评估")
    print(f"  索引模式: {'全部' if args.full else '评估集'} ({len(resume_ids)} 份简历)")
    print(f"  查询数量: {len(triplets)} 条")
    print(f"{'='*60}")

    # 2. Reset & Index
    print("\n[1] 重置 Milvus Collection...")
    reset_milvus()

    print(f"\n[2] 索引 {len(resume_ids)} 份简历...")
    t0 = time.time()
    index_resumes(resume_ids, profiles)
    print(f"  耗时: {time.time()-t0:.1f}s")

    # 3. Run queries
    print(f"\n[3] 执行 {len(triplets)} 条查询...")
    query_results = []
    for i, t in enumerate(triplets):
        query_text = t["query"]
        query_type = t.get("query_type", "combined")
        relevant = t["relevant_resumes"]

        raw_query, slot_kwargs = parse_query_slot(query_text, query_type)

        retrieved = search_query(query_text, slot_kwargs, top_k=20)

        q_metrics = compute_per_query_metrics(retrieved, relevant)
        q_metrics["query"] = query_text
        q_metrics["query_type"] = query_type
        query_results.append(q_metrics)

        # 简短进度
        r5 = q_metrics["recalls"][5]
        r10 = q_metrics["recalls"][10]
        r20 = q_metrics["recalls"][20]
        print(f"  [{i+1:02d}/{len(triplets)}] type={query_type:<15s} R@5={r5:.2f} R@10={r10:.2f} R@20={r20:.2f} Q={query_text[:40]}")

    # 4. Aggregate
    print(f"\n[4] 汇总指标")
    agg = compute_metrics(query_results)

    # 按 query type 分组
    by_type: Dict[str, list] = {}
    for q in query_results:
        by_type.setdefault(q["query_type"], []).append(q)
    type_metrics = {}
    for qt, qlist in by_type.items():
        type_metrics[qt] = compute_metrics(qlist)
        type_metrics[qt]["count"] = len(qlist)

    print(f"\n  {'指标':<30s} {'汇总':>8s} {'skill':>8s} {'years_only':>8s} {'skill+years':>8s}")
    print(f"  {'-'*65}")
    for metric_key in ["avg_recall@5", "avg_recall@10", "avg_recall@20", "avg_mrr", "avg_ndcg@10", "avg_map", "pairwise_ranking_loss", "coverage"]:
        summary = agg.get(metric_key, 0)
        row = f"  {metric_key:<30s} {summary:>8.4f}"
        for qt in ["skill", "years_only", "skill+years", "job_title", "job_title+city", "combined"]:
            tm = type_metrics.get(qt, {})
            row += f" {tm.get(metric_key, 0):>8.4f}"
        print(row)

    # 5. Save report
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_queries": len(triplets),
        "indexed_resumes": len(resume_ids),
        "aggregate_metrics": agg,
        "by_query_type": type_metrics,
        "per_query": [
            {
                "query": q["query"],
                "query_type": q.get("query_type", ""),
                "retrieved": q["retrieved"],
                "relevant": q["relevant_list"],
                "recall@5": q["recalls"][5],
                "recall@10": q["recalls"][10],
                "recall@20": q["recalls"][20],
                "mrr": q["mrr"],
                "ndcg@10": q["ndcgs"][10],
                "ap": q["ap"],
                "pairwise_swaps": q["pairwise_loss"][0],
                "pairwise_pairs": q["pairwise_loss"][1],
            }
            for q in query_results
        ],
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n  ✅ 报告已保存: {REPORT_PATH}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
