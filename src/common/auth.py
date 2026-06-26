"""
智能招聘 RAG 推荐系统 - JWT 认证模块

使用 PyJWT 实现 JWT 签发与验证
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.common.config import get_settings
from src.common.errors import AuthenticationError, ErrorCode

# HTTP Bearer 认证方案
security = HTTPBearer()


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    创建 JWT Access Token

    Args:
        data: Token payload 数据
        expires_delta: 过期时间增量（可选）

    Returns:
        str: 编码后的 JWT Token

    Example:
        >>> token = create_access_token({"sub": "user123", "role": "hr"})
    """
    settings = get_settings()

    # 复制数据，避免修改原始数据
    to_encode = data.copy()

    # 设置过期时间
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            hours=settings.jwt.JWT_EXPIRATION_HOURS
        )

    # 添加标准声明
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid4()),  # JWT ID，用于 Token 唯一标识
    })

    # 编码 Token
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt.JWT_SECRET_KEY,
        algorithm=settings.jwt.JWT_ALGORITHM,
    )

    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """
    解码并验证 JWT Access Token

    Args:
        token: JWT Token 字符串

    Returns:
        dict: Token payload 数据

    Raises:
        AuthenticationError: Token 无效或已过期
    """
    settings = get_settings()

    try:
        # 解码 Token
        payload = jwt.decode(
            token,
            settings.jwt.JWT_SECRET_KEY,
            algorithms=[settings.jwt.JWT_ALGORITHM],
        )
        return payload

    except jwt.ExpiredSignatureError:
        # Token 已过期
        raise AuthenticationError(
            error_code=ErrorCode.AUTH_003,
            detail="Token 已过期，请重新登录",
        )

    except jwt.InvalidTokenError as e:
        # Token 无效
        raise AuthenticationError(
            error_code=ErrorCode.AUTH_004,
            detail=f"Token 无效: {str(e)}",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    FastAPI 依赖项：获取当前认证用户

    从 Authorization header 中提取 JWT Token，并解码验证

    Args:
        credentials: HTTP Bearer 认证信息

    Returns:
        dict: 用户信息（包含 sub, role 等）

    Raises:
        AuthenticationError: Token 无效或已过期
    """
    # 提取 Token
    token = credentials.credentials

    # 解码 Token
    payload = decode_access_token(token)

    # 验证必要字段
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError(
            error_code=ErrorCode.AUTH_004,
            detail="Token 中缺少用户标识",
        )

    return payload


def create_user_token(
    user_id: str,
    role: str,
    extra_data: Optional[dict] = None,
) -> str:
    """
    为用户创建 Token

    Args:
        user_id: 用户 ID
        role: 用户角色（admin/hr/viewer）
        extra_data: 额外数据（可选）

    Returns:
        str: JWT Token
    """
    # 构建 payload
    payload = {
        "sub": user_id,
        "role": role,
    }

    # 添加额外数据
    if extra_data:
        payload.update(extra_data)

    return create_access_token(data=payload)


def verify_token_format(token: str) -> bool:
    """
    验证 Token 格式（不验证签名）

    Args:
        token: JWT Token 字符串

    Returns:
        bool: 格式是否正确
    """
    try:
        # 分割 Token
        parts = token.split(".")
        if len(parts) != 3:
            return False

        # 尝试解码 header 和 payload（不验证签名）
        import base64
        import json

        def decode_base64(data: str) -> bytes:
            """解码 base64url"""
            # 补齐 padding
            padding = 4 - len(data) % 4
            if padding != 4:
                data += "=" * padding
            return base64.urlsafe_b64decode(data)

        # 解码 header
        header_bytes = decode_base64(parts[0])
        header = json.loads(header_bytes)

        # 验证算法字段
        if "alg" not in header:
            return False

        # 解码 payload
        payload_bytes = decode_base64(parts[1])
        payload = json.loads(payload_bytes)

        # 验证必要字段
        if "sub" not in payload:
            return False

        return True

    except Exception:
        return False
