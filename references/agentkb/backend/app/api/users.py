from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import User

router = APIRouter(prefix="/api/v1/users", tags=["users"])

class UserOut(BaseModel):
    id: int
    email: str
    nickname: str
    created_at: str

class UserUpdate(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=32)

@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, email=user.email, nickname=user.nickname, created_at=user.created_at.isoformat())

@router.put("/me", response_model=UserOut)
async def update_me(body: UserUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user.nickname = body.nickname
    await db.commit()
    return UserOut(id=user.id, email=user.email, nickname=user.nickname, created_at=user.created_at.isoformat())