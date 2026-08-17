# coding=utf-8
"""
    @project: MaxKB
    @file： workspace_offboard.py
    @date：2026/8/18
    @desc：内核 Workspace 注销幂等账本。
"""
import uuid_utils.compat as uuid
from django.db import models


class StorageCleanupStatus(models.TextChoices):
    COMPLETED = "COMPLETED", "Completed"
    STORAGE_PENDING = "STORAGE_PENDING", "Storage pending"


class WorkspaceOffboard(models.Model):
    """Workspace 注销完成后的持久 tombstone，保护幂等重入并保留跨域清理摘要。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, unique=True, db_index=True)
    offboarded_at = models.DateTimeField(auto_now_add=True)
    user_id = models.UUIDField(null=True, blank=True)
    exported_path = models.CharField(max_length=1024, blank=True, default="")
    counts = models.JSONField(default=dict)
    force = models.BooleanField(default=False)
    storage_status = models.CharField(
        max_length=20, choices=StorageCleanupStatus.choices, default=StorageCleanupStatus.COMPLETED
    )
    storage_cleanup_attempts = models.PositiveIntegerField(default=0)
    storage_last_error = models.TextField(blank=True, default="")
    storage_last_error_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workspace_offboard"


class WorkspaceOffboardStorageCleanup(models.Model):
    """注销后对象存储逐对象清理账本，支持失败定位和安全重试。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_offboard = models.ForeignKey(
        WorkspaceOffboard, on_delete=models.CASCADE, related_name="storage_cleanup_objects"
    )
    key = models.CharField(max_length=2048)
    status = models.CharField(
        max_length=20, choices=StorageCleanupStatus.choices, default=StorageCleanupStatus.STORAGE_PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    last_error_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    create_time = models.DateTimeField(auto_now_add=True)
    update_time = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workspace_offboard_storage_cleanup"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_offboard", "key"], name="workspace_offboard_storage_key"
            )
        ]
        indexes = [
            models.Index(fields=["workspace_offboard", "status"], name="workspace_offboard_storage_st"),
        ]
