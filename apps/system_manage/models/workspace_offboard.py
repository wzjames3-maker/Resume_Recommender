# coding=utf-8
"""
    @project: MaxKB
    @file： workspace_offboard.py
    @date：2026/8/18
    @desc：内核 Workspace 注销幂等账本。
"""
import uuid_utils.compat as uuid
from django.db import models


class WorkspaceOffboard(models.Model):
    """Workspace 注销完成后的持久 tombstone，保护幂等重入并保留跨域清理摘要。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    workspace_id = models.CharField(max_length=64, unique=True, db_index=True)
    offboarded_at = models.DateTimeField(auto_now_add=True)
    user_id = models.UUIDField(null=True, blank=True)
    exported_path = models.CharField(max_length=1024, blank=True, default="")
    counts = models.JSONField(default=dict)
    force = models.BooleanField(default=False)

    class Meta:
        db_table = "workspace_offboard"
