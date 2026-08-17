# coding=utf-8
"""
    @project: MaxKB
    @file： knowledge_search.py
    @date：2026/8/17
    @desc: 企业知识库检索工具（PRD-AGENT-RAG §4.2 search_knowledge）：
           仅 HrConfig.agent_knowledge_bases 白名单内的知识库可检索；
           双路召回（dense + keywords，沿用 pgvector 既有实现）→ Python RRF 融合 → 可选 rerank。
           结果经 PII 掩码与截断后才进入 LLM 上下文；不改 RAG 链路。
"""
from django.db.models import QuerySet
from knowledge.models import Document, Embedding, Knowledge, Paragraph, SearchMode
from knowledge.serializers.common import get_embedding_model_by_knowledge_id
from knowledge.vector.pg_vector import EmbeddingSearch, KeywordsSearch

from common.exception.app_exception import AppApiException
from hr.models import HrConfig
from hr.services.resume_search import _rrf_fuse, _sparse_query

import re

_MAX_CONTENT_LENGTH = 500
_DEFAULT_SIMILARITY = 0.3

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _mask_pii(text):
    """检索摘录 PII 掩码（企业知识库不应含候选人数据，防御性脱敏）。"""
    if not text:
        return text

    def mask_phone(match):
        value = match.group(0)
        return value[:3] + "****" + value[-4:]

    def mask_email(match):
        value = match.group(0)
        local, _, domain = value.partition("@")
        return (local[:2] + "***" if len(local) > 2 else "***") + "@" + domain

    text = _PHONE_RE.sub(mask_phone, text)
    text = _EMAIL_RE.sub(mask_email, text)
    return text


def _whitelist(workspace_id):
    config = HrConfig.objects.filter(workspace_id=workspace_id).first()
    if config is None:
        return []
    return [str(kb_id) for kb_id in (config.agent_knowledge_bases or [])]


def _allowed_knowledge_bases(workspace_id, kb_ids):
    """白名单强制：请求的 kb_ids 必须是 HrConfig 白名单子集；未传默认全量白名单。
    受保护简历语义索引（meta.hr_protected）与企业知识库目录隔离，不可作为检索源。"""
    whitelist = _whitelist(workspace_id)
    requested = []
    for kb_id in (kb_ids or []):
        kb_id = str(kb_id)
        if kb_id not in whitelist:
            raise AppApiException(400, f"知识库 {kb_id} 不在 Agent 白名单中")
        requested.append(kb_id)
    if not requested:
        requested = whitelist
    if not requested:
        return []
    return list(
        QuerySet(Knowledge)
        .filter(workspace_id=workspace_id, id__in=requested, meta__hr_protected__isnull=True)
        .order_by("create_time")
    )


def _search_one_knowledge(knowledge, query, top_n, similarity):
    """单个知识库双路召回 + RRF 融合。失败返回空（该库跳过，不影响其它库）。"""
    try:
        embedding_model = get_embedding_model_by_knowledge_id(str(knowledge.id))
        query_embedding = embedding_model.embed_query(query)
    except AppApiException:
        raise
    except Exception:
        raise AppApiException(500, "Embedding 调用失败，请稍后重试或检查模型配置")
    exclude_ids = [
        str(document.id)
        for document in QuerySet(Document).filter(knowledge_id=knowledge.id, is_active=False)
    ]
    exclude_dict = {"document_id__in": exclude_ids} if exclude_ids else {}
    query_set = (
        QuerySet(Embedding).filter(knowledge_id=knowledge.id, is_active=True).exclude(**exclude_dict)
    )
    dense = EmbeddingSearch().handle(
        query_set, query, query_embedding, top_n, similarity, SearchMode.embedding, [str(knowledge.id)]
    )
    sparse = []
    sparse_query = _sparse_query(query)
    if sparse_query:
        try:
            sparse = KeywordsSearch().handle(
                query_set, sparse_query, query_embedding, top_n, 0.01, SearchMode.keywords, [str(knowledge.id)]
            )
        except Exception:
            sparse = []
    return _rrf_fuse(dense, sparse)


def search_knowledge(workspace_id, query, kb_ids=None, top_k=5, similarity=_DEFAULT_SIMILARITY, rerank_model=None):
    """企业知识库检索（白名单 + 双路召回 RRF + 可选 rerank + PII 掩码）。

    返回 {"items": [...], "meta": {...}}；items 每项为
    {paragraph_id, knowledge_id, knowledge_name, document_id, document_name, title, content, score}。
    仅 HrConfig 白名单知识库可检索，其他一律 400；
    掩码后的摘录为可进 LLM 上下文的脱敏 chunk（§4.2）。
    """
    top_k = max(1, min(20, int(top_k)))
    similarity = max(0.0, min(2.0, float(similarity)))
    knowledge_list = _allowed_knowledge_bases(workspace_id, kb_ids)
    if not knowledge_list:
        return {"items": [], "meta": {"mode": "blend", "knowledge_count": 0, "total": 0}}

    pooled = []
    failed = 0
    for knowledge in knowledge_list:
        try:
            fused = _search_one_knowledge(knowledge, query, max(top_k * 2, 5), similarity)
        except AppApiException:
            failed += 1
            continue
        for row in fused:
            row["knowledge_id"] = str(knowledge.id)
            row["knowledge_name"] = knowledge.name
        pooled.extend(fused[:top_k])
    if failed == len(knowledge_list):
        raise AppApiException(500, "企业知识库检索失败：Embedding 模型不可用")
    pooled.sort(key=lambda row: row.get("rrf", 0), reverse=True)
    pooled = pooled[:top_k]

    paragraph_ids = [str(row["paragraph_id"]) for row in pooled]
    paragraph_map = {}
    if paragraph_ids:
        paragraph_map = {
            str(paragraph.id): paragraph
            for paragraph in QuerySet(Paragraph).filter(id__in=paragraph_ids)
        }
    document_ids = {
        str(paragraph.document_id) for paragraph in paragraph_map.values() if paragraph.document_id
    }
    document_map = {
        str(document.id): document
        for document in QuerySet(Document).filter(id__in=list(document_ids))
    }

    items = []
    for row in pooled:
        paragraph = paragraph_map.get(str(row["paragraph_id"]))
        if paragraph is None:
            continue
        document = document_map.get(str(paragraph.document_id)) if paragraph.document_id else None
        items.append({
            "paragraph_id": str(paragraph.id),
            "knowledge_id": row.get("knowledge_id"),
            "knowledge_name": row.get("knowledge_name", ""),
            "document_id": str(document.id) if document else None,
            "document_name": document.name if document else "",
            "title": paragraph.title or "",
            "content": _mask_pii((paragraph.content or "")[:_MAX_CONTENT_LENGTH]),
            "score": round(float(row.get("rrf", 0)), 4),
        })

    if rerank_model is not None and items:
        try:
            contents = [item["content"] for item in items]
            for hit in rerank_model.rerank(query, contents, top_n=top_k):
                index = hit.get("index")
                relevance = hit.get("relevance_score", 0)
                if index is not None and 0 <= index < len(items) and relevance:
                    items[index]["score"] = round(float(relevance), 4)
            items.sort(key=lambda item: item["score"], reverse=True)
        except Exception:
            # rerank 失败降级为 RRF 排序（与 resume_search 降级链一致）
            pass
    return {
        "items": items,
        "meta": {
            "mode": "blend",
            "knowledge_count": len(knowledge_list),
            "total": len(items),
            "reranked": rerank_model is not None,
        },
    }
