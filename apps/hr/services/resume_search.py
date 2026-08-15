# coding=utf-8
"""
    @project: MaxKB
    @file： resume_search.py
    @date：2026/8/15
    @desc：简历语义检索服务（阶段 3）：
          模式 A（整句）：一次 embed → 双路独立召回(dense+sparse) → Python RRF 融合 → rerank 精排 → 简历聚合。
          模式 B（Skill-AND）：LLM 查询分解为有序技能列表 → 按序逐技能双路召回 → 命中向量字典序 → 顺位放宽 → rerank。
          降级链：rerank → RRF → dense 单路 → 空结果+meta。
          设计见 docs/superpowers/specs/2026-08-15-hr-resume-search-design.md。
"""
import time

from django.db.models import QuerySet
from knowledge.models import Document, Embedding, SearchMode
from knowledge.serializers.common import get_embedding_model_by_knowledge_id, list_paragraph
from knowledge.vector.pg_vector import EmbeddingSearch, KeywordsSearch

from common.exception.app_exception import AppApiException

from hr.models import Candidate, CandidateStatus, ResumeFile
from hr.services.ai_parser import parse_search_skills
from hr.services.audit import write_audit_log
from hr.services.resume_index import get_resume_knowledge

_RRF_K = 60
_MAX_SKILLS = 10
_DEFAULT_SIMILARITY = 0.2
_MAX_QUERY_LENGTH = 2000
_RESUME_SCORE_MAX_WEIGHT = 0.7
_RESUME_SCORE_AVG_WEIGHT = 0.3

_MODE_CHOICES = {"auto", "hybrid", "dense", "phrase", "skills"}


def _mask_phone(value):
    if not value:
        return value
    return value[:3] + "****" + value[-4:] if len(value) >= 7 else "****"


def _mask_email(value):
    if not value or "@" not in value:
        return value
    local, domain = value.split("@", 1)
    masked_local = local[:2] + "***" if len(local) > 2 else "***"
    return f"{masked_local}@{domain}"


def _mask_for_role(candidate, hr_role):
    """VIEWER 脱敏 phone/email；OPERATOR/ADMIN 原样。"""
    if candidate is None:
        return None
    out = {
        "id": str(candidate.id),
        "name": candidate.name,
        "highest_degree": candidate.highest_degree,
        "years_experience": candidate.years_experience,
        "skills": candidate.skills,
        "status": candidate.status,
        "phone": candidate.phone,
        "email": candidate.email,
    }
    if hr_role == "VIEWER":
        out["phone"] = _mask_phone(candidate.phone)
        out["email"] = _mask_email(candidate.email)
    return out


def _parse_skills(query, llm_model):
    """LLM 查询分解为有序技能列表（重要在前，≤10）。失败抛异常（调用方捕获退模式 A）。"""
    return parse_search_skills(llm_model, query)


def _exclude_documents(knowledge_id):
    return [
        str(document.id)
        for document in QuerySet(Document).filter(knowledge_id=knowledge_id, is_active=False)
    ]


def _sparse_query(query, max_terms=4):
    """关键词路查询截断：websearch_to_tsquery 的空格是 AND 语义，长查询会因
    "所有词都必须出现"而漏召回（实测完整句 0 命中）。取 jieba 切词前 max_terms 个
    有意义的词（去停用词）作为关键词路查询——BM25 常见做法，dense 路不受影响。"""
    import jieba

    stopwords = {"的", "了", "有", "和", "与", "过", "做", "在", "人", "我", "你", "他", "是", "会", "熟悉", "精通", "经验", "工作", "候选人", "负责"}
    terms = [t for t in jieba.lcut(query) if t.strip() and t not in stopwords and len(t) > 1]
    return " ".join(terms[:max_terms])


