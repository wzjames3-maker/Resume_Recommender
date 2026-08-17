# coding=utf-8
"""
    @project: MaxKB
    @file： resume_search.py
    @date：2026/8/15
    @desc：简历语义检索服务（阶段 3）：
          模式 A（整句）：一次 embed → 双路独立召回(dense+sparse) → Python RRF 融合 → rerank 精排 → 简历聚合。
          模式 B（Skill-AND）：LLM 查询分解为有序技能列表 → 按序逐技能双路召回 → 命中向量字典序 → 顺位放宽 → rerank。
          降级链：rerank → RRF → dense 单路 → 空结果+meta。
          设计见 docs/RAG-V2-DESIGN.md。
"""
import math
import os
import re
import time

from django.db.models import F, Q, QuerySet
from knowledge.models import Document, Embedding, SearchMode
from knowledge.serializers.common import get_embedding_model_by_knowledge_id, list_paragraph
from knowledge.vector.pg_vector import EmbeddingSearch, KeywordsSearch

from common.exception.app_exception import AppApiException

from hr.models import Candidate, CandidateSkill, CandidateStatus, ResumeFile
from hr.services.ai_parser import parse_search_skills
from hr.services.audit import write_audit_log
from hr.services.query_understand import degree_words, extract_slots, norm_city
from hr.services.resume_index import get_resume_knowledge
from hr.services.skill_normalize import normalize_skill
def _env_float(name, default):
    """环境变量覆盖（F6）：解析失败回退默认并告警，避免非法值静默生效。"""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        import logging
        logging.getLogger("hr").warning("环境变量 %s 非法（%r），使用默认 %s", name, raw, default)
        return default


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        import logging
        logging.getLogger("hr").warning("环境变量 %s 非法（%r），使用默认 %s", name, raw, default)
        return default


_RRF_K = 60
_MAX_SKILLS = 10
_DEFAULT_SIMILARITY = 0.2
_MAX_QUERY_LENGTH = 2000
# 证据合成（T3，仅模式 A）：score = 聚合基准 + λ·log2(1 + 命中段数)。
# 聚合基准 = 0.7*max(段分) + 0.3*avg(段分)（v2 修复 F2 恢复：λ=0 严格回退旧行为，兑现「置 0 回退」承诺）。
# λ 默认 0（关闭）：真实模型消融显示
# λ=0.15 综合劣于 λ=0：recall@5 主指标全面下降（dense 0.75→0.67；RRF+rerank 0.92→0.83），
# 但 RRF 无 rerank 的 recall@5（0.67→0.75）与 RRF+rerank 的 Top-1/MRR（0.58→0.67 / 0.680→0.705）三格回升；
_EVIDENCE_LAMBDA = _env_float("MAXKB_HR_EVIDENCE_LAMBDA", 0.0)
# 聚合权重（与 be6e659 实施前行为一致；tests 有公式锁定断言防再次静默漂移）
_RESUME_SCORE_MAX_WEIGHT = 0.7
_RESUME_SCORE_AVG_WEIGHT = 0.3
# 结构化预筛上限（T4）：预筛文档集超过该值则放弃预筛转全量语义（避免误伤大库）；可用环境变量覆盖
_PREFILTER_MAX = _env_int("MAXKB_HR_MAX_PREFILTER", 2000)
# 姓名快速通道（T4）：纯 2-4 字中文查询走 name__icontains 并置顶
_NAME_RE = re.compile(r"^[\u4e00-\u9fa5]{2,4}$")

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
        "years_unknown": candidate.years_experience is None,
        "skills": candidate.skills,
        "status": candidate.status,
        "phone": candidate.phone,
        "email": candidate.email,
        "current_city": candidate.current_city,  # A2 复审：评测核对与前端展示用（城市非 PII）
    }
    if hr_role == "VIEWER":
        out["phone"] = _mask_phone(candidate.phone)
        out["email"] = _mask_email(candidate.email)
    return out


def _candidate_matches_hard_slots(candidate, slots):
    """预筛超阈值跳过后的硬条件后置过滤（与 L1 SQL 语义一致）：
    年限 NULL 按满足计（线上 R2 语义）；学历按词表层级；城市按归一形双向匹配。"""
    if candidate is None:
        return False
    if slots["years_min"] is not None:
        if candidate.years_experience is not None and candidate.years_experience < slots["years_min"]:
            return False
    if slots["degree_level"] is not None:
        if candidate.highest_degree not in degree_words(slots["degree_level"]):
            return False
    for city in slots["cities"]:
        norm = norm_city(city)
        if norm_city(candidate.current_city or "") not in {norm, city, norm + "市"}:
            return False
    return True


