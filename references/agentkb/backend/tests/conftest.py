import logging
import os

os.environ.setdefault(
    "MODEL_KEY_ENC_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)
os.environ.setdefault(
    "JWT_SECRET",
    "deadbeef" * 8,
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/agentkb",
)
os.environ.setdefault("RESUME_MAX_AUTO_RETRIES", "2")

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)

_CLEANUP_TABLES = "candidate_embeddings, candidate_overrides, candidate_revisions, candidate_events, resume_irs, resume_files, pii_mappings, candidates, parse_runs, parse_checkpoints, audit_events, workspace_members, workspaces, users"


@pytest.fixture(autouse=True)
def _in_memory_token_store(monkeypatch):
    tokens: dict[str, str] = {}

    async def store(user_id: int, jti: str, ttl_seconds: int) -> None:
        tokens[jti] = str(user_id)

    async def valid(jti: str) -> bool:
        return jti in tokens

    async def revoke(jti: str) -> None:
        tokens.pop(jti, None)

    monkeypatch.setattr("app.core.token_store.store_refresh_token", store)
    monkeypatch.setattr("app.core.token_store.is_refresh_token_valid", valid)
    monkeypatch.setattr("app.core.token_store.revoke_refresh_token", revoke)


@pytest.fixture(autouse=True, scope="session")
async def _cleanup_pg_tables():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {_CLEANUP_TABLES} RESTART IDENTITY CASCADE"))
    except (OSError, SQLAlchemyError) as exc:
        logger.warning("PG cleanup skipped: %s", exc)
    finally:
        await engine.dispose()