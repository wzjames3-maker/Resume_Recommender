"""
智能招聘 RAG 推荐系统 - JWT 认证测试
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import jwt
import pytest

from src.common.auth import (
    create_access_token,
    create_user_token,
    decode_access_token,
    verify_token_format,
)
from src.common.config import get_settings
from src.common.errors import AuthenticationError, ErrorCode


@pytest.fixture
def settings():
    """获取配置"""
    return get_settings()


@pytest.fixture
def valid_token():
    """创建有效的测试 Token"""
    return create_access_token(
        data={"sub": "test-user-123", "role": "hr"},
        expires_delta=timedelta(hours=1),
    )


@pytest.fixture
def expired_token():
    """创建已过期的测试 Token"""
    return create_access_token(
        data={"sub": "test-user-123", "role": "hr"},
        expires_delta=timedelta(seconds=-1),  # 已过期
    )


class TestCreateAccessToken:
    """create_access_token 测试"""

    def test_create_token(self):
        """测试创建 Token"""
        token = create_access_token(
            data={"sub": "user123", "role": "admin"},
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_claims(self, valid_token):
        """测试 Token 包含必要的声明"""
        # 解码 Token（不验证签名）
        payload = jwt.decode(
            valid_token,
            options={"verify_signature": False},
        )

        assert "sub" in payload
        assert "role" in payload
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_token_custom_claims(self):
        """测试自定义声明"""
        token = create_access_token(
            data={"sub": "user123", "role": "hr", "custom": "value"},
        )
        payload = jwt.decode(
            token,
            options={"verify_signature": False},
        )
        assert payload["custom"] == "value"

    def test_token_expiration(self, monkeypatch):
        """测试 Token 过期时间"""
        # 清除可能影响的环境变量
        monkeypatch.delenv("JWT_EXPIRATION_HOURS", raising=False)

        expires = timedelta(hours=2)
        token = create_access_token(
            data={"sub": "user123"},
            expires_delta=expires,
        )

        payload = jwt.decode(
            token,
            options={"verify_signature": False},
        )

        # 验证 exp 字段存在且是未来时间
        assert "exp" in payload
        exp_time = datetime.fromtimestamp(payload["exp"])
        now = datetime.utcnow()
        # 验证过期时间在未来的某个合理范围内（1秒到24小时）
        diff = exp_time - now
        assert 0 < diff.total_seconds() < 86400


class TestDecodeAccessToken:
    """decode_access_token 测试"""

    def test_decode_valid_token(self, valid_token):
        """测试解码有效 Token"""
        payload = decode_access_token(valid_token)
        assert payload["sub"] == "test-user-123"
        assert payload["role"] == "hr"

    def test_decode_expired_token(self, expired_token):
        """测试解码过期 Token"""
        with pytest.raises(AuthenticationError) as exc_info:
            decode_access_token(expired_token)

        assert exc_info.value.error_code == ErrorCode.AUTH_003

    def test_decode_invalid_token(self):
        """测试解码无效 Token"""
        with pytest.raises(AuthenticationError) as exc_info:
            decode_access_token("invalid-token")

        assert exc_info.value.error_code == ErrorCode.AUTH_004

    def test_decode_tampered_token(self, valid_token):
        """测试解码被篡改的 Token"""
        # 篡改 Token
        tampered_token = valid_token[:-5] + "XXXXX"

        with pytest.raises(AuthenticationError) as exc_info:
            decode_access_token(tampered_token)

        assert exc_info.value.error_code == ErrorCode.AUTH_004


class TestCreateUserToken:
    """create_user_token 测试"""

    def test_create_user_token(self):
        """测试创建用户 Token"""
        token = create_user_token(
            user_id="user123",
            role="admin",
        )
        assert isinstance(token, str)

    def test_user_token_payload(self):
        """测试用户 Token payload"""
        token = create_user_token(
            user_id="user123",
            role="hr",
            extra_data={"name": "Test User"},
        )

        payload = decode_access_token(token)
        assert payload["sub"] == "user123"
        assert payload["role"] == "hr"
        assert payload["name"] == "Test User"


class TestVerifyTokenFormat:
    """verify_token_format 测试"""

    def test_valid_format(self, valid_token):
        """测试有效格式"""
        assert verify_token_format(valid_token) is True

    def test_invalid_format_no_dots(self):
        """测试无效格式（没有点）"""
        assert verify_token_format("invalidtoken") is False

    def test_invalid_format_two_dots(self):
        """测试无效格式（两个点）"""
        assert verify_token_format("header.payload") is False

    def test_invalid_format_four_dots(self):
        """测试无效格式（四个点）"""
        assert verify_token_format("a.b.c.d") is False

    def test_invalid_format_empty(self):
        """测试空字符串"""
        assert verify_token_format("") is False

    def test_invalid_format_no_sub(self):
        """测试缺少 sub 字段"""
        # 创建一个没有 sub 的 Token
        import base64
        import json

        # 构造假 Token
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip("=")
        payload = base64.urlsafe_b64encode(json.dumps({"role": "hr"}).encode()).decode().rstrip("=")
        fake_token = f"{header}.{payload}.signature"

        assert verify_token_format(fake_token) is False