def _parse_skills(query, llm_model):
    """LLM 查询分解为有序技能列表（重要在前，≤10）。失败抛异常（调用方捕获退模式 A）。"""
    return parse_search_skills(llm_model, query)


def _exclude_documents(knowledge_id):
    return [
        str(document.id)
        for document in QuerySet(Document).filter(knowledge_id=knowledge_id, is_active=False)
    ]


def _sparse_query(query, max_terms=6):
    """关键词路查询截断：websearch_to_tsquery 的空格是 AND 语义，长查询会因
    "所有词都必须出现"而漏召回（实测完整句 0 命中）。取 jieba 切词前 max_terms 个
    有意义的词（去停用词）作为关键词路查询——BM25 常见做法，dense 路不受影响。"""
    import jieba

    stopwords = {"的", "了", "有", "和", "与", "过", "做", "在", "人", "我", "你", "他", "是", "会", "熟悉", "精通", "经验", "工作", "候选人", "负责"}
    terms = [t for t in jieba.lcut(query) if t.strip() and t not in stopwords and len(t) > 1]
    return " ".join(terms[:max_terms])


def _recall_dual(query, knowledge, embedding_model, candidate_k, similarity, use_sparse=True, document_ids=None):
    """一次 embed，双路独立召回。返回 {dense: [...], sparse: [...], query_embedding, sparse_failed}。
    结果项: {paragraph_id, similarity}。document_ids（T4）：结构化预筛后的文档集，限定召回范围。"""
    try:
        embedding_query = embedding_model.embed_query(query)
    except Exception:
        # Embedding 调用失败（模型不可用/输入超限等）：裸异常会 500，转为业务异常（设计：不抛未处理异常）
        raise AppApiException(500, "Embedding 调用失败，请稍后重试或检查模型配置")
    exclude_ids = _exclude_documents(knowledge.id)
    exclude_dict = {"document_id__in": exclude_ids} if exclude_ids else {}
    query_set = QuerySet(Embedding).filter(knowledge_id=knowledge.id, is_active=True).exclude(**exclude_dict)
    if document_ids:
        query_set = query_set.filter(document_id__in=document_ids)

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
    """Small-to-Big + 简历聚合（模式 A，T3 证据合成）：
    score = (0.7*max(段分) + 0.3*avg(段分)) + λ·log2(1 + 命中段数)——基准加权 + 多段证据加分
    （"金融背景"命中工作+项目两段 > 只命中一段）。λ=0 严格回退旧行为（0.7*max+0.3*avg，F2 恢复）。
    段分优先 rerank 分（rerank 启用时），否则 rrf 分——避免 rerank 重排被 rrf 覆盖。"""
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
        para_scores = [_para_score(p) for p in ps]
        base = _RESUME_SCORE_MAX_WEIGHT * max(para_scores) + _RESUME_SCORE_AVG_WEIGHT * (
            sum(para_scores) / len(para_scores)
        )
        score = base + _EVIDENCE_LAMBDA * math.log2(1 + len(ps))
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


