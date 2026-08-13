from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core import token_store
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models import User
from app.services.auth_service import create_user, get_user_by_email

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=64)
    nickname: str = Field(..., min_length=1, max_length=32)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

class RefreshResponse(BaseModel):
    access_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

@router.post("/register", status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if await get_user_by_email(db, body.email):
        raise HTTPException(409, "邮箱已注册")
    user = await create_user(db, body.email, body.password, body.nickname)
    return {"user_id": user.id}

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await get_user_by_email(db, body.email)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "邮箱或密码错误")
    refresh_token, jti = create_refresh_token(user.id)
    try:
        await token_store.store_refresh_token(user.id, jti, ttl_seconds=7 * 24 * 3600)
    except Exception:
        raise HTTPException(503, "认证服务暂不可用，请稍后重试")
    return TokenResponse(access_token=create_access_token(user.id), refresh_token=refresh_token)

@router.post("/refresh", response_model=RefreshResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        raise HTTPException(401, "refresh_token 无效或已过期")
    if payload.get("type") != "refresh":
        raise HTTPException(401, "refresh_token 类型错误")
    try:
        user_id = int(payload["sub"])
        jti = payload["jti"]
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "refresh_token 无效或已过期") from None
    if not isinstance(jti, str) or not jti:
        raise HTTPException(401, "refresh_token 无效或已过期")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "refresh_token 无效或已过期")
    try:
        valid = await token_store.is_refresh_token_valid(jti)
    except token_store.TokenStoreUnavailable:
        raise HTTPException(503, "认证服务暂不可用，请稍后重试") from None
    if not valid:
        raise HTTPException(401, "refresh_token 无效或已过期")
    return RefreshResponse(access_token=create_access_token(user.id))

@router.post("/logout", status_code=204)
async def logout(body: LogoutRequest, user: User = Depends(get_current_user)):
    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        return
    if payload.get("type") != "refresh" or not isinstance(payload.get("jti"), str) or not payload["jti"]:
        return
    if payload.get("sub") != str(user.id):
        raise HTTPException(403, "无权注销该会话")
    try:
        await token_store.revoke_refresh_token(payload["jti"])
    except Exception:
        raise HTTPException(503, "认证服务暂不可用，请稍后重试")
    return
