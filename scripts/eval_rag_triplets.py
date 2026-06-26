"""
RAG 评估三元组体系 — 简历推荐系统
=====================================
三元组结构:
  - query: 招聘搜索查询
  - relevant_resume_ids: 标注为相关的简历 ID 列表
  - query_metadata: {job_title, skills, experience, education, ...}

评估指标:
  - Recall@K: 前K个结果中命中相关简历的比例
  - Precision@K: 前K个结果中相关简历的占比
  - MRR: 第一个相关结果排名的倒数均值
  - NDCG@K: 归一化折损累计增益

伪标注策略:
  1. LLM 提取每份简历的结构化信息 (job_title, skills, etc.)
  2. 基于提取信息生成合成查询 (e.g., "找{job_title} 要求{skills}")
  3. 生成查询的简历自身标记为 relevant (id=1 相关度)
  4. 同岗位/同技能的简历标记为 partially relevant (id=0.5)
"""

import sys, os, json, time, math
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple

sys.path.insert(0, ".")

DATASET = r"C:\Users\Administrator\Downloads\数据集"
OUTPUT_DIR = "data/evaluation"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# PHASE 1: 批量 LLM 提取
# ============================================================
def phase1_extract_all():
    """对 33 份简历批量执行 LLM 结构化提取，缓存结果"""
    cache_file = os.path.join(OUTPUT_DIR, "extracted_profiles.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            profiles = json.load(f)
        print(f"Loaded {len(profiles)} cached profiles from {cache_file}")
        return profiles

    from src.resume_parser.text_extractor import get_text_extractor
    from src.resume_parser.llm_extractor import get_llm_extractor

    files = sorted([f for f in os.listdir(DATASET) if f.endswith(".docx")])
    extractor = get_text_extractor()
    llm = get_llm_extractor()

    profiles = []
    for i, fn in enumerate(files):
        fpath = os.path.join(DATASET, fn)
        with open(fpath, "rb") as f:
            doc = extractor.extract(f.read(), fn)

        print(f"[{i+1}/{len(files)}] Extracting {fn} ({len(doc.raw_text)} chars)...")
        structured = llm.extract(doc.raw_text)

        pi = structured.personal_info
        profile = {
            "file": fn,
            "resume_id": fn.replace(".docx", ""),
            "name": pi.full_name or "",
            "job_title": pi.current_title or "",
            "years_of_experience": pi.years_of_experience or 0,
            "skills": [s.name for s in structured.skill_list if s.name],
            "skill_details": [
                {"name": s.name, "proficiency": s.proficiency, "years": s.years_of_experience}
                for s in structured.skill_list if s.name
            ],
            "education": [
                {"school": e.school, "degree": e.degree, "major": e.major}
                for e in structured.education_list if e.school
            ],
            "city": pi.city or pi.expected_city or "",
            "industry": "",
            "confidence": structured.confidence_score,
        }
        profiles.append(profile)

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(profiles)} profiles to {cache_file}")
    return profiles


