# coding=utf-8
"""
    @project: MaxKB
    @file： resume_index.py
    @date：2026/8/15
    @desc：简历语义索引服务：简历知识库管理 + 简历入库（清洗→切片→文档→向量化）+ 生命周期同步。
          设计见 docs/superpowers/specs/2026-08-15-end-to-end-pipeline-combined-design.md；
          链路见 docs/superpowers/specs/2026-08-15-resume-upload-split-embed-flow.md §8。
"""
from django.db.models import QuerySet

from common.exception.app_exception import AppApiException
from knowledge.models import Document, Embedding, Knowledge, KnowledgeFolder, KnowledgeScope, KnowledgeType
from knowledge.serializers.document import DocumentSerializers
from knowledge.serializers.knowledge import KnowledgeSerializer
from knowledge.task.embedding import delete_embedding_by_document
from models_provider.models import Model

from hr.services.flow_log import log_flow
from hr.services.resume_splitter import split_resume_text

_KNOWLEDGE_NAME = "简历语义索引"
_DEFAULT_FOLDER_ID = "default"


def get_resume_knowledge(workspace_id):
    """按工作区查找简历语义知识库。"""
    return QuerySet(Knowledge).filter(workspace_id=workspace_id, name=_KNOWLEDGE_NAME).first()


def get_or_create_resume_knowledge(workspace_id, user_id):
    """
    获取或创建工作区的简历语义知识库（幂等）。
    embedding 模型取第一个已注册的 EMBEDDING 类型模型；folder 复用 default（非 EE 单租户内核）。
    """
    knowledge = get_resume_knowledge(workspace_id)
    if knowledge is not None:
        return knowledge
    embedding_model = QuerySet(Model).filter(model_type="EMBEDDING").first()
    if embedding_model is None:
        raise AppApiException(500, "未配置 Embedding 模型，无法建立简历语义索引")
    KnowledgeFolder.objects.get_or_create(
        id=_DEFAULT_FOLDER_ID, defaults={"name": _DEFAULT_FOLDER_ID, "workspace_id": "default"}
    )
    serializer = KnowledgeSerializer.Create(data={"user_id": str(user_id), "workspace_id": workspace_id})
    serializer.save_base(
        {
            "name": _KNOWLEDGE_NAME,
            "desc": "HR 简历语义索引（自动维护，勿手动编辑）",
            "folder_id": _DEFAULT_FOLDER_ID,
            "embedding_model_id": str(embedding_model.id),
            "type": KnowledgeType.BASE.value,
            "scope": KnowledgeScope.WORKSPACE.value,
        },
        with_valid=True,
    )
    return get_resume_knowledge(workspace_id)


def index_resume(workspace_id, user_id, resume, text, chat_fn, stats=None):
    """
    简历入库：清洗已在 split_resume_text 内完成 → 切片 → 建 Document/Paragraph → 触发向量化。
    :param stats: 可选 dict，透传 split_resume_text 的 path/llm_calls（供流转日志）
    :return: document_id
    :raises: 切片失败（ValueError）/ 知识库或模型缺失（AppApiException）
    """
    knowledge = get_or_create_resume_knowledge(workspace_id, user_id)
    chunks = split_resume_text(text, chat_fn, stats=stats)
    log_flow(
        workspace_id, "SPLIT", resume_id=resume.id,
        detail={
            "path": (stats or {}).get("path", "?"),
            "llm_calls": (stats or {}).get("llm_calls", 0),
            "chunks": len(chunks),
            "lengths": [len(chunk["content"]) for chunk in chunks],
            "pii_masked": sum(1 for chunk in chunks if "[已脱敏]" in chunk["content"]),
        },
    )
    if resume.document_id:
        _delete_document(str(resume.document_id))
    serializer = DocumentSerializers.Create(data={"knowledge_id": str(knowledge.id), "user_id": str(user_id)})
    saved = serializer.save(
        {
            "name": resume.file_name,
            "paragraphs": [{"title": chunk["title"], "content": chunk["content"]} for chunk in chunks],
        },
        with_valid=True,
    )
    # save 经 @post 装饰器返回文档详情 dict（内部已触发 refresh → embedding_by_document.delay）
    document_id = saved.get("id") if isinstance(saved, dict) else str(saved)
    resume.document_id = document_id
    resume.save(update_fields=["document_id", "update_time"])
    return str(document_id)


def _delete_document(document_id):
    """删除文档及其向量（幂等）。"""
    delete_embedding_by_document(document_id)
    QuerySet(Document).filter(id=document_id).delete()


def delete_resume_index(resume):
    """候选人删除/合并清理时删除简历文档与向量（幂等）。"""
    if not resume.document_id:
        return
    _delete_document(str(resume.document_id))
    resume.document_id = None
    resume.save(update_fields=["document_id", "update_time"])


def set_resume_index_active(resume, is_active):
    """归档/恢复：同步 Document 与 Embedding 的 is_active（检索自动排除）。"""
    if not resume.document_id:
        return
    QuerySet(Document).filter(id=str(resume.document_id)).update(is_active=is_active)
    QuerySet(Embedding).filter(document_id=str(resume.document_id)).update(is_active=is_active)
