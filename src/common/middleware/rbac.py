"""
智能招聘 RAG 推荐系统 - RBAC 权限控制模块

基于角色的访问控制（Role-Based Access Control）
"""

from enum import Enum
from functools import wraps
from typing import Callable, List, Set

from fastapi import Depends, HTTPException

from src.common.auth import get_current_user
from src.common.errors import AuthorizationError, ErrorCode


class Role(str, Enum):
    """
    用户角色枚举

    对齐 PRD 权限矩阵：
    - admin: 全部权限
    - hr: 推荐查询、候选人查看、简历上传、个人对话历史
    - viewer: 只读（查看推荐结果、候选人详情）
    """

    ADMIN = "admin"
    HR = "hr"
    VIEWER = "viewer"


# 角色权限映射
ROLE_PERMISSIONS: dict[Role, Set[str]] = {
    Role.ADMIN: {
        # 简历管理
        "resume:create",
        "resume:read",
        "resume:update",
        "resume:delete",
        # 推荐
        "recommend:search",
        "recommend:refine",
        "recommend:lookup",
        # 对话
        "conversation:create",
        "conversation:read",
        "conversation:delete",
        # 系统配置
        "system:config",
        "system:audit_log",
        # 用户管理
        "user:create",
        "user:read",
        "user:update",
        "user:delete",
    },
    Role.HR: {
        # 简历管理（仅上传）
        "resume:create",
        "resume:read",
        # 推荐
        "recommend:search",
        "recommend:refine",
        "recommend:lookup",
        # 对话（个人）
        "conversation:create",
        "conversation:read",
        "conversation:delete",
    },
    Role.VIEWER: {
        # 只读
        "recommend:lookup",
        "resume:read",
        "conversation:read",
    },
}


def has_permission(role: Role, permission: str) -> bool:
    """
    检查角色是否拥有指定权限

    Args:
        role: 用户角色
        permission: 权限标识

    Returns:
        bool: 是否拥有权限
    """
    role_permissions = ROLE_PERMISSIONS.get(role, set())
    return permission in role_permissions


def require_role(*allowed_roles: str) -> Callable:
    """
    角色检查依赖工厂

    创建一个 FastAPI 依赖项，用于检查当前用户是否具有指定角色

    Args:
        *allowed_roles: 允许的角色列表

    Returns:
        Callable: FastAPI 依赖项

    Example:
        @app.get("/admin-only")
        async def admin_endpoint(user = Depends(require_role("admin"))):
            return {"message": "Admin only"}

        @app.get("/hr-or-admin")
        async def hr_endpoint(user = Depends(require_role("admin", "hr"))):
            return {"message": "HR or Admin"}
    """

    async def role_checker(
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        """
        检查当前用户角色

        Args:
            current_user: 当前用户信息（从 JWT Token 解码）

        Returns:
            dict: 用户信息

        Raises:
            AuthorizationError: 角色不在允许列表中
        """
        user_role = current_user.get("role")

        if not user_role:
            raise AuthorizationError(
                error_code=ErrorCode.AUTH_002,
                detail="用户角色信息缺失",
            )

        if user_role not in allowed_roles:
            raise AuthorizationError(
                error_code=ErrorCode.AUTH_002,
                detail=f"需要角色: {', '.join(allowed_roles)}，当前角色: {user_role}",
            )

        return current_user

    return role_checker


def require_permission(*required_permissions: str) -> Callable:
    """
    权限检查依赖工厂

    创建一个 FastAPI 依赖项，用于检查当前用户是否具有指定权限

    Args:
        *required_permissions: 需要的权限列表

    Returns:
        Callable: FastAPI 依赖项

    Example:
        @app.delete("/resumes/{id}")
        async def delete_resume(
            user = Depends(require_permission("resume:delete"))
        ):
            return {"message": "Deleted"}
    """

    async def permission_checker(
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        """
        检查当前用户权限

        Args:
            current_user: 当前用户信息（从 JWT Token 解码）

        Returns:
            dict: 用户信息

        Raises:
            AuthorizationError: 权限不足
        """
        user_role = current_user.get("role")

        if not user_role:
            raise AuthorizationError(
                error_code=ErrorCode.AUTH_002,
                detail="用户角色信息缺失",
            )

        try:
            role = Role(user_role)
        except ValueError:
            raise AuthorizationError(
                error_code=ErrorCode.AUTH_002,
                detail=f"无效的用户角色: {user_role}",
            )

        # 检查所有必需权限
        for permission in required_permissions:
            if not has_permission(role, permission):
                raise AuthorizationError(
                    error_code=ErrorCode.AUTH_002,
                    detail=f"需要权限: {permission}",
                )

        return current_user

    return permission_checker


# 预定义的常用权限依赖
require_admin = require_role("admin")
require_hr = require_role("admin", "hr")
require_viewer = require_role("admin", "hr", "viewer")


def get_user_permissions(user: dict) -> Set[str]:
    """
    获取用户所有权限

    Args:
        user: 用户信息

    Returns:
        Set[str]: 权限集合
    """
    user_role = user.get("role")

    try:
        role = Role(user_role)
    except ValueError:
        return set()

    return ROLE_PERMISSIONS.get(role, set())


def check_user_permission(user: dict, permission: str) -> bool:
    """
    检查用户是否拥有指定权限

    Args:
        user: 用户信息
        permission: 权限标识

    Returns:
        bool: 是否拥有权限
    """
    user_role = user.get("role")

    try:
        role = Role(user_role)
    except ValueError:
        return False

    return has_permission(role, permission)