def _recall_dual(query, knowledge, embedding_model, candidate_k, similarity, use_sparse=True):
    """一次 embed，双路独立召回。返回 {dense: [...], sparse: [...], query_embedding, sparse_failed}。
    结果项: {paragraph_id, similarity}"""
    try:
        embedding_query = embedding_model.embed_query(query)
    except Exception:
        # Embedding 调用失败（模型不可用/输入超限等）：裸异常会 500，转为业务异常（设计：不抛未处理异常）
        raise AppApiException(500, "Embedding 调用失败，请稍后重试或检查模型配置")
    exclude_ids = _exclude_documents(knowledge.id)
    exclude_dict = {"document_id__in": exclude_ids} if exclude_ids else {}
    query_set = QuerySet(Embedding).filter(knowledge_id=knowledge.id, is_active=True).exclude(**exclude_dict)

    dense_results = EmbeddingSearch().handle(
        query_set, query, embedding_query, candidate_k, similarity, SearchMode.embedding, [knowledge.id]
    )
    sparse_results = []
    sparse_failed = False
    if use_sparse:
        try:
            sparse_query = _sparse_query(query)
            if sparse_query:
                # 关键词路用极低内部阈值（0.01）：websearch_to_tsquery 多词 AND 会稀释
                # ts_rank 分数（实测 幕墙 0.286 → 幕墙+系统+设计 0.193），若用与 dense 相同的
                # 0.2 阈值会误过滤高质量多词命中；质量筛选交给 RRF 的 rank 排序。
                sparse_results = KeywordsSearch().handle(
                    query_set, sparse_query, embedding_query, candidate_k, 0.01, SearchMode.keywords, [knowledge.id]
                )
        except Exception:
            sparse_results = []
            sparse_failed = True
    return {"dense": dense_results, "sparse": sparse_results, "query_embedding": embedding_query,
            "sparse_failed": sparse_failed}


def _rrf_fuse(dense, sparse, k=_RRF_K):
    """Python RRF：score(d) = Σ 1/(k+rank)。返回 [{paragraph_id, rrf, dense, sparse}] 降序。
    paragraph_id 统一转为 str（与 list_paragraph 返回的 id 字符串化对齐）。"""
    scores = {}
    for rank, item in enumerate(dense):
        pid = str(item.get("paragraph_id"))
        entry = scores.setdefault(pid, {"paragraph_id": pid, "rrf": 0.0, "dense": 0.0, "sparse": 0.0})
        entry["rrf"] += 1.0 / (k + rank + 1)
        entry["dense"] = item.get("similarity", 0.0)
    for rank, item in enumerate(sparse):
        pid = str(item.get("paragraph_id"))
        entry = scores.setdefault(pid, {"paragraph_id": pid, "rrf": 0.0, "dense": 0.0, "sparse": 0.0})
        entry["rrf"] += 1.0 / (k + rank + 1)
        entry["sparse"] = item.get("similarity", 0.0)
    return sorted(scores.values(), key=lambda x: x["rrf"], reverse=True)


def _rerank(query, fused, rerank_model, top_n):
    """bge-reranker 精排。异常 → (按 rrf 排序, False)。"""
    try:
        contents = [row.get("content", "") for row in fused]
        results = rerank_model.rerank(query, contents, top_n=top_n)
        # rerank API 返回 results 的 index = 输入 contents 的下标（按相关性降序排列）
        # 先把分数写回对应行（index 指向 fused 原下标），再按分数排序
        for item in results:
            index = item.get("index")
            if index is not None and 0 <= index < len(fused):
                fused[index]["rerank"] = item.get("relevance_score", 0)
        ordered = sorted(fused, key=lambda row: row.get("rerank", 0), reverse=True)
        return ordered, True
    except Exception:
        return fused, False


def _para_score(p):
    """段落主导分：rerank 启用且该段有 rerank 分时用 rerank 分，否则用 rrf 分。"""
    rerank = p.get("rerank")
    if rerank is not None and rerank > 0:
        return rerank
    return p.get("rrf", 0)


