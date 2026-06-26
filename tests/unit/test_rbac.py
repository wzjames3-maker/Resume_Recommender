"""
智能招聘 RAG 推荐系统 - RBAC 权限控制测试
"""

import pytest

from src.common.errors import AuthorizationError, ErrorCode
from src.common.middleware.rbac import (
    Role,
    check_user_permission,
    get_user_permissions,
    has_permission,
    require_permission,
    require_role,
)


class TestRole:
    """Role 枚举测试"""

    def test_role_values(self):
        """测试角色值"""
        assert Role.ADMIN.value == "admin"
        assert Role.HR.value == "hr"
        assert Role.VIEWER.value == "viewer"


class TestHasPermission:
    """has_permission 测试"""

    def test_admin_has_all_permissions(self):
        """测试管理员拥有所有权限"""
        admin_permissions = [
            "resume:create",
            "resume:read",
            "resume:update",
            "resume:delete",
            "recommend:search",
            "recommend:refine",
            "recommend:lookup",
            "conversation:create",
            "conversation:read",
            "conversation:delete",
            "system:config",
            "system:audit_log",
            "user:create",
            "user:read",
            "user:update",
            "user:delete",
        ]

        for permission in admin_permissions:
            assert has_permission(Role.ADMIN, permission) is True

    def test_hr_permissions(self):
        """测试 HR 权限"""
        # HR 应有的权限
        assert has_permission(Role.HR, "resume:create") is True
        assert has_permission(Role.HR, "resume:read") is True
        assert has_permission(Role.HR, "recommend:search") is True
        assert has_permission(Role.HR, "recommend:refine") is True
        assert has_permission(Role.HR, "recommend:lookup") is True
        assert has_permission(Role.HR, "conversation:create") is True
        assert has_permission(Role.HR, "conversation:read") is True
        assert has_permission(Role.HR, "conversation:delete") is True

        # HR 不应有的权限
        assert has_permission(Role.HR, "resume:update") is False
        assert has_permission(Role.HR, "resume:delete") is False
        assert has_permission(Role.HR, "system:config") is False
        assert has_permission(Role.HR, "system:audit_log") is False
        assert has_permission(Role.HR, "user:create") is False

    def test_viewer_permissions(self):
        """测试 Viewer 权限"""
        # Viewer 应有的权限
        assert has_permission(Role.VIEWER, "recommend:lookup") is True
        assert has_permission(Role.VIEWER, "resume:read") is True
        assert has_permission(Role.VIEWER, "conversation:read") is True

        # Viewer 不应有的权限
        assert has_permission(Role.VIEWER, "resume:create") is False
        assert has_permission(Role.VIEWER, "resume:update") is False
        assert has_permission(Role.VIEWER, "resume:delete") is False
        assert has_permission(Role.VIEWER, "recommend:search") is False
        assert has_permission(Role.VIEWER, "recommend:refine") is False
        assert has_permission(Role.VIEWER, "conversation:create") is False
        assert has_permission(Role.VIEWER, "conversation:delete") is False

    def test_nonexistent_permission(self):
        """测试不存在的权限"""
        assert has_permission(Role.ADMIN, "nonexistent:permission") is False
        assert has_permission(Role.HR, "nonexistent:permission") is False


class TestRequireRole:
    """require_role 测试"""

    @pytest.fixture
    def admin_user(self):
        """管理员用户"""
        return {"sub": "admin-123", "role": "admin"}

    @pytest.fixture
    def hr_user(self):
        """HR 用户"""
        return {"sub": "hr-123", "role": "hr"}

    @pytest.fixture
    def viewer_user(self):
        """Viewer 用户"""
        return {"sub": "viewer-123", "role": "viewer"}

    @pytest.mark.asyncio
    async def test_require_admin_with_admin(self, admin_user):
        """测试管理员通过管理员检查"""
        checker = require_role("admin")
        result = await checker(admin_user)
        assert result == admin_user

    @pytest.mark.asyncio
    async def test_require_admin_with_hr(self, hr_user):
        """测试 HR 被管理员检查拒绝"""
        checker = require_role("admin")
        with pytest.raises(AuthorizationError) as exc_info:
            await checker(hr_user)
        assert exc_info.value.error_code == ErrorCode.AUTH_002

    @pytest.mark.asyncio
    async def test_require_hr_with_hr(self, hr_user):
        """测试 HR 通过 HR 检查"""
        checker = require_role("admin", "hr")
        result = await checker(hr_user)
        assert result == hr_user

    @pytest.mark.asyncio
    async def test_require_hr_with_viewer(self, viewer_user):
        """测试 Viewer 被 HR 检查拒绝"""
        checker = require_role("admin", "hr")
        with pytest.raises(AuthorizationError) as exc_info:
            await checker(viewer_user)
        assert exc_info.value.error_code == ErrorCode.AUTH_002

    @pytest.mark.asyncio
    async def test_require_viewer_with_all(self, admin_user, hr_user, viewer_user):
        """测试所有角色通过 Viewer 检查"""
        checker = require_role("admin", "hr", "viewer")

        # Admin 通过
        result = await checker(admin_user)
        assert result == admin_user

        # HR 通过
        result = await checker(hr_user)
        assert result == hr_user

        # Viewer 通过
        result = await checker(viewer_user)
        assert result == viewer_user