# ============================================================
# PHASE 2: 生成评估三元组
# ============================================================
def phase2_generate_triplets(profiles: List[Dict]) -> List[Dict]:
    """基于提取的结构化信息生成评估三元组"""
    triplets = []

    for p in profiles:
        # Determine query type based on available data
        job_title = p.get("job_title", "")
        skills = p.get("skills", [])
        city = p.get("city", "")
        yrs = p.get("years_of_experience", 0)

        # Build diverse query templates
        queries = []

        # Type A: 岗位搜索
        if job_title:
            queries.append({
                "query": f"找{job_title}",
                "query_type": "job_title",
                "weight": 1.0,
            })
            if city:
                queries.append({
                    "query": f"找{city}的{job_title}",
                    "query_type": "job_title+city",
                    "weight": 1.0,
                })

        # Type B: 技能搜索
        if skills:
            top_skills = skills[:3]
            skill_str = " ".join(top_skills)
            queries.append({
                "query": f"找会{skill_str}的候选人",
                "query_type": "skill",
                "weight": 1.0,
            })
            if yrs > 0:
                queries.append({
                    "query": f"找{yrs}年以上{skill_str}经验",
                    "query_type": "skill+years",
                    "weight": 1.0,
                })

        # Type C: 综合搜索
        if job_title and skills:
            top_skills = skills[:2]
            skill_str = " ".join(top_skills)
            queries.append({
                "query": f"找{job_title} 要求{skill_str}",
                "query_type": "combined",
                "weight": 1.0,
            })

        # Type D: 年限搜索
        if yrs > 0:
            queries.append({
                "query": f"找{int(yrs)}年工作经验",
                "query_type": "years_only",
                "weight": 0.5,  # Less specific
            })

        # Determine relevant resumes for each query
        for q in queries:
            relevant = _compute_relevance(p, q, profiles)
            triplets.append({
                "query": q["query"],
                "query_type": q["query_type"],
                "query_weight": q["weight"],
                "source_resume_id": p["resume_id"],
                "relevant_resumes": relevant,
            })

    print(f"Generated {len(triplets)} evaluation triplets from {len(profiles)} profiles")

    # Save triplets
    triplet_file = os.path.join(OUTPUT_DIR, "evaluation_triplets.json")
    with open(triplet_file, "w", encoding="utf-8") as f:
        json.dump(triplets, f, ensure_ascii=False, indent=2)
    print(f"Saved triplets to {triplet_file}")

    return triplets


def _compute_relevance(source_profile: Dict, query: Dict, all_profiles: List[Dict]) -> List[Dict]:
    """计算每份简历对查询的相关度 (0~1)"""
    relevant = []

    for p in all_profiles:
        score = 0.0
        reasons = []

        # 自身: 最高相关度
        if p["resume_id"] == source_profile["resume_id"]:
            score = 1.0
            reasons.append("self")
        else:
            # 岗位匹配
            if source_profile.get("job_title") and p.get("job_title"):
                if source_profile["job_title"] == p["job_title"]:
                    score += 0.4
                    reasons.append("same_title")
                elif _partial_match(source_profile["job_title"], p["job_title"]):
                    score += 0.2
                    reasons.append("similar_title")

            # 技能匹配
            src_skills = set(s.lower() for s in source_profile.get("skills", []))
            tgt_skills = set(s.lower() for s in p.get("skills", []))
            if src_skills and tgt_skills:
                overlap = src_skills & tgt_skills
                if overlap:
                    skill_score = len(overlap) / max(len(src_skills), len(tgt_skills))
                    score += 0.3 * skill_score
                    if skill_score > 0.5:
                        reasons.append("skill_match")

            # 城市匹配
            if source_profile.get("city") and p.get("city"):
                if source_profile["city"] in p["city"] or p["city"] in source_profile["city"]:
                    score += 0.1
                    reasons.append("same_city")

            # 年限接近
            src_yrs = source_profile.get("years_of_experience", 0) or 0
            tgt_yrs = p.get("years_of_experience", 0) or 0
            if src_yrs > 0 and tgt_yrs > 0:
                diff = abs(src_yrs - tgt_yrs)
                if diff <= 2:
                    score += 0.1 * (1 - diff / 3)
                    reasons.append("similar_years")

        score = min(1.0, score)

        # Include if any relevance
        if score > 0:
            relevant.append({
                "resume_id": p["resume_id"],
                "relevance": round(score, 2),
                "reasons": reasons,
            })

    # Sort by relevance desc
    relevant.sort(key=lambda x: x["relevance"], reverse=True)
    return relevant


def _partial_match(a: str, b: str) -> bool:
    """检查两个字符串是否有部分匹配"""
    if not a or not b:
        return False
    # Check if one contains the other
    if a in b or b in a:
        return True
    # Check word overlap
    a_words = set(a.replace("/", " ").split())
    b_words = set(b.replace("/", " ").split())
    if a_words & b_words:
        return True
    return False


