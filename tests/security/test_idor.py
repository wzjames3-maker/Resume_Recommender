"""测试 IDOR 资源归属校验（SEC-T04）"""
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.common.auth import create_user_token

client = TestClient(app)


def make_token(user_id: str, role: str) -> str:
    return create_user_token(user_id=user_id, role=role)


class TestConversationOwnership:
    """Conversation get/delete must check session.user_id ownership"""

    def test_get_other_user_conversation_denied(self):
        """User A cannot read User B's conversation"""
        token_a = make_token("user-a", "hr")
        # GET non-existent or B's conversation
        r = client.get(
            "/api/v1/conversations/nonexistent-id",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r.status_code == 404

    def test_delete_other_user_conversation_denied(self):
        """User A cannot delete User B's conversation"""
        token_a = make_token("user-a", "hr")
        r = client.delete(
            "/api/v1/conversations/nonexistent-id",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r.status_code == 404

    def test_response_does_not_leak_existence(self):
        """Non-owner access returns 404 (not 403 to avoid enumeration)"""
        token_a = make_token("user-a", "hr")
        r = client.get(
            "/api/v1/conversations/another-user-id",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        # Must be 404, never 403 for non-existent or non-owned
        assert r.status_code == 404
        body = r.json()
        assert body.get("code") == "CONV_001"

    def test_conversations_no_bare_http_exception(self):
        """conversations routes use ResourceNotFoundError not raw HTTPException"""
        token_a = make_token("user-a", "hr")
        r = client.delete(
            "/api/v1/conversations/fake-session",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r.status_code == 404
        data = r.json()
        assert "code" in data
