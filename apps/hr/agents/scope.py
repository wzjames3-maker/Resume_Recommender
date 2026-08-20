# coding=utf-8
"""Agent 简历范围辅助：统一使用 ResumeDatabaseMembership 限定文档集。"""

import uuid_utils.compat as uuid
from common.exception.app_exception import AppApiException
from hr.models import ResumeDatabase, ResumeDatabaseStatus, ResumeFile


def normalize_resume_database_ids(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        values = [str(item).strip() for item in value if str(item).strip()]
    else:
        values = [str(value).strip()]
    return list(dict.fromkeys(values)) or None


def validate_resume_database_ids(workspace_id, value):
    database_ids = normalize_resume_database_ids(value)
    if not database_ids:
        return None
    if len(database_ids) > 50:
        raise AppApiException(400, "resume_database_ids contains too many libraries")
    try:
        parsed_ids = [uuid.UUID(database_id) for database_id in database_ids]
    except (TypeError, ValueError) as exc:
        raise AppApiException(400, "resume_database_ids contains an invalid id") from exc
    active_ids = {
        str(database_id) for database_id in ResumeDatabase.objects.filter(
            workspace_id=workspace_id,
            status=ResumeDatabaseStatus.ACTIVE,
            id__in=parsed_ids,
        ).values_list("id", flat=True)
    }
    missing = [database_id for database_id in database_ids if database_id not in active_ids]
    if missing:
        raise AppApiException(400, "resume_database_ids contains an inaccessible or archived library")
    return database_ids


def candidate_document_ids(workspace_id, candidate_id, resume_database_ids=None):
    queryset = ResumeFile.objects.filter(
        workspace_id=workspace_id,
        candidate_id=candidate_id,
        document_id__isnull=False,
    )
    database_ids = normalize_resume_database_ids(resume_database_ids)
    if database_ids:
        queryset = queryset.filter(database_memberships__resume_database_id__in=database_ids)
    return [
        str(document_id) for document_id in queryset.values_list("document_id", flat=True).distinct()
    ]