def _search_skill_and(skills, workspace_id, knowledge, embedding_model, candidate_k, similarity, top_k, document_ids=None):
    """模式 B 主干：语义路（按序逐技能双路召回，每技能一次 embed）→ 候选池累积（不截断）
    + 结构化路（Candidate.skills 精确命中，设计 §2 步骤2）→ 命中向量 OR 合并
    → 字典序排序 → 返回 [(doc_id, hit_vec)]。
    document_ids（F1）：结构化预筛文档集（skills 模式的年限/学历/城市硬条件），
    语义路与结构化路均限定在该集内；None 表示不限定。
    相对阈值原因：短技能词（java/fastapi/rag）对任意段落的 dense 相似度都在 0.2~0.42 区间，
    固定阈值会导致人人命中、命中向量失去区分度（实测）。"""
    pool = {}            # paragraph_id(str) -> row
    doc_skill_vec = {}   # document_id(str) -> hit_vec
    sparse_failed = False
    for skill_index, skill in enumerate(skills):
        recall = _recall_dual(skill, knowledge, embedding_model, candidate_k, similarity, document_ids=document_ids)
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
    # 结构化路（T5）：candidate_skill 归一表 SQL 查询 (candidate_id, skill_norm) 对 →
    # Python 重建 per-doc 命中向量（保留"有序技能优先"排序语义）；表为空时回退 Candidate.skills JSON 路径（迁移期兼容）
    structured_vec = {}    # document_id -> hit_vec（结构化命中）
    norm_skills = [normalize_skill(skill) for skill in skills]
    skill_rows = list(
        QuerySet(CandidateSkill)
        .filter(candidate__workspace_id=workspace_id, candidate__status=CandidateStatus.ACTIVE)
        .values_list("candidate_id", "skill_norm")
    )
    hit_candidate_ids = []
    if skill_rows:
        norm_by_candidate = {}
        for candidate_id, skill_norm in skill_rows:
            norm_by_candidate.setdefault(str(candidate_id), set()).add(skill_norm)
        for candidate_id, norms in norm_by_candidate.items():
            vec = [1 if ns in norms else 0 for ns in norm_skills]
            if any(vec):
                hit_candidate_ids.append((candidate_id, vec))
    else:
        candidates = list(QuerySet(Candidate).filter(workspace_id=workspace_id, status=CandidateStatus.ACTIVE))
        for candidate in candidates:
            candidate_skills = {normalize_skill(s) for s in (candidate.skills or [])}
            if not candidate_skills:
                continue
            vec = [1 if ns in candidate_skills else 0 for ns in norm_skills]
            if any(vec):
                hit_candidate_ids.append((candidate.id, vec))
    if hit_candidate_ids:
        resumes_qs = QuerySet(ResumeFile).filter(
            candidate_id__in=[candidate_id for candidate_id, _ in hit_candidate_ids], document_id__isnull=False)
        if document_ids:
            # F1：结构化路与预筛文档集求交（年限/学历/城市硬条件对结构化命中同样生效）
            resumes_qs = resumes_qs.filter(document_id__in=document_ids)
        resumes = list(resumes_qs)
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


def _scope_document_ids(workspace_id, candidate_id, document_ids):
    """解析可选范围限定：document_ids 必须属于当前工作区，且若同时指定 candidate_id 必须属于该候选人。"""
    if document_ids is not None:
        if not isinstance(document_ids, list) or not document_ids or any(
            not isinstance(doc_id, str) or not doc_id.strip() for doc_id in document_ids
        ):
            raise AppApiException(400, "document_ids must be a non-empty list of strings")
        document_ids = [doc_id.strip() for doc_id in document_ids]
        valid = {
            str(doc_id) for doc_id in QuerySet(ResumeFile)
            .filter(workspace_id=workspace_id, document_id__in=document_ids, document_id__isnull=False)
            .values_list("document_id", flat=True)
        }
        missing = set(document_ids) - valid
        if missing:
            raise AppApiException(400, f"document_ids contain invalid or inaccessible documents: {sorted(missing)[:5]}")
        if candidate_id not in (None, ""):
            candidate = QuerySet(Candidate).filter(id=candidate_id, workspace_id=workspace_id).first()
            if candidate is None:
                raise AppApiException(404, "Candidate not found")
            allowed = {
                str(doc_id) for doc_id in QuerySet(ResumeFile)
                .filter(candidate=candidate, document_id__isnull=False)
                .values_list("document_id", flat=True)
            }
            cross = set(document_ids) - allowed
            if cross:
                raise AppApiException(400, f"document_ids do not belong to the candidate: {sorted(cross)[:5]}")
        return sorted(valid)
    if candidate_id is None or candidate_id == "":
        return None
    candidate = QuerySet(Candidate).filter(id=candidate_id, workspace_id=workspace_id).first()
    if candidate is None:
        raise AppApiException(404, "Candidate not found")
    return [
        str(doc_id) for doc_id in QuerySet(ResumeFile)
        .filter(candidate=candidate, document_id__isnull=False)
        .values_list("document_id", flat=True)
    ]


