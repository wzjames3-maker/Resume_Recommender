# coding=utf-8
"""
    @project: MaxKB
    @file： resume_index.py
    @date：2026/8/15
    @desc：简历语义索引服务：简历知识库管理 + 简历入库（清洗→切片→文档→向量化）+ 生命周期同步。
          设计见 docs/RAG-V2-DESIGN.md；

"""
import uuid_utils.compat as uuid
from celery_once import AlreadyQueued
from django.db import transaction
from django.db.models import QuerySet

from common.chunk import text_to_chunk
from common.exception.app_exception import AppApiException
from knowledge.models import Document, Embedding, Knowledge, KnowledgeFolder, KnowledgeScope, KnowledgeType, Paragraph
from knowledge.serializers.knowledge import KnowledgeSerializer
from knowledge.task.embedding import delete_embedding_by_document, embedding_by_document
from models_provider.models import Model

from hr.services.flow_log import log_flow
from hr.services.resume_splitter import scan_residual_pii, split_resume_text

_KNOWLEDGE_NAME = "简历语义索引"
_DEFAULT_FOLDER_ID = "default"


class ResidualPIIError(ValueError):
    """残留 PII 拒绝入库（设计 §6.8）。专用异常供 task 层识别：index_resume 已在
    抛错前记录 SPLIT FAILED 详情日志，task 层不再重复写（避免双日志，P2 修复）。"""


def get_resume_knowledge(workspace_id):
    """按工作区查找简历语义知识库（自动补保护标记，PRD-AGENT-RAG §7：受人事模块管理的受保护索引）。"""
    knowledge = QuerySet(Knowledge).filter(workspace_id=workspace_id, name=_KNOWLEDGE_NAME).first()
    if knowledge is not None and not (knowledge.meta or {}).get("hr_protected"):
        knowledge.meta = {**(knowledge.meta or {}), "hr_protected": True}
        knowledge.save(update_fields=["meta", "update_time"])
    return knowledge


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
            "meta": {"hr_protected": True},
        },
        with_valid=True,
    )
    return get_resume_knowledge(workspace_id)


def index_resume(workspace_id, user_id, resume, text, chat_fn, stats=None, chunks=None):
    """
    简历入库：清洗已在 split_resume_text 内完成 → 切片 → 建 Document/Paragraph → 触发向量化。
    :param stats: 可选 dict，透传 split_resume_text 的 path/llm_calls（供流转日志）
    :param chunks: 可选预切片（结构化语料免 LLM 切片，如数据集导入）；缺省走 split_resume_text
    :return: document_id
    :raises: 切片失败（ValueError）/ 知识库或模型缺失（AppApiException）
    """
    knowledge = get_or_create_resume_knowledge(workspace_id, user_id)
    if chunks is None:
        chunks = split_resume_text(text, chat_fn, stats=stats)
    # 入库前二次扫描（设计 §6.8）：掩码未覆盖的 PII 变体 → 拒绝入库（不阻塞候选人建档，错误经任务记入 error_message）
    # 注意：先扫描后写 SPLIT 日志，避免被拒绝的残留 PII 进入流转日志。
    for chunk in chunks:
        if scan_residual_pii(chunk["content"]):
            log_flow(
                workspace_id, "SPLIT", status="FAILED", resume_id=resume.id,
                detail={
                    "path": (stats or {}).get("path", "?"),
                    "llm_calls": (stats or {}).get("llm_calls", 0),
                    "chunks_count": len(chunks),
                    "error_message": f"切片内容仍包含未掩码的 PII（{chunk['title']}），拒绝入库",
                },
                error_message=f"切片内容仍包含未掩码的 PII（{chunk['title']}），拒绝入库",
            )
            raise ResidualPIIError(f"切片内容仍包含未掩码的 PII（{chunk['title']}），拒绝入库")
    log_flow(
        workspace_id, "SPLIT", resume_id=resume.id,
        detail={
            "path": (stats or {}).get("path", "?"),
            "llm_calls": (stats or {}).get("llm_calls", 0),
            "chunks_count": len(chunks),
            "chunks": [
                {
                    "title": chunk["title"],
                    "length": len(chunk["content"]),
                    "pii_masked": "[已脱敏]" in chunk["content"],
                    "content": chunk["content"],
                }
                for chunk in chunks
            ],
        },
    )
    if resume.document_id:
        _delete_document(str(resume.document_id))
    # T2：HR 自建 Document/Paragraph（chunks 携带 "{title}\n" 前缀参与向量化/分词，
    # content 保持原文——保真/展示/证据回溯不受影响）。默认 status 即 PENDING，
    # embedding 任务 state_list 含 PENDING，delay 后可直接拾取，无需复刻 refresh() 状态置位。
    document_id = _create_document_with_chunks(knowledge, user_id, resume.file_name, chunks)
    resume.document_id = document_id
    resume.save(update_fields=["document_id", "update_time"])
    try:
        embedding_by_document.delay(document_id, str(knowledge.embedding_model_id))
    except AlreadyQueued:
        raise AppApiException(500, "向量化任务已在执行中，请勿重复提交")
    return str(document_id)


def _create_document_with_chunks(knowledge, user_id, file_name, chunks):
    """自建 Document/Paragraph（原子）：chunks = ["{title}\n{chunk}" ...]（title 入向量）；
    content 字段保持原文。字段构造对照 kernel paragraph.py:419-426 与 document.py:1085-1097。"""
    document_id = uuid.uuid7()
    contents = [chunk["content"] for chunk in chunks]
    with transaction.atomic():
        document = Document(
            id=document_id,
            knowledge_id=knowledge.id,
            name=file_name,
            char_length=sum(len(c) for c in contents),
            meta={"allow_download": True},
            type=KnowledgeType.BASE.value,
            user_id=user_id,
        )
        document.save()
        paragraph_list = [
            Paragraph(
                id=uuid.uuid7(),
                document_id=document_id,
                knowledge_id=knowledge.id,
                content=chunk["content"],
                title=chunk["title"],
                chunks=[
                    f"{chunk['title']}\n{c}" if chunk["title"] else c
                    for c in text_to_chunk(chunk["content"])
                ],
                position=index + 1,
            )
            for index, chunk in enumerate(chunks)
        ]
        if paragraph_list:
            QuerySet(Paragraph).bulk_create(paragraph_list)
    return str(document_id)


def _delete_document(document_id):
    """删除文档及其向量与段落（幂等）。
    Paragraph.document 为 on_delete=DO_NOTHING 且无 DB 级联约束（内核模型），必须显式删除段落，
    否则简历删除/替换后段落残留、仍可被检索（审查 P1 修复）。"""
    QuerySet(Paragraph).filter(document_id=document_id).delete()
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


def delete_resume_knowledge(workspace_id):
    """工作区注销：清空该工作区「简历语义索引」知识库的全部文档/段落/向量，并删知识库本身（幂等）。

    复用 _delete_document（显式删段落后删向量再删文档，覆盖内核模型无 DB 级联的情况），
    不依赖 ResumeFile.document_id，可一并收掉未挂接简历的孤儿文档。"""
    knowledge = get_resume_knowledge(workspace_id)
    if knowledge is None:
        return
    for document_id in QuerySet(Document).filter(knowledge_id=knowledge.id).values_list("id", flat=True):
        _delete_document(str(document_id))
    QuerySet(Knowledge).filter(id=knowledge.id).delete()