def _aggregate(paragraphs, hr_role):
    """Small-to-Big + 简历聚合（模式 A：0.7*max + 0.3*avg 段落主导分）。
    排序键优先 rerank 分（rerank 启用时），否则 rrf 分——避免 rerank 重排被 rrf 覆盖。"""
    doc_ids = [p.get("document_id") for p in paragraphs if p.get("document_id")]
    resumes = []
    resume_by_doc = {}
    if doc_ids:
        resumes = list(QuerySet(ResumeFile).filter(document_id__in=doc_ids).select_related("candidate"))
        resume_by_doc = {str(r.document_id): r for r in resumes}
    resume_map = {}
    for p in paragraphs:
        doc_id = str(p.get("document_id")) if p.get("document_id") else None
        resume_map.setdefault(doc_id, []).append(p)
    results = []
    for doc_id, ps in resume_map.items():
        score = _RESUME_SCORE_MAX_WEIGHT * max(_para_score(p) for p in ps) + _RESUME_SCORE_AVG_WEIGHT * (
            sum(_para_score(p) for p in ps) / len(ps)
        )
        resume = resume_by_doc.get(doc_id)
        candidate = resume.candidate if resume else None
        results.append({
            "candidate": _mask_for_role(candidate, hr_role),
            "resume": {"id": str(resume.id), "file_name": resume.file_name, "extension": resume.extension} if resume else None,
            "paragraphs": sorted(ps, key=_para_score, reverse=True),
            "document_id": doc_id,
            "score": score,
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def _search_skill_and(skills, workspace_id, knowledge, embedding_model, candidate_k, similarity, top_k):
    """模式 B 主干：语义路（按序逐技能双路召回，每技能一次 embed）→ 候选池累积（不截断）
    + 结构化路（Candidate.skills 精确命中，设计 §2 步骤2）→ 命中向量 OR 合并
    → 字典序排序 → 返回 [(doc_id, hit_vec)]。
    相对阈值原因：短技能词（java/fastapi/rag）对任意段落的 dense 相似度都在 0.2~0.42 区间，
    固定阈值会导致人人命中、命中向量失去区分度（实测）。"""
    pool = {}            # paragraph_id(str) -> row
    doc_skill_vec = {}   # document_id(str) -> hit_vec
    sparse_failed = False
    for skill_index, skill in enumerate(skills):
        recall = _recall_dual(skill, knowledge, embedding_model, candidate_k, similarity)
        sparse_failed = sparse_failed or recall.get("sparse_failed", False)
        fused = _rrf_fuse(recall["dense"], recall["sparse"])
        for row in fused:
            pool.setdefault(row["paragraph_id"], row)
        # 命中判定：相对阈值——该技能召回最高分的 75%（且 ≥ 绝对阈值）
        dense_sims = [item.get("similarity", 0) for item in recall["dense"]]
        top_sim = max(dense_sims) if dense_sims else 0
        hit_threshold = max(similarity, top_sim * 0.75)
        for item in recall["dense"]:
            if item.get("similarity", 0) >= hit_threshold:
                # 段落 → document 映射稍后统一补全，这里先记 paragraph 级命中。
                # 注意：pool 中可能已有该 pid（RRF 融合阶段），setdefault 不覆盖，
                # 因此 hit_skills 只能通过 setdefault+append 单次追加，避免双写。
                pid = str(item["paragraph_id"])
                entry = pool.setdefault(pid, {"paragraph_id": pid, "rrf": 0.0,
                                              "dense": item.get("similarity", 0.0), "sparse": 0.0})
                entry.setdefault("hit_skills", []).append(skill_index)
    # 补全段落 → document 映射
    p_list = list_paragraph(list(pool.keys()))
    p_by_id = {str(p.get("id")): p for p in p_list}
    for pid, row in pool.items():
        p = p_by_id.get(pid)
        row["content"] = p.get("content", "") if p else ""
        row["title"] = p.get("title", "") if p else ""
        row["document_id"] = str(p.get("document_id")) if p and p.get("document_id") else None
    # 简历级命中向量 + 每简历段落池（供 rerank 精排）
    doc_paragraphs = {}
    for pid, row in pool.items():
        doc_id = row.get("document_id")
        if doc_id is None:
            continue
        doc_paragraphs.setdefault(doc_id, []).append(row)
        vec = doc_skill_vec.setdefault(doc_id, [0] * len(skills))
        for skill_index in row.get("hit_skills", []):
            vec[skill_index] = 1
    # 结构化路（设计 §2 步骤2）：Candidate.skills 与有序技能列表的精确命中（忽略大小写，排除已删除/已归档候选人）
    structured_vec = {}    # document_id -> hit_vec（结构化命中）
    candidates = list(QuerySet(Candidate).filter(workspace_id=workspace_id, status=CandidateStatus.ACTIVE))
    hit_candidate_ids = []
    for candidate in candidates:
        candidate_skills = [s.lower() for s in (candidate.skills or [])]
        if not candidate_skills:
            continue
        vec = [1 if skill.lower() in candidate_skills else 0 for skill in skills]
        if any(vec):
            hit_candidate_ids.append((candidate.id, vec))
    if hit_candidate_ids:
        resumes = list(QuerySet(ResumeFile).filter(
            candidate_id__in=[candidate_id for candidate_id, _ in hit_candidate_ids], document_id__isnull=False))
        resume_by_candidate = {}
        for rf in resumes:
            resume_by_candidate.setdefault(str(rf.candidate_id), rf)
        for candidate_id, vec in hit_candidate_ids:
            rf = resume_by_candidate.get(str(candidate_id))
            if rf is not None:
                structured_vec[str(rf.document_id)] = vec
    # 两路命中向量合并：同一简历两路都命中 → 按位 OR（段落并集，不重复计）
    structured_only = {}   # document_id -> hit_vec（仅结构化命中、无语义段落）
    for doc_id, structured_hit in structured_vec.items():
        if doc_id in doc_skill_vec:
            doc_skill_vec[doc_id] = [a or b for a, b in zip(doc_skill_vec[doc_id], structured_hit)]
        else:
            doc_skill_vec[doc_id] = structured_hit
            doc_paragraphs[doc_id] = []
            structured_only[doc_id] = structured_hit
    # 字典序排序：命中靠前技能优先
    ordered = sorted(doc_skill_vec.items(), key=lambda item: tuple(item[1]), reverse=True)
    return ordered, {"rounds": len(skills), "pool_paragraphs": len(pool), "skill_relaxed": len(skills),
                     "doc_paragraphs": doc_paragraphs, "structured_only": structured_only,
                     "structured_hits": len(structured_vec), "sparse_failed": sparse_failed}


def search_resumes(workspace_id, query, top_k=5, recall_k=None, similarity=0.2,
                   mode="auto", hr_role=None, user_id=None, llm_model=None, rerank_model=None):
    """
    简历语义检索入口。返回 {"items": [...], "meta": {...}}。
    模式 A（整句）/ 模式 B（技能复合，auto 自动判定）。
    降级链：rerank → RRF → dense 单路 → 空结果。
    """
    t0 = time.time()
    if not isinstance(query, str) or not query.strip():
        raise AppApiException(400, "query is required")
    if len(query) > _MAX_QUERY_LENGTH:
        raise AppApiException(400, "query is too long")
    if not isinstance(mode, str) or mode not in _MODE_CHOICES:
        raise AppApiException(400, "mode must be one of auto|hybrid|dense|phrase|skills")
    if not isinstance(top_k, int) or not (1 <= top_k <= 20):
        raise AppApiException(400, "top_k must be in [1, 20]")
    # recall_k/similarity 按设计契约 clamp（设计 §3.1：[5,60] / [0,2]），负数不得进入 SQL（PG LIMIT 报错）
    recall_k = recall_k if recall_k is not None else max(5, min(60, top_k * 3))
    recall_k = max(5, min(60, recall_k))
    similarity = max(0.0, min(2.0, similarity))

    knowledge = get_resume_knowledge(workspace_id)
    if knowledge is None:
        raise AppApiException(400, "简历语义索引尚未建立")
    try:
        embedding_model = get_embedding_model_by_knowledge_id(knowledge.id)
    except Exception:
        # 知识库绑定的 Embedding 模型缺失/异常：裸异常会 500，转为业务异常（设计：不抛未处理异常）
        raise AppApiException(500, "Embedding 模型不可用，无法执行语义检索")

    meta = {"mode": mode, "search_type": "", "skills": [], "recall": {}, "rerank": {},
            "aggregation": {}, "elapsed_ms": {}, "query": {"length": len(query), "truncated": False}}

    # ---------- 查询理解：技能分解（模式 B 判定） ----------
    skills = []
    if mode in ("auto", "skills"):
        if llm_model is not None:
            try:
                skills = _parse_skills(query, llm_model)
            except Exception:
                skills = []
        meta["skills"] = skills[: _MAX_SKILLS]
        meta["skills_truncated"] = len(skills) > _MAX_SKILLS
        skills = skills[: _MAX_SKILLS]
    if mode == "auto":
        if len(skills) >= 2:
            mode = "skills"
        else:
            mode = "phrase"
        meta["mode"] = mode
    elif mode == "skills" and len(skills) < 2:
        # 显式 skills 模式但技能解析失败/不足（LLM 未配置/异常）：退化整句检索，meta 如实反映
        mode = "phrase"
        meta["mode"] = "phrase"

    # ---------- 模式 B：Skill-AND ----------
    if mode == "skills" and len(skills) >= 2:
        ordered, b_meta = _search_skill_and(
            skills, workspace_id, knowledge, embedding_model, recall_k, similarity, top_k
        )
        doc_paragraphs = b_meta.pop("doc_paragraphs", {})
        structured_only = b_meta.pop("structured_only", {})
        sparse_failed = b_meta.pop("sparse_failed", False)
        structured_hits = b_meta.pop("structured_hits", 0)
        meta.update(b_meta)
        meta["recall"] = {"rounds": b_meta["rounds"], "pool_paragraphs": b_meta["pool_paragraphs"],
                          "candidate_k": recall_k, "sparse_failed": sparse_failed,
                          "structured_hits": structured_hits}
        # 候选段落：按 hit_vec 排序取前 candidate_k 简历的最优段落（Small-to-Big 回溯到段落）
        cand_docs = [doc_id for doc_id, _ in ordered[: max(top_k * 3, recall_k)]]
        cand_paras = []
        for doc_id in cand_docs:
            best = None
            for row in doc_paragraphs.get(doc_id, []):
                if best is None or _para_score(row) > _para_score(best):
                    best = row
            if best is not None:
                cand_paras.append(best)
        # Rerank 精排（设计步骤 6）：对候选段落精排，失败降级 hit_vec 顺序
        reranked = False
        if rerank_model is not None and cand_paras:
            cand_paras, reranked = _rerank(query, cand_paras, rerank_model, top_k)
        meta["rerank"] = {"enabled": rerank_model is not None, "top_n": top_k, "failed": rerank_model is not None and not reranked,
                          "model": getattr(rerank_model, "model_name", None) if rerank_model else None}
        meta["search_type"] = "skill_ordered_reranked" if reranked else ("skill_ordered" if rerank_model is None else "skill_ordered_fallback")
        # 按 rerank 分排序取 top_k，回溯候选人
        seen = set()
        items = []
        for row in cand_paras:
            doc_id = row.get("document_id")
            if doc_id is None or doc_id in seen:
                continue
            seen.add(doc_id)
            hit_vec = dict(ordered).get(doc_id, [0] * len(skills))
            resume = QuerySet(ResumeFile).filter(document_id=doc_id).select_related("candidate").first()
            items.append({
                "rank": len(items) + 1,
                "candidate": _mask_for_role(resume.candidate if resume else None, hr_role),
                "resume": {"id": str(resume.id), "file_name": resume.file_name, "extension": resume.extension} if resume else None,
                "score": {"hit_vec": hit_vec, "hit_count": sum(hit_vec), "rerank": _para_score(row)},
                "paragraphs": [{"id": row.get("paragraph_id"), "title": row.get("title"), "content": row.get("content"), "score": _para_score(row)}],
                "document_id": doc_id,
            })
            if len(items) >= top_k:
                break
        # 结构化-only 命中补位（设计 §2 步骤2：结构化字段精确满足、正文未命中 → 直接进候选）：
        # 无段落可精排，按命中向量字典序排在 rerank 结果之后
        if len(items) < top_k and structured_only:
            seen_docs = {item["document_id"] for item in items}
            for doc_id, hit_vec in sorted(structured_only.items(), key=lambda kv: tuple(kv[1]), reverse=True):
                if doc_id in seen_docs:
                    continue
                seen_docs.add(doc_id)
                resume = QuerySet(ResumeFile).filter(document_id=doc_id).select_related("candidate").first()
                items.append({
                    "rank": len(items) + 1,
                    "candidate": _mask_for_role(resume.candidate if resume else None, hr_role),
                    "resume": {"id": str(resume.id), "file_name": resume.file_name, "extension": resume.extension} if resume else None,
                    "score": {"hit_vec": hit_vec, "hit_count": sum(hit_vec), "rerank": 0},
                    "paragraphs": [],
                    "document_id": doc_id,
                })
                if len(items) >= top_k:
                    break
        meta["aggregation"] = {"grouped_resumes": len(items)}
        meta["elapsed_ms"]["total"] = int((time.time() - t0) * 1000)
        _write_search_audit(workspace_id, user_id, query, top_k, meta, len(items))
        return {"items": items, "meta": meta}

    # ---------- 模式 A：整句 ----------
    use_sparse = mode in ("auto", "hybrid", "phrase")
    recall = _recall_dual(query, knowledge, embedding_model, recall_k, similarity, use_sparse=use_sparse)
    fused = _rrf_fuse(recall["dense"], recall["sparse"])
    meta["recall"] = {"dense": len(recall["dense"]), "sparse": len(recall["sparse"]), "fused": len(fused),
                      "candidate_k": recall_k, "sparse_failed": recall.get("sparse_failed", False)}
    if not fused:
        meta["search_type"] = "empty"
        meta["elapsed_ms"]["total"] = int((time.time() - t0) * 1000)
        _write_search_audit(workspace_id, user_id, query, top_k, meta, 0)
        return {"items": [], "meta": meta}

    # 补全段落信息
    p_list = list_paragraph([row["paragraph_id"] for row in fused])
    p_by_id = {str(p.get("id")): p for p in p_list}
    for row in fused:
        p = p_by_id.get(row["paragraph_id"])
        row["content"] = p.get("content", "") if p else ""
        row["title"] = p.get("title", "") if p else ""
        row["document_id"] = str(p.get("document_id")) if p and p.get("document_id") else None

    # rerank 精排
    reranked = False
    if rerank_model is not None:
        fused, reranked = _rerank(query, fused, rerank_model, top_k)
    meta["rerank"] = {"enabled": rerank_model is not None, "top_n": top_k, "failed": rerank_model is not None and not reranked,
                      "model": getattr(rerank_model, "model_name", None) if rerank_model else None}
    meta["search_type"] = "hybrid_rrf_reranked" if reranked else ("hybrid_rrf" if rerank_model is None else "hybrid_rrf_fallback")

    # 简历聚合
    aggregated = _aggregate(fused, hr_role)
    orphan_count = sum(1 for p in fused if not p.get("document_id"))
    meta["aggregation"] = {"grouped_resumes": len(aggregated), "dropped_orphan_paragraphs": orphan_count}

    items = []
    for idx, a in enumerate(aggregated[:top_k], 1):
        top_paragraph = a["paragraphs"][0]
        items.append({
            "rank": idx,
            "candidate": a["candidate"],
            "resume": a["resume"],
            "score": {
                "resume": a["score"],
                "rerank": top_paragraph.get("rerank", 0),
                "rrf": top_paragraph.get("rrf", 0),
                "dense": top_paragraph.get("dense", 0),
                "sparse": top_paragraph.get("sparse", 0),
            },
            "paragraphs": [
                {"id": p.get("paragraph_id"), "title": p.get("title"), "content": p.get("content"),
                 "score": p.get("rerank") if p.get("rerank") is not None else p.get("rrf", 0)}
                for p in a["paragraphs"]
            ],
            "document_id": a["document_id"],
        })
    meta["elapsed_ms"]["total"] = int((time.time() - t0) * 1000)
    _write_search_audit(workspace_id, user_id, query, top_k, meta, len(items))
    return {"items": items, "meta": meta}


def _write_search_audit(workspace_id, user_id, query, top_k, meta, hit_count):
    """SEARCH 审计：查询原文不入库（PII 治理）。"""
    if user_id is None:
        return
    try:
        write_audit_log(
            workspace_id, user_id, "SEARCH", "RESUME",
            detail={"query_len": len(query), "top_k": top_k, "mode": meta.get("mode"),
                    "hit_count": hit_count, "search_type": meta.get("search_type")},
        )
    except Exception:
        pass
