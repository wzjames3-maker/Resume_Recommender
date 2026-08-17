# coding=utf-8
"""
    @project: MaxKB
    @file： workspace_offboarding.py
    @date：2026/8/18
    @desc：精简内核 Workspace 注销编排：跨 application / knowledge / model / permission / chat 授权域，
           先生成数据返还包，再在一个数据库事务中清理核心域与 HR 域，提交后回收 HR 对象存储。
           当前仓库没有统一 Workspace ORM，本服务和 workspace_offboard 命令是明确的生命周期接入点。
"""
import os
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from application.models import (
    Application,
    ApplicationAccessToken,
    ApplicationApiKey,
    ApplicationChatUserStats,
    ApplicationFolder,
    ApplicationKnowledgeMapping,
    ApplicationLongTermMemory,
    ApplicationVersion,
    Chat,
    ChatRecord,
    ChatShareLink,
)
from common.exception.app_exception import AppApiException
from hr.services.offboarding import (
    export_workspace_data as hr_export_workspace_data,
    offboard_workspace as hr_offboard_workspace,
    preview_workspace_offboarding as hr_preview_workspace_offboarding,
)
from hr.services.storage import get_storage
from knowledge.models import (
    Document,
    DocumentTag,
    Embedding,
    File,
    FileSourceType,
    Knowledge,
    KnowledgeFolder,
    KnowledgeWorkflow,
    KnowledgeWorkflowVersion,
    Paragraph,
    Problem,
    ProblemParagraphMapping,
    Tag,
    Termbase,
)
from models_provider.models import Model
from system_manage.models.resource_mapping import ResourceMapping
from system_manage.models import (
    Log,
    ResourceChatUserAuthorize,
    ResourceChatUserGroupAuthorize,
    StorageCleanupStatus,
    WorkspaceOffboard,
    WorkspaceOffboardStorageCleanup,
    WorkspaceUserResourcePermission,
)

_RESERVED_WORKSPACE_IDS = {"", "default"}
_CORE_FILE_SOURCE_TYPES = {
    FileSourceType.KNOWLEDGE.value,
    FileSourceType.DOCUMENT.value,
    FileSourceType.APPLICATION.value,
    FileSourceType.CHAT.value,
}
_SECRET_KEYS = {"credential", "secret_key", "access_token", "password", "token", "api_key", "webhook_url"}


def _json_value(value, key=""):
    if isinstance(value, dict):
        return {str(k): _json_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item, key) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if key.lower() in _SECRET_KEYS and value not in (None, ""):
        return "***REDACTED***"
    return value


def _rows(queryset, fields=None):
    rows = queryset.values(*fields) if fields else queryset.values()
    return [_json_value(dict(row)) for row in rows]