# ============================================================
# PHASE 3: 检索评估
# ============================================================
def phase3_evaluate(triplets: List[Dict], profiles: List[Dict]):
    """运行检索评估，计算各项指标"""

    # Index all resumes first
    print("\n=== Indexing all resumes for evaluation ===")
    _index_all_resumes(profiles)

    from src.recommendation_engine.hybrid_retriever import get_hybrid_retriever
    from src.intent_router.schemas import CandidateSlot

    retriever = get_hybrid_retriever()

    all_metrics = []
    per_query_results = []

    for i, triplet in enumerate(triplets):
        query_text = triplet["query"]
        relevant_ids = {r["resume_id"]: r["relevance"] for r in triplet["relevant_resumes"]}

        # Execute retrieval
        try:
            results = retriever.retrieve(
                CandidateSlot(job_title=query_text),
                top_k=20,
                raw_query=query_text,
            )
        except Exception as e:
            print(f"  [{i}] ERROR: {e}")
            continue

        # Deduplicate by resume_id
        seen = set()
        retrieved_ids = []
        retrieved_scores = []
        for r in results:
            if r.resume_id not in seen:
                seen.add(r.resume_id)
                retrieved_ids.append(r.resume_id)
                retrieved_scores.append(r.score)

        # Compute metrics
        K_values = [1, 3, 5, 10, 20]
        metrics = {"query": query_text, "query_type": triplet["query_type"]}

        for K in K_values:
            top_k_ids = retrieved_ids[:K]
            # Recall@K
            relevant_retrieved = sum(
                relevant_ids.get(rid, 0) >= 0.5
                for rid in top_k_ids
            )
            total_relevant = sum(1 for v in relevant_ids.values() if v >= 0.5)
            if total_relevant > 0:
                metrics[f"recall@{K}"] = round(relevant_retrieved / total_relevant, 4)
            else:
                metrics[f"recall@{K}"] = 0.0

            # Precision@K
            highly_relevant = sum(
                relevant_ids.get(rid, 0) >= 0.8
                for rid in top_k_ids
            )
            metrics[f"precision@{K}"] = round(highly_relevant / min(K, len(top_k_ids)), 4) if top_k_ids else 0.0

        # MRR
        for rank, rid in enumerate(retrieved_ids, 1):
            if relevant_ids.get(rid, 0) >= 0.5:
                metrics["mrr"] = round(1.0 / rank, 4)
                break
        else:
            metrics["mrr"] = 0.0

        # NDCG@10
        dcg = 0.0
        idcg = 0.0
        ideal_relevances = sorted(relevant_ids.values(), reverse=True)
        for rank, rid in enumerate(retrieved_ids[:10], 1):
            rel = relevant_ids.get(rid, 0)
            dcg += rel / math.log2(rank + 1)
        for rank, rel in enumerate(ideal_relevances[:10], 1):
            idcg += rel / math.log2(rank + 1)
        metrics["ndcg@10"] = round(dcg / idcg, 4) if idcg > 0 else 0.0

        all_metrics.append(metrics)
        per_query_results.append({
            "query": query_text,
            "retrieved": retrieved_ids[:10],
            "relevant": sorted(relevant_ids.items(), key=lambda x: x[1], reverse=True)[:5],
        })

        if (i + 1) % 10 == 0:
            print(f"  Evaluated {i+1}/{len(triplets)} queries")

    # Aggregate metrics
    agg = {}
    for key in all_metrics[0].keys():
        if key not in ("query", "query_type") and isinstance(all_metrics[0][key], (int, float)):
            values = [m[key] for m in all_metrics]
            agg[f"avg_{key}"] = round(sum(values) / len(values), 4)
            agg[f"max_{key}"] = round(max(values), 4)

    by_type = defaultdict(list)
    for m in all_metrics:
        by_type[m.get("query_type", "unknown")].append(m)

    type_summary = {}
    for qtype, metrics_list in by_type.items():
        type_summary[qtype] = {
            "count": len(metrics_list),
            "avg_recall@5": round(sum(m.get("recall@5", 0) for m in metrics_list) / len(metrics_list), 4),
            "avg_recall@10": round(sum(m.get("recall@10", 0) for m in metrics_list) / len(metrics_list), 4),
            "avg_mrr": round(sum(m.get("mrr", 0) for m in metrics_list) / len(metrics_list), 4),
            "avg_ndcg@10": round(sum(m.get("ndcg@10", 0) for m in metrics_list) / len(metrics_list), 4),
        }

    report = {
        "generated_at": datetime.now().isoformat(),
        "total_queries": len(all_metrics),
        "aggregate_metrics": agg,
        "by_query_type": type_summary,
        "per_query": per_query_results[:20],  # Top 20 for inspection
    }

    report_file = os.path.join(OUTPUT_DIR, "evaluation_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nSaved evaluation report to {report_file}")
    return report


