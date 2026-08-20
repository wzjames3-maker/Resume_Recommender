# coding=utf-8
"""
    @project: MaxKB
    @file： context.py
    @date：2026/8/17
    @desc: Agent LLM 上下文投影（PRD-AGENT-RAG §4.2/§9）：
           进入模型前的工具返回值统一脱敏——剔除 phone/email/note/文件路径/简历原文，
           证据只保留已脱敏 chunk。只改工具适配器，不改 RAG 链路。
"""

_MAX_EXCERPT_LENGTH = 500
_SEARCH_EVIDENCE_LIMIT = 12


def _mask_phone(value):
    if not value:
        return ""
    return value[:3] + "****" + value[-4:] if len(value) >= 7 else "****"


def _mask_email(value):
    if not value or "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    masked_local = local[:2] + "***" if len(local) > 2 else "***"
    return f"{masked_local}@{domain}"


def job_to_llm(job):
    """职位信息投影：纯职位事实，无候选人数据。"""
    return {
        "id": str(job.id),
        "name": job.name,
        "department": job.department,
        "city": job.city,
        "level": job.level,
        "description": job.description,
        "skill_requirements": job.skill_requirements,
    }


def candidate_to_llm(candidate):
    """候选人投影（0030 后仅 id/姓名/状态；城市/学历/年限/技能已移除，联系方式永不进 LLM）。"""
    if candidate is None:
        return None
    return {
        "id": str(candidate.id),
        "name": candidate.name,
        "status": candidate.status,
    }


def structured_filter_to_llm(result):
    """结构化核对结果投影：条件明细 + hard_met。"""
    conditions = []
    for condition in result.get("conditions", []):
        conditions.append({
            "requirement": condition.get("requirement", ""),
            "field": condition.get("field", ""),
            "met": bool(condition.get("met")),
            "detail": condition.get("detail", ""),
        })
    return {"conditions": conditions, "hard_met": bool(result.get("hard_met"))}


def search_to_llm(search_result):
    """检索结果投影：候选人仅脱敏最小字段；resume 只留 id；证据只保留脱敏 chunk（截断长度）。"""
    items = []
    for item in (search_result or {}).get("items", [])[:_SEARCH_EVIDENCE_LIMIT]:
        candidate = item.get("candidate") or {}
        resume = item.get("resume") or {}
        paragraphs = []
        for paragraph in (item.get("paragraphs") or [])[:3]:
            content = paragraph.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            paragraphs.append({
                "paragraph_id": paragraph.get("id") or paragraph.get("paragraph_id"),
                "title": paragraph.get("title", ""),
                "content": content[:_MAX_EXCERPT_LENGTH],
                "score": paragraph.get("score"),
            })
        items.append({
            "candidate": {
                "id": candidate.get("id"),
                "name": candidate.get("name"),
                "status": candidate.get("status"),
                "phone": _mask_phone(candidate.get("phone")),
                "email": _mask_email(candidate.get("email")),
            },
            "resume": {"id": resume.get("id")},
            "paragraphs": paragraphs,
            "document_id": item.get("document_id"),
            "score": item.get("score"),
        })
    meta = (search_result or {}).get("meta") or {}
    return {
        "items": items,
        "meta": {
            "mode": meta.get("mode"),
            "search_type": meta.get("search_type"),
            "grouped_resumes": (meta.get("aggregation") or {}).get("grouped_resumes"),
        },
    }


def _mask_pii(text):
    """投影层防御性掩码：即使上游漏过，联系方式也不得进入 LLM 上下文。"""
    import re

    if not text:
        return text
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", lambda m: m.group(0)[:3] + "****" + m.group(0)[-4:], text)
    text = re.sub(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        lambda m: m.group(0)[:2] + "***@" + m.group(0).split("@")[1],
        text,
    )
    return text


def knowledge_to_llm(search_result, maximum=_SEARCH_EVIDENCE_LIMIT):
    """企业知识库检索投影：仅保留文档/段落标题与脱敏摘要，出入库路径一律剔除。"""
    items = []
    for item in (search_result or {}).get("items", [])[:maximum]:
        items.append({
            "paragraph_id": item.get("paragraph_id"),
            "knowledge_id": item.get("knowledge_id"),
            "knowledge_name": item.get("knowledge_name"),
            "document_id": item.get("document_id"),
            "document_name": item.get("document_name"),
            "title": item.get("title", ""),
            "content": _mask_pii(str(item.get("content", ""))[:_MAX_EXCERPT_LENGTH]),
            "score": item.get("score"),
        })
    return {"items": items, "meta": (search_result or {}).get("meta") or {}}


def similar_jobs_to_llm(rows):
    """相似职位投影：不含候选人数据；录用画像仅聚合统计。"""
    output = []
    for job in (rows or [])[:5]:
        output.append({
            "job_id": job.get("job_id"),
            "name": job.get("name"),
            "department": job.get("department"),
            "city": job.get("city"),
            "level": job.get("level"),
            "skill_overlap": job.get("skill_overlap", []),
            "similarity": job.get("similarity"),
            "hired_count": job.get("hired_count"),
            "hired_avg_years": job.get("hired_avg_years"),
        })
    return output


def sanitize_for_trace(value, maximum=200):
    """工具轨迹脱敏：仅保留简短摘要（不记录联系方式/简历原文）。"""
    if isinstance(value, dict):
        return {k: sanitize_for_trace(v, maximum) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_trace(v, maximum) for v in value[:5]]
    if not isinstance(value, str):
        return value
    return value[:maximum]
