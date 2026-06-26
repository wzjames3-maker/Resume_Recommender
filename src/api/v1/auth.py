"""
智能招聘 RAG 推荐系统 - 认证 API 路由

/api/v1/auth/login 端点
"""

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.common.auth import create_user_token
from src.common.errors import ErrorCode, AuthenticationError
from src.common.errors import AppException
from src.common.logger import get_logger
from src.common.rate_limiter import _login_limiter
from src.common.user_store import get_user_by_username, verify_password

logger = get_logger("api_auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class LoginResponse(BaseModel):
    """登录响应"""
    success: bool = Field(..., description="是否成功")
    token: Optional[str] = Field(None, description="JWT Token")
    user_id: Optional[str] = Field(None, description="用户 ID")
    role: Optional[str] = Field(None, description="用户角色")
    message: str = Field(..., description="消息")


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, http_request: Request):
    """用户登录（bcrypt 密码哈希验证 + 限流）"""
    # Rate limiting
    client_ip = http_request.client.host if http_request.client else "unknown"
    allowed = await _login_limiter.is_allowed(f"ratelimit:login:{client_ip}", limit=10)
    if not allowed:
        raise AppException(error_code=ErrorCode.SYS_004, detail="请求过于频繁，请稍后重试")

    logger.info(f"收到登录请求: username={request.username}")

    user = get_user_by_username(request.username)
    if not user or not verify_password(request.password, user["password_hash"]):
        logger.warning(f"登录失败: 用户名或密码错误")
        raise AuthenticationError(error_code=ErrorCode.AUTH_005, detail="用户名或密码错误")

    token = create_user_token(user_id=user["user_id"], role=user["role"])
    logger.info(f"登录成功: user_id={user['user_id']}, role={user['role']}")
    return LoginResponse(success=True, token=token, user_id=user["user_id"], role=user["role"], message="登录成功")


class VerifyRequest(BaseModel):
    """Token 验证请求"""
    token: str = Field(..., description="JWT Token")


class VerifyResponse(BaseModel):
    """Token 验证响应"""
    valid: bool = Field(..., description="Token 是否有效")
    user_id: Optional[str] = Field(None, description="用户 ID")
    role: Optional[str] = Field(None, description="用户角色")
    message: str = Field(..., description="消息")


@router.post("/verify", response_model=VerifyResponse)
async def verify_token(request: VerifyRequest):
    """验证 JWT Token 并返回用户信息（用于页面刷新恢复会话）"""
    try:
        from src.common.auth import decode_access_token
        payload = decode_access_token(request.token)
        return VerifyResponse(valid=True, user_id=payload.get("sub", ""), role=payload.get("role", ""), message="Token 有效")
    except Exception as e:
        return VerifyResponse(valid=False, user_id=None, role=None, message=f"Token 无效: {str(e)}")