class TestRequirePermission:
    """require_permission 测试"""

    @pytest.fixture
    def admin_user(self):
        """管理员用户"""
        return {"sub": "admin-123", "role": "admin"}

    @pytest.fixture
    def hr_user(self):
        """HR 用户"""
        return {"sub": "hr-123", "role": "hr"}

    @pytest.fixture
    def viewer_user(self):
        """Viewer 用户"""
        return {"sub": "viewer-123", "role": "viewer"}

    @pytest.mark.asyncio
    async def test_require_permission_admin(self, admin_user):
        """测试管理员通过权限检查"""
        checker = require_permission("resume:delete")
        result = await checker(admin_user)
        assert result == admin_user

    @pytest.mark.asyncio
    async def test_require_permission_hr_denied(self, hr_user):
        """测试 HR 被权限检查拒绝"""
        checker = require_permission("resume:delete")
        with pytest.raises(AuthorizationError) as exc_info:
            await checker(hr_user)
        assert exc_info.value.error_code == ErrorCode.AUTH_002

    @pytest.mark.asyncio
    async def test_require_permission_hr_allowed(self, hr_user):
        """测试 HR 通过权限检查"""
        checker = require_permission("resume:create")
        result = await checker(hr_user)
        assert result == hr_user

    @pytest.mark.asyncio
    async def test_require_permission_viewer_denied(self, viewer_user):
        """测试 Viewer 被权限检查拒绝"""
        checker = require_permission("resume:create")
        with pytest.raises(AuthorizationError) as exc_info:
            await checker(viewer_user)
        assert exc_info.value.error_code == ErrorCode.AUTH_002

    @pytest.mark.asyncio
    async def test_require_multiple_permissions(self, admin_user):
        """测试多权限检查"""
        checker = require_permission("resume:create", "resume:read")
        result = await checker(admin_user)
        assert result == admin_user

    @pytest.mark.asyncio
    async def test_require_multiple_permissions_partial_denied(self, hr_user):
        """测试多权限检查部分拒绝"""
        checker = require_permission("resume:create", "resume:delete")
        with pytest.raises(AuthorizationError):
            await checker(hr_user)


class TestGetUserPermissions:
    """get_user_permissions 测试"""

    def test_admin_permissions(self):
        """测试管理员权限"""
        user = {"role": "admin"}
        permissions = get_user_permissions(user)
        assert "resume:create" in permissions
        assert "resume:delete" in permissions
        assert "system:config" in permissions

    def test_hr_permissions(self):
        """测试 HR 权限"""
        user = {"role": "hr"}
        permissions = get_user_permissions(user)
        assert "resume:create" in permissions
        assert "resume:delete" not in permissions

    def test_viewer_permissions(self):
        """测试 Viewer 权限"""
        user = {"role": "viewer"}
        permissions = get_user_permissions(user)
        assert "resume:read" in permissions
        assert "resume:create" not in permissions

    def test_invalid_role(self):
        """测试无效角色"""
        user = {"role": "invalid"}
        permissions = get_user_permissions(user)
        assert len(permissions) == 0


class TestCheckUserPermission:
    """check_user_permission 测试"""

    def test_admin_has_permission(self):
        """测试管理员有权限"""
        user = {"role": "admin"}
        assert check_user_permission(user, "resume:delete") is True

    def test_hr_lacks_permission(self):
        """测试 HR 缺少权限"""
        user = {"role": "hr"}
        assert check_user_permission(user, "resume:delete") is False

    def test_viewer_has_permission(self):
        """测试 Viewer 有权限"""
        user = {"role": "viewer"}
        assert check_user_permission(user, "resume:read") is True

    def test_viewer_lacks_permission(self):
        """测试 Viewer 缺少权限"""
        user = {"role": "viewer"}
        assert check_user_permission(user, "resume:create") is False

    def test_invalid_role(self):
        """测试无效角色"""
        user = {"role": "invalid"}
        assert check_user_permission(user, "resume:read") is False
