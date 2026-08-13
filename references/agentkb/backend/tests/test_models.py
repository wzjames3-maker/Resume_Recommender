import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import User, Workspace, WorkspaceMember, WorkspaceRole
from app.models.base import Base


@pytest.mark.asyncio
async def test_user_and_workspace_roundtrip():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession)
    async with Session() as s:
        u = User(email="a@b.com", hashed_password="x", nickname="A")
        s.add(u)
        await s.flush()
        ws = Workspace(name="WS", owner_id=u.id)
        s.add(ws)
        await s.flush()
        s.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.owner))
        await s.commit()
        result = await s.execute(select(User).where(User.email == "a@b.com"))
        assert result.scalar_one().nickname == "A"
    await engine.dispose()