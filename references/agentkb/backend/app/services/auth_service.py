from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

async def create_user(db: AsyncSession, email: str, password: str, nickname: str) -> User:
    user = User(email=email, hashed_password=hash_password(password), nickname=nickname)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user