def search_resumes(workspace_id, query, top_k=5, recall_k=None, similarity=0.2,
                   mode="auto", hr_role=None, user_id=None, llm_model=None, rerank_model=None,
                   candidate_id=None, document_ids=None):
    """
    简历语义检索入口。返回 {"items": [...], "meta": {...}}。
    模式 A（整句）/ 模式 B（技能复合，auto 自动判定）。
    降级链：rerank → RRF → dense 单路 → 空结果。
    可选范围限定（不改召回/精排/降级链，仅限定召回 Document 集合）：
      document_ids：直接限定召回文档集；
      candidate_id：先查该候选人全部 ResumeFile.document_id 作为限定。
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

    # 可选范围限定（§八）：document_ids 优先；candidate_id 解析其简历文档集
    scope_document_ids = _scope_document_ids(workspace_id, candidate_id, document_ids)

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

    # ---------- 查询理解 v1（T4）：规则槽位（年限/学历/城市 + 语义词） ----------
    city_list = list(
        QuerySet(Candidate)
        .filter(workspace_id=workspace_id, status=CandidateStatus.ACTIVE)
        .exclude(current_city="")
        .values_list("current_city", flat=True)
        .distinct()
    )
    slots = extract_slots(query, city_list=city_list)
    meta["slots"] = {"years_min": slots["years_min"], "degree_level": slots["degree_level"],
                     "cities": slots["cities"]}
    meta["prefilter"] = {"applied": False, "candidate_count": 0, "resume_count": 0,
                         "skipped": False, "empty": False}
    prefilter_ids = None
    prefilter_skipped = False

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

    # ---------- 结构化预筛（T4/T7，整句/混合/Skills 模式；G1：精确条件由 SQL 保证） ----------
    # 技能维度仅整句/混合模式接入（T7：LLM 已解析出技能且 <2 时 AND 上 candidate_skill EXISTS）；
    # skills 模式的技能命中由模式 B 自身（结构化路 + 语义路 OR 合并）负责，预筛只保年限/学历/城市——
    # 避免与 candidate_skill EXISTS 双重收窄、回填稀疏期误杀（审查修复 F1，owner 决策：不含技能维度）。
    # 显式 dense 模式不接预筛（消融纯净性，评测口径依赖该契约）。
    skill_norms = [normalize_skill(s) for s in skills]
    hard = (
        slots["years_min"] is not None
        or slots["degree_level"] is not None
        or bool(slots["cities"])
        or bool(skill_norms)
    )
    # skills 模式门控只认硬条件槽位（年限/学历/城市）：技能词恒非空会使 hard 恒真，
    # 空条件时不应触发全量预筛（避免大库全量 IN 子句与误导性 applied 标记，复审 P3-1）
    hard_slots = slots["years_min"] is not None or slots["degree_level"] is not None or bool(slots["cities"])
    if (mode in ("phrase", "hybrid") and hard) or (mode == "skills" and hard_slots):
        q = Q()
        if slots["years_min"] is not None:
            # 年限未知（NULL）纳入但排序靠后（years_unknown 标记），不静默消失（R2）
            q &= Q(years_experience__gte=slots["years_min"]) | Q(years_experience__isnull=True)
        if slots["degree_level"] is not None:
            q &= Q(highest_degree__in=degree_words(slots["degree_level"]))
        for city in slots["cities"]:
            q &= Q(current_city=city) | Q(current_city=norm_city(city)) | Q(current_city=norm_city(city) + "市")
        if mode in ("phrase", "hybrid") and skill_norms and QuerySet(CandidateSkill).filter(
            candidate__workspace_id=workspace_id, candidate__status=CandidateStatus.ACTIVE
        ).exists():
            # 表空（未回填/语料无技能）时跳过技能维度，避免 EXISTS 空表误杀整条查询（迁移期兼容）
            q &= Q(skill_rows__skill_norm__in=skill_norms)
        candidate_ids = list(
            QuerySet(Candidate)
            .filter(workspace_id=workspace_id, status=CandidateStatus.ACTIVE)
            .filter(q)
            .values_list("id", flat=True)
            .distinct()  # F4：技能维度联表 __in 可能产生重复行（防御性，当前路径最多 1 个技能词）
        )
        meta["prefilter"]["candidate_count"] = len(candidate_ids)
        doc_ids = []
        if candidate_ids:
            doc_ids = list(
                QuerySet(ResumeFile)
                .filter(candidate_id__in=candidate_ids, document_id__isnull=False)
                .values_list("document_id", flat=True)
            )
        meta["prefilter"]["resume_count"] = len(doc_ids)
        if not doc_ids:
            # 无满足条件的候选人：明确返回空，不做语义兜底误导（设计 §3.5）
            meta["prefilter"]["empty"] = True
            meta["search_type"] = "prefilter_empty"
            meta["elapsed_ms"]["total"] = int((time.time() - t0) * 1000)
            _write_search_audit(workspace_id, user_id, query, top_k, meta, 0)
            return {"items": [], "meta": meta}
        if len(doc_ids) > _PREFILTER_MAX:
            # 超阈值跳过 IN 限定：语义路径靠检索后硬条件过滤保证精确率；
            # 纯条件查询（无语义词）不调 embed，直接按已算出的 candidate_ids 走结构化 top_k。
            meta["prefilter"]["skipped"] = True
            prefilter_skipped = True
            if not slots["semantic_query"]:
                structured_resumes = list(
                    QuerySet(ResumeFile)
                    .filter(candidate_id__in=candidate_ids, document_id__isnull=False)
                    .select_related("candidate")
                    .order_by(F("candidate__years_experience").desc(nulls_last=True), "-update_time")
                )
                items = []
                seen = set()
                for rf in structured_resumes:
                    if str(rf.document_id) in seen:
                        continue
                    seen.add(str(rf.document_id))
                    items.append({
                        "rank": len(items) + 1,
                        "candidate": _mask_for_role(rf.candidate, hr_role),
                        "resume": {"id": str(rf.id), "file_name": rf.file_name, "extension": rf.extension},
                        "score": {"structured": True},
                        "paragraphs": [],
                        "document_id": str(rf.document_id),
                    })
                    if len(items) >= top_k:
                        break
                meta["search_type"] = "structured_only"
                meta["name_matched"] = 0
                meta["aggregation"] = {"grouped_resumes": len(items)}
                meta["elapsed_ms"]["total"] = int((time.time() - t0) * 1000)
                _write_search_audit(workspace_id, user_id, query, top_k, meta, len(items))
                return {"items": items, "meta": meta}
        else:
            meta["prefilter"]["applied"] = True
            prefilter_ids = doc_ids

    # 范围限定与结构化预筛取交集；仅传 scope 时直接作为限定集
    if scope_document_ids is not None:
        if prefilter_ids is None:
            prefilter_ids = scope_document_ids
        else:
            scope_set = set(scope_document_ids)
            prefilter_ids = [doc_id for doc_id in prefilter_ids if doc_id in scope_set]
        meta["scope"] = {"applied": True, "document_count": len(scope_document_ids),
                         "restricted_count": len(prefilter_ids)}

    # ---------- 模式 B：Skill-AND ----------
    if mode == "skills" and len(skills) >= 2:
        ordered, b_meta = _search_skill_and(
            skills, workspace_id, knowledge, embedding_model, recall_k, similarity, top_k,
            document_ids=prefilter_ids,
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
        if prefilter_skipped and hard_slots:
            # 超阈值跳过 IN 限定：候选文档先按硬条件过滤，避免返回不满足年限/学历/城市的弱命中
            cand_resumes = {
                str(rf.document_id): rf
                for rf in QuerySet(ResumeFile).filter(document_id__in=cand_docs).select_related("candidate")
            }
            cand_docs = [
                doc_id for doc_id in cand_docs
                if doc_id in cand_resumes and cand_resumes[doc_id].candidate is not None
                and _candidate_matches_hard_slots(cand_resumes[doc_id].candidate, slots)
            ]
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
                resume = QuerySet(ResumeFile).filter(document_id=doc_id).select_related("candidate").first()
                if prefilter_skipped and hard_slots:
                    if resume is None or resume.candidate is None or not _candidate_matches_hard_slots(resume.candidate, slots):
                        continue
                seen_docs.add(doc_id)
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

    # ---------- 模式 A：整句（T4：结构化预筛限定召回集） ----------
    use_sparse = mode in ("auto", "hybrid", "phrase")
    # 姓名快速通道（T4）：纯 2-4 字中文查询并跑 name__icontains，结果置顶
    name_hits = []
    if _NAME_RE.match(query):
        name_candidates = list(
            QuerySet(Candidate)
            .filter(workspace_id=workspace_id, status=CandidateStatus.ACTIVE, name__icontains=query)
            .select_related()
        )
        if name_candidates:
            name_qs = QuerySet(ResumeFile).filter(candidate__in=name_candidates, document_id__isnull=False)
            if scope_document_ids is not None:
                name_qs = name_qs.filter(document_id__in=scope_document_ids)
            name_resumes = list(name_qs.select_related("candidate"))
            for rf in name_resumes:
                name_hits.append({
                    "candidate": _mask_for_role(rf.candidate, hr_role),
                    "resume": {"id": str(rf.id), "file_name": rf.file_name, "extension": rf.extension},
                    "score": {"name_match": True},
                    "paragraphs": [],
                    "document_id": str(rf.document_id),
                })
    if prefilter_ids is not None and not slots["semantic_query"]:
        # 纯条件查询（无语义词）：跳过语义召回，纯结构化检索（R2；杜绝 embed_query("")）
        structured_resumes = list(
            QuerySet(ResumeFile)
            .filter(document_id__in=prefilter_ids)
            .select_related("candidate")
            .order_by(F("candidate__years_experience").desc(nulls_last=True), "-update_time")
        )
        items = []
        seen = set()
        for rf in structured_resumes:
            if str(rf.document_id) in seen:
                continue
            seen.add(str(rf.document_id))
            items.append({
                "rank": len(items) + 1,
                "candidate": _mask_for_role(rf.candidate, hr_role),
                "resume": {"id": str(rf.id), "file_name": rf.file_name, "extension": rf.extension},
                "score": {"structured": True},
                "paragraphs": [],
                "document_id": str(rf.document_id),
            })
            if len(items) >= top_k:
                break
        items = name_hits + items[: max(0, top_k - len(name_hits))]
        for i, item in enumerate(items, 1):
            item["rank"] = i  # F5：姓名置顶后统一重排 rank
        meta["search_type"] = "structured_only"
        meta["name_matched"] = len(name_hits)
        meta["aggregation"] = {"grouped_resumes": len(items)}
        meta["elapsed_ms"]["total"] = int((time.time() - t0) * 1000)
        _write_search_audit(workspace_id, user_id, query, top_k, meta, len(items))
        return {"items": items, "meta": meta}
    recall = _recall_dual(slots["semantic_query"] or query, knowledge, embedding_model, recall_k, similarity,
                          use_sparse=use_sparse, document_ids=prefilter_ids)
    fused = _rrf_fuse(recall["dense"], recall["sparse"])
    meta["recall"] = {"dense": len(recall["dense"]), "sparse": len(recall["sparse"]), "fused": len(fused),
                      "candidate_k": recall_k, "sparse_failed": recall.get("sparse_failed", False)}
    if not fused:
        if name_hits:
            # 语义空但姓名命中（T4）：按姓名返回，避免"搜不到人"
            items = [dict(h, rank=i + 1) for i, h in enumerate(name_hits[:top_k])]
            meta["search_type"] = "name_match"
            meta["name_matched"] = len(items)
            meta["elapsed_ms"]["total"] = int((time.time() - t0) * 1000)
            _write_search_audit(workspace_id, user_id, query, top_k, meta, len(items))
            return {"items": items, "meta": meta}
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
    if prefilter_skipped and hard_slots:
        # 超阈值跳过 IN 限定：聚合后仍按硬条件过滤，保证 conditional 精确率。
        # aggregated 中的 candidate 是脱敏 dict（无 current_city），需回表取 ORM Candidate 判断。
        agg_doc_ids = [a["document_id"] for a in aggregated if a.get("document_id")]
        agg_resumes = {
            str(rf.document_id): rf
            for rf in QuerySet(ResumeFile).filter(document_id__in=agg_doc_ids).select_related("candidate")
        }
        aggregated = [
            a for a in aggregated
            if a.get("document_id") in agg_resumes
            and agg_resumes[a["document_id"]].candidate is not None
            and _candidate_matches_hard_slots(agg_resumes[a["document_id"]].candidate, slots)
        ]
    orphan_count = sum(1 for p in fused if not p.get("document_id"))
    meta["aggregation"] = {
        "grouped_resumes": len(aggregated),
        "dropped_orphan_paragraphs": orphan_count,
        "evidence_lambda": _EVIDENCE_LAMBDA,
        "base_formula": "0.7max+0.3avg",
        "multi_hit_boosted": sum(1 for a in aggregated if len(a["paragraphs"]) > 1),
    }

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
    if name_hits:
        # 姓名命中置顶（去重：已出现的候选人不再重复）
        seen_candidates = {item["candidate"]["id"] for item in items if item["candidate"]}
        prepend = [h for h in name_hits if h["candidate"] and h["candidate"]["id"] not in seen_candidates]
        items = prepend + items[: max(0, top_k - len(prepend))]
        for i, item in enumerate(items, 1):
            item["rank"] = i  # F5：姓名置顶后统一重排 rank
        meta["name_matched"] = len(prepend)
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