class WorkspaceOffboardingService:
    """跨内核域的 Workspace 注销服务。"""

    @staticmethod
    def _resource_ids(workspace_id):
        application_ids = list(Application.objects.filter(workspace_id=workspace_id).values_list("id", flat=True))
        knowledge_ids = list(Knowledge.objects.filter(workspace_id=workspace_id).values_list("id", flat=True))
        document_ids = list(Document.objects.filter(knowledge_id__in=knowledge_ids).values_list("id", flat=True))
        chat_ids = list(Chat.objects.filter(application_id__in=application_ids).values_list("id", flat=True))
        model_ids = list(Model.objects.filter(workspace_id=workspace_id).values_list("id", flat=True))
        return {
            "application_ids": application_ids,
            "knowledge_ids": knowledge_ids,
            "document_ids": document_ids,
            "chat_ids": chat_ids,
            "model_ids": model_ids,
        }

    @staticmethod
    def _core_file_queryset(ids):
        return File.objects.filter(
            Q(source_type=FileSourceType.KNOWLEDGE.value, source_id__in=[str(i) for i in ids["knowledge_ids"]])
            | Q(source_type=FileSourceType.DOCUMENT.value, source_id__in=[str(i) for i in ids["document_ids"]])
            | Q(source_type=FileSourceType.APPLICATION.value, source_id__in=[str(i) for i in ids["application_ids"]])
            | Q(source_type=FileSourceType.CHAT.value, source_id__in=[str(i) for i in ids["chat_ids"]])
        )

    @classmethod
    def _core_counts(cls, workspace_id, ids=None):
        ids = ids or cls._resource_ids(workspace_id)
        app_ids = ids["application_ids"]
        knowledge_ids = ids["knowledge_ids"]
        document_ids = ids["document_ids"]
        chat_ids = ids["chat_ids"]
        resource_ids = [str(i) for i in app_ids + knowledge_ids + ids["model_ids"]]
        return {
            "application_folders": ApplicationFolder.objects.filter(workspace_id=workspace_id).count(),
            "applications": len(app_ids),
            "application_versions": ApplicationVersion.objects.filter(
                Q(workspace_id=workspace_id) | Q(application_id__in=app_ids)
            ).count(),
            "application_api_keys": ApplicationApiKey.objects.filter(
                Q(workspace_id=workspace_id) | Q(application_id__in=app_ids)
            ).count(),
            "application_access_tokens": ApplicationAccessToken.objects.filter(application_id__in=app_ids).count(),
            "application_knowledge_mappings": ApplicationKnowledgeMapping.objects.filter(
                application_id__in=app_ids
            ).count(),
            "chats": len(chat_ids),
            "chat_records": ChatRecord.objects.filter(chat_id__in=chat_ids).count(),
            "chat_user_stats": ApplicationChatUserStats.objects.filter(application_id__in=app_ids).count(),
            "chat_share_links": ChatShareLink.objects.filter(
                Q(application_id__in=app_ids) | Q(chat_id__in=chat_ids)
            ).count(),
            "long_term_memories": ApplicationLongTermMemory.objects.filter(application_id__in=app_ids).count(),
            "knowledge_folders": KnowledgeFolder.objects.filter(workspace_id=workspace_id).count(),
            "knowledge": len(knowledge_ids),
            "knowledge_workflows": KnowledgeWorkflow.objects.filter(knowledge_id__in=knowledge_ids).count(),
            "knowledge_workflow_versions": KnowledgeWorkflowVersion.objects.filter(
                Q(workspace_id=workspace_id) | Q(knowledge_id__in=knowledge_ids)
            ).count(),
            "documents": len(document_ids),
            "document_tags": DocumentTag.objects.filter(document_id__in=document_ids).count(),
            "paragraphs": Paragraph.objects.filter(document_id__in=document_ids).count(),
            "problems": Problem.objects.filter(knowledge_id__in=knowledge_ids).count(),
            "problem_paragraph_mappings": ProblemParagraphMapping.objects.filter(
                knowledge_id__in=knowledge_ids
            ).count(),
            "termbases": Termbase.objects.filter(knowledge_id__in=knowledge_ids).count(),
            "tags": Tag.objects.filter(knowledge_id__in=knowledge_ids).count(),
            "embeddings": Embedding.objects.filter(knowledge_id__in=knowledge_ids).count(),
            "models": len(ids["model_ids"]),
            "workspace_permissions": WorkspaceUserResourcePermission.objects.filter(
                workspace_id=workspace_id
            ).count(),
            "resource_chat_authorizes": ResourceChatUserAuthorize.objects.filter(
                workspace_id=workspace_id
            ).count(),
            "resource_chat_group_authorizes": ResourceChatUserGroupAuthorize.objects.filter(
                workspace_id=workspace_id
            ).count(),
            "logs": Log.objects.filter(workspace_id=workspace_id).count(),
            "resource_mappings": ResourceMapping.objects.filter(
                Q(source_id__in=resource_ids) | Q(target_id__in=resource_ids)
            ).count(),
            "core_files": cls._core_file_queryset(ids).count(),
        }

    @classmethod
    def _core_issues(cls, workspace_id, counts):
        issues = []
        if counts["applications"]:
            issues.append("有内核应用资源")
        if counts["knowledge"]:
            issues.append("有内核知识库资源")
        if counts["models"]:
            issues.append("有工作区模型配置")
        return issues

    @classmethod
    def plan(cls, workspace_id):
        ids = cls._resource_ids(workspace_id)
        core_counts = cls._core_counts(workspace_id, ids)
        hr = hr_preview_workspace_offboarding(workspace_id)
        issues = cls._core_issues(workspace_id, core_counts) + (hr.get("active_issues") or [])
        return {
            "workspace_id": workspace_id,
            "core": {"counts": core_counts, "active_issues": cls._core_issues(workspace_id, core_counts)},
            "hr": hr,
            "active_issues": issues,
            "can_offboard": not issues,
            "resource_ids": ids,
        }

    @classmethod
    def export_data(cls, workspace_id, plan=None):
        plan = plan or cls.plan(workspace_id)
        try:
            hr_data = hr_export_workspace_data(workspace_id)
        except AppApiException:
            hr_data = {"status": "ALREADY_OFFBOARDED"}
        ids = plan["resource_ids"]
        app_ids = ids["application_ids"]
        knowledge_ids = ids["knowledge_ids"]
        document_ids = ids["document_ids"]
        chat_ids = ids["chat_ids"]
        return {
            "workspace_id": workspace_id,
            "exported_at": timezone.now().isoformat(),
            "counts": {"core": plan["core"]["counts"], "hr": plan["hr"].get("counts", {})},
            "applications": _rows(Application.objects.filter(workspace_id=workspace_id)),
            "application_versions": _rows(ApplicationVersion.objects.filter(
                Q(workspace_id=workspace_id) | Q(application_id__in=app_ids)
            )),
            "application_api_keys": _rows(ApplicationApiKey.objects.filter(
                Q(workspace_id=workspace_id) | Q(application_id__in=app_ids)
            )),
            "application_access_tokens": _rows(ApplicationAccessToken.objects.filter(application_id__in=app_ids)),
            "chats": _rows(Chat.objects.filter(id__in=chat_ids)),
            "chat_records": _rows(ChatRecord.objects.filter(chat_id__in=chat_ids)),
            "chat_user_stats": _rows(ApplicationChatUserStats.objects.filter(application_id__in=app_ids)),
            "chat_share_links": _rows(ChatShareLink.objects.filter(
                Q(application_id__in=app_ids) | Q(chat_id__in=chat_ids)
            )),
            "long_term_memories": _rows(ApplicationLongTermMemory.objects.filter(application_id__in=app_ids)),
            "knowledge": _rows(Knowledge.objects.filter(workspace_id=workspace_id)),
            "knowledge_workflows": _rows(KnowledgeWorkflow.objects.filter(knowledge_id__in=knowledge_ids)),
            "knowledge_workflow_versions": _rows(KnowledgeWorkflowVersion.objects.filter(
                Q(workspace_id=workspace_id) | Q(knowledge_id__in=knowledge_ids)
            )),
            "documents": _rows(Document.objects.filter(id__in=document_ids)),
            "paragraphs": _rows(Paragraph.objects.filter(document_id__in=document_ids)),
            "problems": _rows(Problem.objects.filter(knowledge_id__in=knowledge_ids)),
            "problem_paragraph_mappings": _rows(ProblemParagraphMapping.objects.filter(knowledge_id__in=knowledge_ids)),
            "termbases": _rows(Termbase.objects.filter(knowledge_id__in=knowledge_ids)),
            "tags": _rows(Tag.objects.filter(knowledge_id__in=knowledge_ids)),
            "document_tags": _rows(DocumentTag.objects.filter(document_id__in=document_ids)),
            "embeddings": _rows(Embedding.objects.filter(knowledge_id__in=knowledge_ids), [
                "id", "source_id", "source_type", "is_active", "knowledge_id", "document_id", "paragraph_id", "meta"
            ]),
            "models": _rows(Model.objects.filter(workspace_id=workspace_id), [
                "id", "name", "status", "model_type", "model_name", "provider", "meta", "model_params_form", "workspace_id"
            ]),
            "workspace_permissions": _rows(WorkspaceUserResourcePermission.objects.filter(workspace_id=workspace_id)),
            "resource_chat_authorizes": _rows(ResourceChatUserAuthorize.objects.filter(workspace_id=workspace_id)),
            "resource_chat_group_authorizes": _rows(ResourceChatUserGroupAuthorize.objects.filter(workspace_id=workspace_id)),
            "logs": _rows(Log.objects.filter(workspace_id=workspace_id)),
            "resource_mappings": _rows(ResourceMapping.objects.filter(
                Q(source_id__in=[str(i) for i in app_ids + knowledge_ids + plan["resource_ids"]["model_ids"]])
                | Q(target_id__in=[str(i) for i in app_ids + knowledge_ids + plan["resource_ids"]["model_ids"]])
            )),
            "files": _rows(cls._core_file_queryset(ids), [
                "id", "file_name", "file_size", "sha256_hash", "source_type", "source_id", "meta"
            ]),
            "hr": hr_data,
        }

    @staticmethod
    def _delete_tree(model, workspace_id):
        """MPTT parent FK 使用 DO_NOTHING，按深度从叶子到根逐行删除。"""
        for object_id in model.objects.filter(workspace_id=workspace_id).order_by("-level", "-lft").values_list("id", flat=True):
            model.objects.filter(id=object_id).delete()

    @staticmethod
    def _delete_core(workspace_id, ids):
        app_ids = ids["application_ids"]
        knowledge_ids = ids["knowledge_ids"]
        document_ids = ids["document_ids"]
        chat_ids = ids["chat_ids"]
        resource_ids = [str(i) for i in app_ids + knowledge_ids + ids["model_ids"]]

        # 资源授权、映射和数据库文件不持有工作区字段，必须按资源 ID 精确删除。
        WorkspaceUserResourcePermission.objects.filter(workspace_id=workspace_id).delete()
        ResourceChatUserAuthorize.objects.filter(workspace_id=workspace_id).delete()
        ResourceChatUserGroupAuthorize.objects.filter(workspace_id=workspace_id).delete()
        ResourceMapping.objects.filter(
            Q(source_id__in=resource_ids) | Q(target_id__in=resource_ids)
        ).delete()
        WorkspaceOffboardingService._core_file_queryset(ids).delete()
        Log.objects.filter(workspace_id=workspace_id).delete()

        # application 子对象
        ApplicationKnowledgeMapping.objects.filter(application_id__in=app_ids).delete()
        ApplicationAccessToken.objects.filter(application_id__in=app_ids).delete()
        ApplicationApiKey.objects.filter(
            Q(workspace_id=workspace_id) | Q(application_id__in=app_ids)
        ).delete()
        ApplicationVersion.objects.filter(
            Q(workspace_id=workspace_id) | Q(application_id__in=app_ids)
        ).delete()
        ApplicationChatUserStats.objects.filter(application_id__in=app_ids).delete()
        ApplicationLongTermMemory.objects.filter(application_id__in=app_ids).delete()
        ChatRecord.objects.filter(chat_id__in=chat_ids).delete()
        ChatShareLink.objects.filter(Q(application_id__in=app_ids) | Q(chat_id__in=chat_ids)).delete()
        Chat.objects.filter(id__in=chat_ids).delete()
        Application.objects.filter(workspace_id=workspace_id).delete()
        WorkspaceOffboardingService._delete_tree(ApplicationFolder, workspace_id)

        # knowledge 子对象（内核模型多为 DO_NOTHING，不能只删 Knowledge）
        DocumentTag.objects.filter(document_id__in=document_ids).delete()
        ProblemParagraphMapping.objects.filter(knowledge_id__in=knowledge_ids).delete()
        Embedding.objects.filter(knowledge_id__in=knowledge_ids).delete()
        Paragraph.objects.filter(document_id__in=document_ids).delete()
        Problem.objects.filter(knowledge_id__in=knowledge_ids).delete()
        Termbase.objects.filter(knowledge_id__in=knowledge_ids).delete()
        Tag.objects.filter(knowledge_id__in=knowledge_ids).delete()
        Document.objects.filter(id__in=document_ids).delete()
        KnowledgeWorkflowVersion.objects.filter(
            Q(workspace_id=workspace_id) | Q(knowledge_id__in=knowledge_ids)
        ).delete()
        KnowledgeWorkflow.objects.filter(knowledge_id__in=knowledge_ids).delete()
        Knowledge.objects.filter(workspace_id=workspace_id).delete()
        WorkspaceOffboardingService._delete_tree(KnowledgeFolder, workspace_id)
        Model.objects.filter(workspace_id=workspace_id).delete()

    @classmethod
    def _storage_payload(cls, tombstone):
        pending = list(
            tombstone.storage_cleanup_objects.filter(status=StorageCleanupStatus.STORAGE_PENDING)
            .order_by("create_time")
            .values("key", "attempts", "last_error", "last_error_at")
        )
        return {
            "storage_status": tombstone.storage_status,
            "storage_cleanup_attempts": tombstone.storage_cleanup_attempts,
            "storage_last_error": tombstone.storage_last_error,
            "storage_last_error_at": tombstone.storage_last_error_at.isoformat()
            if tombstone.storage_last_error_at
            else None,
            "storage_cleanup_errors": [
                {
                    "key": row["key"],
                    "attempts": row["attempts"],
                    "error": row["last_error"],
                    "last_error_at": row["last_error_at"].isoformat() if row["last_error_at"] else None,
                }
                for row in pending
            ],
        }

    @classmethod
    def _cleanup_storage(cls, tombstone):
        pending_ids = list(
            tombstone.storage_cleanup_objects.filter(status=StorageCleanupStatus.STORAGE_PENDING).values_list(
                "id", flat=True
            )
        )
        if not pending_ids:
            return WorkspaceOffboard.objects.get(id=tombstone.id)

        try:
            storage = get_storage()
            storage_error = None
        except Exception as exc:
            # A broken S3 client/config is still a cleanup failure, not a reason to undo committed deletes.
            storage = None
            storage_error = exc

        for cleanup_id in pending_ids:
            with transaction.atomic():
                cleanup = (
                    WorkspaceOffboardStorageCleanup.objects.select_for_update()
                    .filter(id=cleanup_id, status=StorageCleanupStatus.STORAGE_PENDING)
                    .first()
                )
                if cleanup is None:
                    continue
                cleanup.attempts += 1
                cleanup.save(update_fields=["attempts", "update_time"])
                try:
                    if storage_error is not None:
                        raise storage_error
                    if cleanup.key:
                        # delete is idempotent for local/S3 backends; avoid a preflight stat race.
                        storage.delete(cleanup.key)
                except Exception as exc:
                    cleanup.last_error = str(exc)
                    cleanup.last_error_at = timezone.now()
                    cleanup.save(update_fields=["last_error", "last_error_at", "update_time"])
                else:
                    cleanup.status = StorageCleanupStatus.COMPLETED
                    cleanup.completed_at = timezone.now()
                    cleanup.save(update_fields=["status", "completed_at", "update_time"])

        with transaction.atomic():
            tombstone = WorkspaceOffboard.objects.select_for_update().get(id=tombstone.id)
            pending = list(
                tombstone.storage_cleanup_objects.filter(status=StorageCleanupStatus.STORAGE_PENDING)
                .order_by("create_time")
                .values("key", "attempts", "last_error", "last_error_at")
            )
            latest_error = max(
                (row for row in pending if row["last_error_at"]),
                key=lambda row: row["last_error_at"],
                default=None,
            )
            tombstone.storage_cleanup_attempts += 1
            tombstone.storage_status = (
                StorageCleanupStatus.STORAGE_PENDING if pending else StorageCleanupStatus.COMPLETED
            )
            if latest_error:
                tombstone.storage_last_error = latest_error["last_error"]
                tombstone.storage_last_error_at = latest_error["last_error_at"]
            tombstone.counts = {
                **tombstone.counts,
                "storage_cleanup_errors": [
                    {
                        "key": row["key"],
                        "attempts": row["attempts"],
                        "error": row["last_error"],
                        "last_error_at": row["last_error_at"].isoformat() if row["last_error_at"] else None,
                    }
                    for row in pending
                ],
            }
            tombstone.save(
                update_fields=[
                    "storage_cleanup_attempts",
                    "storage_status",
                    "storage_last_error",
                    "storage_last_error_at",
                    "counts",
                ]
            )
        return tombstone

    @classmethod
    def offboard(cls, workspace_id, *, user_id, force=False, dry_run=False, export_dir=None, include_export=False):
        if workspace_id in _RESERVED_WORKSPACE_IDS:
            return {"status": "BLOCKED", "workspace_id": workspace_id, "active_issues": ["保留工作区不可注销"]}
        already = WorkspaceOffboard.objects.filter(workspace_id=workspace_id).first()
        if already is not None:
            return {
                "status": "ALREADY_OFFBOARDED", "workspace_id": workspace_id, "counts": already.counts,
                "offboarded_at": already.offboarded_at.isoformat(), "exported_path": already.exported_path,
                **cls._storage_payload(already),
            }
        plan = cls.plan(workspace_id)
        result = {
            "status": "DRY_RUN" if dry_run else "PENDING", "workspace_id": workspace_id,
            "counts": {"core": plan["core"]["counts"], "hr": plan["hr"].get("counts", {})},
            "active_issues": plan["active_issues"], "can_offboard": plan["can_offboard"],
        }
        if dry_run:
            return result
        if plan["active_issues"] and not force:
            result["status"] = "BLOCKED"
            return result

        export_data = cls.export_data(workspace_id, plan) if (include_export or export_dir) else None
        exported_path = ""
        if export_dir:
            os.makedirs(export_dir, exist_ok=True)
            exported_path = os.path.join(
                export_dir, f"workspace_offboard_{workspace_id}_{timezone.now().strftime('%Y%m%d%H%M%S')}.json"
            )
            import json

            with open(exported_path, "w", encoding="utf-8") as handle:
                json.dump(export_data, handle, ensure_ascii=False, indent=2, default=str)

        with transaction.atomic():
            hr_result = hr_offboard_workspace(
                workspace_id, user_id=user_id, force=force, include_export=False, delete_storage=False
            )
            cls._delete_core(workspace_id, plan["resource_ids"])
            storage_keys = sorted({str(key) for key in hr_result.get("storage_keys", []) if key})
            tombstone = WorkspaceOffboard.objects.create(
                workspace_id=workspace_id,
                user_id=user_id,
                exported_path=exported_path,
                counts=result["counts"],
                force=force,
                storage_status=StorageCleanupStatus.STORAGE_PENDING
                if storage_keys
                else StorageCleanupStatus.COMPLETED,
            )
            WorkspaceOffboardStorageCleanup.objects.bulk_create(
                [WorkspaceOffboardStorageCleanup(workspace_offboard=tombstone, key=key) for key in storage_keys]
            )

        tombstone = cls._cleanup_storage(tombstone) if storage_keys else tombstone
        result.update({
            "status": "OFFBOARDED", "force": force, "exported_path": exported_path,
            "export": export_data if include_export else None,
            "offboarded_at": tombstone.offboarded_at.isoformat(),
            **cls._storage_payload(tombstone),
        })
        return result

    @classmethod
    def storage_cleanup_status(cls, workspace_id):
        tombstone = WorkspaceOffboard.objects.filter(workspace_id=workspace_id).first()
        if tombstone is None:
            raise AppApiException(404, "workspace has not been offboarded")
        return {
            "status": "OFFBOARDED",
            "workspace_id": workspace_id,
            "offboarded_at": tombstone.offboarded_at.isoformat(),
            **cls._storage_payload(tombstone),
        }

    @classmethod
    def retry_storage_cleanup(cls, workspace_id):
        tombstone = WorkspaceOffboard.objects.filter(workspace_id=workspace_id).first()
        if tombstone is None:
            raise AppApiException(404, "workspace has not been offboarded")
        tombstone = cls._cleanup_storage(tombstone)
        return {
            "status": "OFFBOARDED",
            "workspace_id": workspace_id,
            "offboarded_at": tombstone.offboarded_at.isoformat(),
            **cls._storage_payload(tombstone),
        }


def preview_workspace_offboarding(workspace_id):
    return WorkspaceOffboardingService.offboard(workspace_id, user_id=None, dry_run=True)


def export_workspace_data(workspace_id):
    if workspace_id in _RESERVED_WORKSPACE_IDS:
        raise AppApiException(400, "reserved workspace cannot be exported")
    if WorkspaceOffboard.objects.filter(workspace_id=workspace_id).exists():
        raise AppApiException(409, "workspace is already offboarded")
    return WorkspaceOffboardingService.export_data(workspace_id)


def offboard_workspace(workspace_id, *, user_id, force=False, include_export=False):
    result = WorkspaceOffboardingService.offboard(
        workspace_id, user_id=user_id, force=force, include_export=include_export
    )
    if result["status"] == "BLOCKED":
        raise AppApiException(409, "workspace offboarding blocked: " + "；".join(result.get("active_issues", [])))
    return result