def _index_all_resumes(profiles: List[Dict]):
    """将全部简历索引到 Milvus"""
    from src.resume_parser.text_extractor import get_text_extractor
    from src.services.indexing import index_resume

    extractor = get_text_extractor()
    indexed = 0
    for p in profiles:
        fn = p["file"]
        fpath = os.path.join(DATASET, fn)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, "rb") as f:
                doc = extractor.extract(f.read(), fn)
            chunk_count = index_resume(p["resume_id"], doc.raw_text)
            indexed += 1
            if indexed % 5 == 0:
                print(f"  Indexed {indexed}/{len(profiles)} resumes")
        except Exception as e:
            print(f"  WARN: Failed to index {fn}: {e}")

    print(f"  Total indexed: {indexed}/{len(profiles)}")


# ============================================================
# PHASE 4: 输出报告
# ============================================================
def phase4_print_report(report: Dict):
    """打印评估报告"""
    print("\n" + "=" * 70)
    print("  RAG EVALUATION REPORT — 简历推荐系统")
    print("=" * 70)

    agg = report["aggregate_metrics"]
    print(f"\n  Total Queries: {report['total_queries']}")
    print(f"\n  Aggregate Metrics:")
    print(f"    Recall@5:       {agg.get('avg_recall@5', 'N/A')}")
    print(f"    Recall@10:      {agg.get('avg_recall@10', 'N/A')}")
    print(f"    Recall@20:      {agg.get('avg_recall@20', 'N/A')}")
    print(f"    Precision@5:    {agg.get('avg_precision@5', 'N/A')}")
    print(f"    MRR:            {agg.get('avg_mrr', 'N/A')}")
    print(f"    NDCG@10:        {agg.get('avg_ndcg@10', 'N/A')}")

    print(f"\n  By Query Type:")
    for qtype, m in report.get("by_query_type", {}).items():
        print(f"    {qtype} (n={m['count']}):")
        print(f"      Recall@5={m['avg_recall@5']}, Recall@10={m['avg_recall@10']}, "
              f"MRR={m['avg_mrr']}, NDCG@10={m['avg_ndcg@10']}")

    print(f"\n  Sample Results (top 5):")
    for r in report.get("per_query", [])[:5]:
        print(f"    Q: {r['query'][:60]}")
        print(f"      Retrieved: {r['retrieved'][:5]}")
        rel = [f"{rid}({score})" for rid, score in r['relevant'][:3]]
        print(f"      Relevant:  {rel}")

    print("\n" + "=" * 70)


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=" * 70)
    print("RAG Evaluation Triplet Pipeline")
    print("=" * 70)

    t0 = time.time()

    print("\n--- Phase 1: LLM Extraction ---")
    profiles = phase1_extract_all()

    print(f"\n--- Phase 2: Generate Triplets ---")
    triplets = phase2_generate_triplets(profiles)

    print(f"\n--- Phase 3: Retrieval Evaluation ---")
    report = phase3_evaluate(triplets, profiles)

    print(f"\n--- Phase 4: Report ---")
    phase4_print_report(report)

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed:.1f}s")
