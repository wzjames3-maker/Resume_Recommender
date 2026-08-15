# coding=utf-8
"""
    @project: MaxKB
    @file： audit.py
    @date：2026/8/14
    @desc: HR 操作审计与授权查询 helper
"""
import json

import uuid_utils.compat as uuid

from hr.models import HrAccess, HrAuditLog


def write_audit_log(workspace_id, user_id, action, object_type="OTHER", object_id="", result="SUCCESS", detail=""):
    """
    写一条审计记录；审计行只增不改。
    :param workspace_id: 工作空间 ID
    :param user_id:      操作者
    :param action:       HrAuditAction 取值
    :param object_type:  HrAuditObjectType 取值
    :param object_id:    对象 ID 或描述
    :param result:       SUCCESS / FAILED / DENIED
    :param detail:       简短补充（str 原样入库；dict 序列化为 JSON 字符串，保证可解析）
    """
    if isinstance(detail, dict):
        detail = json.dumps(detail, ensure_ascii=False)
    HrAuditLog.objects.create(
        workspace_id=workspace_id,
        user_id=user_id,
        action=action,
        object_type=object_type,
        object_id=str(object_id)[:64] if object_id else "",
        result=result,
        detail=detail,
    )


def get_hr_role(workspace_id, user_id):
    """
    获取用户在指定工作空间的 HR 角色；无授权返回 None。
    """
    if user_id is None:
        return None
    try:
        user_id = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return None
    access = HrAccess.objects.filter(workspace_id=workspace_id, user_id=user_id).only("role").first()
    return access.role if access else None
