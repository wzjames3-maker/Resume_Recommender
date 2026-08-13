from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from jwt import ExpiredSignatureError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models import User

bearer = HTTPBearer(auto_error=False)

async def get_db():
    async with SessionLocal() as session:
        yield session

async def get_current_user(creds=Depends(bearer), db: AsyncSession = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(401, "未认证")
    try:
        payload = decode_token(creds.credentials)
    except ExpiredSignatureError:
        raise HTTPException(401, detail={"code": "TOKEN_EXPIRED", "message": "token 已过期"})
    except Exception:
        raise HTTPException(401, "token 无效或已过期")
    if payload.get("type") != "access":
        raise HTTPException(401, "token 类型错误")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "token 无效或已过期") from None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "token 无效或已过期")
    return user
