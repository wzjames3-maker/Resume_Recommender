"""测试 RBAC 权限强制启用（SEC-T03）"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Mock get_current_user in rbac to avoid real auth
import src.common.middleware.rbac as rbac_mod
from src.api.main import app

client = TestClient(app)


def make_token(role: str) -> str:
    """Create a mock JWT for the given role."""
    from src.common.auth import create_user_token
    return create_user_token(user_id=f"{role}-001", role=role)


@pytest.fixture
def admin_token():
    return make_token("admin")


@pytest.fixture
def hr_token():
    return make_token("hr")


@pytest.fixture
def viewer_token():
    return make_token("viewer")


class TestUploadRBAC:
    """POST /api/v1/resumes/upload RBAC enforcement"""

    def test_viewer_upload_denied(self, viewer_token):
        r = client.post(
            "/api/v1/resumes/upload",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert r.status_code == 403

    def test_hr_upload_allowed(self, hr_token):
        r = client.post(
            "/api/v1/resumes/upload",
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert r.status_code in (200, 400, 422)  # auth passed, missing file body

    def test_no_token_upload_denied(self):
        r = client.post("/api/v1/resumes/upload")
        assert r.status_code in (401, 403)  # 401 = no auth header; auth blocks access


class TestChatRBAC:
    """POST /api/v1/chat RBAC enforcement"""

    def test_viewer_chat_denied(self, viewer_token):
        r = client.post(
            "/api/v1/chat",
            json={"message": "test"},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert r.status_code == 403  # viewer has no conversation:create


class TestConversationsRBAC:
    """Conversations endpoints RBAC enforcement"""

    def test_viewer_list_allowed(self, viewer_token):
        r = client.get(
            "/api/v1/conversations",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert r.status_code == 200  # viewer has conversation:read

    def test_viewer_delete_denied(self, viewer_token):
        r = client.delete(
            "/api/v1/conversations/fake-id",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert r.status_code == 403  # viewer has no conversation:delete


class TestPublicEndpoints:
    """Public endpoints should not require auth"""

    def test_health_no_auth(self):
        r = client.get("/health")
        assert r.status_code == 200

    def test_login_no_auth(self):
        r = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        assert r.status_code in (200, 401)  # public access works
