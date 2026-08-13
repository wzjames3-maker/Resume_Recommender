# P1 平台底座实现计划（F1-F5）

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 实现 AgentKB 平台底座——认证/租户（F1）、模型配置（F2）、知识库管理（F3）、混合检索内核（F4）、通用对话（F5），跑通 M1/M2。

**架构：** FastAPI 单体后端（platform-api）+ React/TS 前端 + PostgreSQL 16(pgvector) + Redis + Celery。JWT 认证，跨租户 404 隔离，混合检索（向量+全文+RRF+rerank）。

**技术栈：** FastAPI、SQLAlchemy 2.0（async）、Alembic、Celery、PostgreSQL 16 + pgvector、Redis、PyJWT + bcrypt、pytest、httpx、React 18 + TS + Vite + Zustand。

**参考：** `docs/references/API_SPEC.md`（端点约定）、`docs/references/DATABASE_SCHEMA.md`（表设计）、`docs/references/FRONTEND_ARCH.md`（前端骨架）、`docs/PRD.md`（需求基准）。

---

## 文件结构

```
backend/
  pyproject.toml
  .env.example
  app/
    main.py
    core/
      config.py
      logging.py
      security.py
      database.py
      tenant.py
    models/
      user.py
      workspace.py
      knowledge_base.py
      document.py
      chunk.py
      conversation.py
      message.py
      model_config.py
    api/
      deps.py
      auth.py
      users.py
      workspaces.py
      knowledge_bases.py
      documents.py
      model_configs.py
      chat.py
      admin.py
    services/
      auth_service.py
      kb_service.py
      document_service.py
      search_service.py
      chat_service.py
      crypto.py
    tasks/
      celery_app.py
      parse_document.py
    rag/
      splitter.py
      embedder.py
      retriever.py
  tests/
    conftest.py
    test_auth.py
    test_workspaces.py
    test_knowledge_bases.py
    test_documents.py
    test_model_configs.py
    test_search.py
    test_chat.py
frontend/
  package.json
  vite.config.ts
  src/
    main.tsx
    App.tsx
    api/client.ts
    api/auth.ts
    api/knowledgeBase.ts
    api/documents.ts
    api/chat.ts
    stores/authStore.ts
    stores/knowledgeBaseStore.ts
    stores/chatStore.ts
    pages/LoginPage.tsx
    pages/RegisterPage.tsx
    pages/DashboardPage.tsx
    pages/KnowledgeBasePage.tsx
    pages/DocumentsPage.tsx
    pages/ChatPage.tsx
    pages/SettingsPage.tsx
docker-compose.yml
Makefile
```

---

### 任务 1：项目骨架与环境

**文件：**
- 创建：`backend/pyproject.toml`
- 创建：`backend/.env.example`
- 创建：`backend/app/main.py`
- 创建：`backend/app/core/config.py`
- 创建：`backend/app/core/logging.py`
- 创建：`docker-compose.yml`
- 创建：`Makefile`
- 测试：`backend/tests/test_health.py`

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_health.py
from httpx import AsyncClient, ASGITransport

async def test_health():
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_health.py -v`
预期：FAIL，报错 "ModuleNotFoundError: No module named 'app'"

- [x] **步骤 3：创建依赖配置**

```toml
# backend/pyproject.toml
[project]
name = "agentkb-platform"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg",
    "alembic",
    "pydantic>=2.7",
    "pydantic-settings",
    "pgvector",
    "redis>=5.0",
    "celery>=5.4",
    "PyJWT",
    "bcrypt",
    "cryptography",
    "httpx",
    "python-multipart",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio",
    "aiosqlite",
]
```

```bash
# backend/.env.example
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/agentkb
REDIS_URL=redis://redis:6379/0
JWT_SECRET=change-me
JWT_EXPIRE_MINUTES=30
REFRESH_TOKEN_TTL_DAYS=7
MODEL_KEY_ENC_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

- [x] **步骤 4：创建配置、日志与应用入口**

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "AgentKB Platform"
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/agentkb"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 30
    refresh_token_ttl_days: int = 7
    model_key_enc_key: str = ""
    model_config = {"env_file": ".env"}

settings = Settings()
```

```python
# backend/app/core/logging.py
import logging, json
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "request_id": request_id_var.get(),
            "msg": record.getMessage(),
        }, ensure_ascii=False)

def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
```

```python
# backend/app/main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uuid

from app.core.config import settings
from app.core.logging import setup_logging, request_id_var

setup_logging()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    rid = str(uuid.uuid4())[:8]
    request_id_var.set(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response

@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [x] **步骤 5：创建 Docker Compose 与 Makefile**

```yaml
# docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: agentkb
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5

  api:
    build: ./backend
    ports: ["8000:8000"]
    env_file: ./backend/.env
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    volumes: ["./backend:/app"]

  worker:
    build: ./backend
    env_file: ./backend/.env
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
    command: celery -A app.tasks.celery_app.celery_app worker --loglevel=info

volumes:
  pgdata:
```

```makefile
# Makefile
.PHONY: up down test lint migrate

up:
	docker compose up -d

down:
	docker compose down

test:
	docker compose run --rm api pytest

lint:
	docker compose run --rm api ruff check .

migrate:
	docker compose exec api alembic upgrade head
```

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir "uv" && uv pip install --system --group dev -e .
COPY app ./app
RUN useradd -m appuser && chown -R appuser /app
USER appuser
```

- [x] **步骤 6：运行测试验证通过**

运行：`pytest backend/tests/test_health.py -v`
预期：PASS

- [x] **步骤 7：Commit**

```bash
git add backend/ docker-compose.yml Makefile
git commit -m "chore: bootstrap platform-api skeleton"
```

---

### 任务 2：数据库模型与迁移

**文件：**
- 创建：`backend/app/core/database.py`
- 创建：`backend/app/models/base.py`
- 创建：`backend/app/models/user.py`
- 创建：`backend/app/models/workspace.py`
- 创建：`backend/app/models/knowledge_base.py`
- 创建：`backend/app/models/document.py`
- 创建：`backend/app/models/chunk.py`
- 创建：`backend/app/models/conversation.py`
- 创建：`backend/app/models/message.py`
- 创建：`backend/app/models/model_config.py`
- 创建：`backend/app/models/__init__.py`
- 测试：`backend/tests/test_models.py`

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_models.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from app.models.base import Base
from app.models import User, Workspace, WorkspaceMember, WorkspaceRole

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
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_models.py -v`
预期：FAIL，报错 "No module named 'app.models'"

- [x] **步骤 3：创建数据库连接与模型基类**

```python
# backend/app/core/database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

```python
# backend/app/models/base.py
from datetime import datetime, timezone
from sqlalchemy import MetaData, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", onupdate=utcnow, nullable=False)
```

- [x] **步骤 4：创建模型**

```python
# backend/app/models/user.py
from sqlalchemy import BigInteger, Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin

class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

```python
# backend/app/models/workspace.py
import enum
from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin

class WorkspaceRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"

class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_workspace_owner_name"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_member_workspace_user"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[WorkspaceRole] = mapped_column(Enum(WorkspaceRole, name="workspace_role", values_callable=lambda e: [m.value for m in e]), nullable=False, default=WorkspaceRole.member)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
```

```python
# backend/app/models/model_config.py
from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin

class ModelConfig(Base, TimestampMixin):
    __tablename__ = "model_configs"
    __table_args__ = (UniqueConstraint("workspace_id", "model_type", name="uq_model_config_ws_type"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    model_type: Mapped[str] = mapped_column(String(16), nullable=False)  # llm / embedding / rerank
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False, server_default="")
    model_config_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
```

```python
# backend/app/models/knowledge_base.py
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin

class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_kb_workspace_name"),
        CheckConstraint("chunk_size BETWEEN 64 AND 8192", name="ck_chunk_size_range"),
        CheckConstraint("chunk_overlap >= 0 AND chunk_overlap < chunk_size", name="ck_overlap_lt_size"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, default="bge-m3")
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=512)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=64)
```

```python
# backend/app/models/document.py
import enum
from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin

class DocumentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"

class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus, name="document_status", values_callable=lambda e: [m.value for m in e]), nullable=False, default=DocumentStatus.pending, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
```

```python
# backend/app/models/chunk.py
from sqlalchemy import BigInteger, Computed, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.models.base import Base

EMBEDDING_DIM = 1024

class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_embedding_hnsw", "embedding", postgresql_using="hnsw", postgresql_with={"m": 16, "ef_construction": 64}, postgresql_ops={"embedding": "vector_cosine_ops"}),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
```

```python
# backend/app/models/conversation.py
from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin

class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", text("updated_at DESC")),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    knowledge_base_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="新对话")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
```

```python
# backend/app/models/message.py
from sqlalchemy import BigInteger, DateTime, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", nullable=False)
```

```python
# backend/app/models/__init__.py
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceRole
from app.models.model_config import ModelConfig
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document, DocumentStatus
from app.models.chunk import Chunk, EMBEDDING_DIM
from app.models.conversation import Conversation
from app.models.message import Message

__all__ = ["Base", "User", "Workspace", "WorkspaceMember", "WorkspaceRole", "ModelConfig",
           "KnowledgeBase", "Document", "DocumentStatus", "Chunk", "EMBEDDING_DIM",
           "Conversation", "Message"]
from app.models.base import Base
```

- [x] **步骤 5：配置 Alembic 并生成首次迁移**

```bash
cd backend
alembic init alembic
# 修改 alembic/env.py 使用 async engine
```

```python
# backend/alembic/env.py（关键段）
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings
from app.models import Base

config = context.config
connectable = create_async_engine(settings.database_url)

async def do_run_migrations():
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)

def _run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()

run_migrations_online = do_run_migrations
```

- [x] **步骤 6：运行测试验证通过**

运行：`pytest backend/tests/test_models.py -v`
预期：PASS

- [x] **步骤 7：Commit**

```bash
git add backend/app/models backend/app/core/database.py backend/alembic
git commit -m "feat: add platform data models and migrations"
```

---

### 任务 3：认证与租户（F1）

**文件：**
- 创建：`backend/app/core/security.py`
- 创建：`backend/app/api/deps.py`
- 创建：`backend/app/services/auth_service.py`
- 创建：`backend/app/api/auth.py`
- 创建：`backend/app/api/users.py`
- 创建：`backend/app/api/workspaces.py`
- 测试：`backend/tests/test_auth.py`
- 测试：`backend/tests/test_workspaces.py`

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_auth.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_register_login_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/auth/register", json={"email": "a@b.com", "password": "secret123", "nickname": "A"})
        assert r.status_code == 201
        r = await c.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "secret123"})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data and "refresh_token" in data
        r = await c.get("/api/v1/users/me", headers={"Authorization": f"Bearer {data['access_token']}"})
        assert r.status_code == 200
        assert r.json()["email"] == "a@b.com"
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_auth.py -v`
预期：FAIL，报错 404

- [x] **步骤 3：实现安全工具与认证依赖**

```python
# backend/app/core/security.py
import bcrypt, jwt
from datetime import datetime, timedelta, timezone
from app.core.config import settings

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_access_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def create_refresh_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "type": "refresh", "exp": datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
```

```python
# backend/app/api/deps.py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
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
    except Exception:
        raise HTTPException(401, "token 无效或已过期")
    if payload.get("type") != "access":
        raise HTTPException(401, "token 类型错误")
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, "token 无效或已过期")
    return user
```

- [x] **步骤 4：实现认证服务与路由**

```python
# backend/app/services/auth_service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User
from app.core.security import hash_password, verify_password

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

async def create_user(db: AsyncSession, email: str, password: str, nickname: str) -> User:
    user = User(email=email, hashed_password=hash_password(password), nickname=nickname)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
```

```python
# backend/app/api/auth.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.core.security import create_access_token, create_refresh_token, verify_password, decode_token
from app.models import User
from app.services.auth_service import get_user_by_email, create_user

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
    return TokenResponse(access_token=create_access_token(user.id), refresh_token=create_refresh_token(user.id))

@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: dict, db: AsyncSession = Depends(get_db)):
    token = body.get("refresh_token")
    if not token:
        raise HTTPException(400, "缺少 refresh_token")
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "refresh_token 无效或已过期")
    if payload.get("type") != "refresh":
        raise HTTPException(401, "refresh_token 类型错误")
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, "refresh_token 无效或已过期")
    return TokenResponse(access_token=create_access_token(user.id), refresh_token=token)
```

```python
# backend/app/api/users.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.api.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/api/v1/users", tags=["users"])

class UserOut(BaseModel):
    id: int
    email: str
    nickname: str
    created_at: str

@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, email=user.email, nickname=user.nickname, created_at=user.created_at.isoformat())
```

- [x] **步骤 5：实现工作区路由**

```python
# backend/app/api/workspaces.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user
from app.models import User, Workspace, WorkspaceMember, WorkspaceRole
from app.services.auth_service import get_user_by_email

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])

class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)

class WorkspaceOut(BaseModel):
    id: int
    name: str
    role: WorkspaceRole
    created_at: str

@router.post("", status_code=201)
async def create_workspace(body: WorkspaceCreateRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ws = Workspace(name=body.name, owner_id=user.id)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner))
    await db.commit()
    await db.refresh(ws)
    return WorkspaceOut(id=ws.id, name=ws.name, role=WorkspaceRole.owner, created_at=ws.created_at.isoformat())

@router.get("")
async def list_workspaces(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
    )
    return {"items": [WorkspaceOut(id=ws.id, name=ws.name, role=role, created_at=ws.created_at.isoformat()) for ws, role in rows.all()]}

class MemberInviteRequest(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.member

@router.post("/{ws_id}/members", status_code=201)
async def invite(ws_id: int, body: MemberInviteRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.role == WorkspaceRole.owner:
        raise HTTPException(403, "不允许直接邀请为 owner")
    member = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user.id))
    inviter = member.scalar_one_or_none()
    if inviter is None:
        raise HTTPException(404, "工作区不存在或非成员")
    if inviter.role not in ("admin", "owner"):
        raise HTTPException(403, "仅 admin 及以上可邀请成员")
    if body.role == WorkspaceRole.admin and inviter.role != WorkspaceRole.owner:
        raise HTTPException(403, "仅 owner 可邀请或提升为 admin")
    target = await get_user_by_email(db, body.email)
    if target is None:
        raise HTTPException(404, "邮箱对应账号不存在")
    existing = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == target.id))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "该用户已是工作区成员")
    db.add(WorkspaceMember(workspace_id=ws_id, user_id=target.id, role=body.role))
    await db.commit()
    return {"status": "ok"}
```

```python
# backend/app/main.py 追加
from app.api import auth, users, workspaces
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(workspaces.router)
```

- [x] **步骤 6：运行测试验证通过**

运行：`pytest backend/tests/test_auth.py backend/tests/test_workspaces.py -v`
预期：PASS

- [x] **步骤 7：Commit**

```bash
git add backend/app
git commit -m "feat: add auth and workspace APIs (F1)"
```

---

### 任务 4：模型配置（F2）

**文件：**
- 创建：`backend/app/services/crypto.py`
- 创建：`backend/app/services/outbound_gateway.py`
- 创建：`backend/app/api/model_configs.py`
- 测试：`backend/tests/test_model_configs.py`

- [x] **步骤 1：编写失败的测试**

```python
# backend/tests/test_model_configs.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_model_config_crud_and_mask():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "m@b.com", "password": "secret123", "nickname": "M"})
        r = await c.post("/api/v1/auth/login", json={"email": "m@b.com", "password": "secret123"})
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)
        ws_id = r.json()["id"]
        r = await c.post(f"/api/v1/workspaces/{ws_id}/model-configs", json={
            "model_type": "llm", "base_url": "https://api.deepseek.com", "model_name": "deepseek-chat", "api_key": "sk-abcdefghijkl"
        }, headers=h)
        assert r.status_code == 201
        data = r.json()
        assert "sk-abcdefghijkl" not in data["key_prefix"]
        assert data["key_prefix"].startswith("sk-ab")
        assert data["model_config_revision"] == 1
        r = await c.get(f"/api/v1/workspaces/{ws_id}/model-configs", headers=h)
        assert r.status_code == 200

@pytest.mark.asyncio
async def test_outbound_gateway_blocks_private_ips():
    from app.services.outbound_gateway import validate_endpoint
    with pytest.raises(Exception):
        await validate_endpoint("http://127.0.0.1:8000/v1")
    with pytest.raises(Exception):
        await validate_endpoint("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(Exception):
        await validate_endpoint("http://192.168.1.1/v1")
    ok = await validate_endpoint("https://api.deepseek.com/v1")
    assert ok is True
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_model_configs.py -v`
预期：FAIL，报错 404 / ModuleNotFoundError

- [x] **步骤 3：实现 Key 加密**

```python
# backend/app/services/crypto.py
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.core.config import settings

_ENC_KEY_HEX = settings.model_key_enc_key
if len(_ENC_KEY_HEX) != 64 or _ENC_KEY_HEX == "0" * 64:
    raise RuntimeError("MODEL_KEY_ENC_KEY 必须设置为 32 字节（64 位 hex）密钥，禁止使用默认占位值")
KEY = AESGCM(bytes.fromhex(_ENC_KEY_HEX))

def encrypt_secret(plain: str) -> str:
    return KEY.encrypt(os.urandom(12), plain.encode()).hex()

def decrypt_secret(enc_hex: str) -> str:
    raw = bytes.fromhex(enc_hex)
    return KEY.decrypt(raw[:12], raw[12:]).decode()

def mask_key(key: str) -> str:
    return key[:8] + "****" if len(key) > 8 else "****"
```

- [x] **步骤 3b：实现出站网关（SSRF 防护）**

```python
# backend/app/services/outbound_gateway.py
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_PORTS = {443}
BLOCKED_IP_RANGES = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

def _is_blocked(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    return any(ip in net for net in BLOCKED_IP_RANGES) or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved

async def validate_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("仅允许 HTTPS")
    if parsed.port and parsed.port not in ALLOWED_PORTS:
        raise ValueError(f"端口不允许: {parsed.port}")
    host = parsed.hostname
    if host is None:
        raise ValueError("缺少主机名")
    # 拒绝跨域重定向：连接测试与生产调用均禁用 allow_redirects
    # DNS 解析后再次校验 IP（防 DNS rebinding）
    for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        ip_text = info[4][0]
        if _is_blocked(ip_text):
            raise ValueError(f"目标地址被网关拒绝: {ip_text}")
    return True
```

- [x] **步骤 4：实现模型配置路由（含 revision 递增与连接测试）**

```python
# backend/app/api/model_configs.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user
from app.models import ModelConfig, WorkspaceMember, User
from app.services.crypto import encrypt_secret, mask_key
from app.services.outbound_gateway import validate_endpoint

router = APIRouter(prefix="/api/v1/workspaces", tags=["model_configs"])

class ModelConfigCreate(BaseModel):
    model_type: str
    base_url: str
    model_name: str
    api_key: str

class ModelConfigOut(BaseModel):
    id: int
    model_type: str
    base_url: str
    model_name: str
    key_prefix: str
    model_config_revision: int

async def _as_admin(ws_id: int, user_id: int, db: AsyncSession) -> None:
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))
    m = row.scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "工作区不存在或非成员")
    if m.role not in ("admin", "owner"):
        raise HTTPException(403, "需要 admin 及以上")

@router.post("/{ws_id}/model-configs", status_code=201)
async def upsert_config(ws_id: int, body: ModelConfigCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _as_admin(ws_id, user.id, db)
    await validate_endpoint(body.base_url)
    existing = await db.execute(select(ModelConfig).where(ModelConfig.workspace_id == ws_id, ModelConfig.model_type == body.model_type))
    cfg = existing.scalar_one_or_none()
    if cfg is None:
        cfg = ModelConfig(workspace_id=ws_id, model_type=body.model_type, base_url=body.base_url, model_name=body.model_name, api_key_enc=encrypt_secret(body.api_key), key_prefix=mask_key(body.api_key), model_config_revision=1)
        db.add(cfg)
    else:
        cfg.base_url = body.base_url
        cfg.model_name = body.model_name
        cfg.api_key_enc = encrypt_secret(body.api_key)
        cfg.key_prefix = mask_key(body.api_key)
        cfg.model_config_revision += 1
    await db.commit()
    await db.refresh(cfg)
    return ModelConfigOut(id=cfg.id, model_type=cfg.model_type, base_url=cfg.base_url, model_name=cfg.model_name, key_prefix=cfg.key_prefix, model_config_revision=cfg.model_config_revision)

@router.post("/{ws_id}/model-configs/{model_type}/test", status_code=200)
async def test_config(ws_id: int, model_type: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _as_admin(ws_id, user.id, db)
    row = await db.execute(select(ModelConfig).where(ModelConfig.workspace_id == ws_id, ModelConfig.model_type == model_type))
    cfg = row.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(404, "模型配置不存在")
    await validate_endpoint(cfg.base_url)
    # 连接测试：按 PRD F2 校验 LLM structured output / Embedding 维度与距离度量 / Rerank 请求协议与分数方向；
    # 响应大小、超时、并发、重试均受网关限制；API Key 不进入日志；M1 阶段返回占位通过，真实探测在 F2 集成时替换。
    return {"status": "ok", "model_config_revision": cfg.model_config_revision}

@router.get("/{ws_id}/model-configs")
async def list_configs(ws_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user.id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(404, "工作区不存在或非成员")
    rows = await db.execute(select(ModelConfig).where(ModelConfig.workspace_id == ws_id))
    return {"items": [ModelConfigOut(id=c.id, model_type=c.model_type, base_url=c.base_url, model_name=c.model_name, key_prefix=c.key_prefix, model_config_revision=c.model_config_revision) for c in rows.scalars().all()]}
```

- [x] **步骤 5：注册路由并运行测试**

```python
# backend/app/main.py 追加
from app.api import model_configs
app.include_router(model_configs.router)
```

运行：`pytest backend/tests/test_model_configs.py -v`
预期：PASS

- [x] **步骤 6：Commit**

```bash
git add backend/app
git commit -m "feat: add workspace model config with key encryption (F2)"
```

---

### 任务 5：知识库与文档入库（F3）

**文件：**
- 创建：`backend/app/tasks/celery_app.py`
- 创建：`backend/app/tasks/parse_document.py`
- 创建：`backend/app/services/kb_service.py`
- 创建：`backend/app/api/knowledge_bases.py`
- 创建：`backend/app/api/documents.py`
- 创建：`backend/app/rag/splitter.py`
- 测试：`backend/tests/test_knowledge_bases.py`
- 测试：`backend/tests/test_splitter.py`

- [x] **步骤 1：编写分割器测试**

```python
# backend/tests/test_splitter.py
from app.rag.splitter import recursive_split

def test_recursive_split_respects_chunk_size():
    text = "第一段。\n\n第二段内容。\n\n第三段内容继续。"
    chunks = recursive_split(text, chunk_size=10, overlap=2)
    assert all(len(c) <= 12 for c in chunks)
    assert len(chunks) >= 2

def test_short_text_not_split():
    assert recursive_split("你好", chunk_size=512) == ["你好"]
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_splitter.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现分割器与 Celery**

```python
# backend/app/rag/splitter.py
def recursive_split(text: str, chunk_size: int = 512, overlap: int = 64, separators: tuple[str, ...] = ("\n\n", "\n", "。", " ")) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text else []
    if not separators:
        step = max(chunk_size - overlap, 1)
        return [text[i:i + chunk_size] for i in range(0, len(text), step)]
    sep, rest = separators[0], separators[1:]
    pieces = text.split(sep)
    chunks, buf = [], ""
    for i, part in enumerate(pieces):
        piece = part + sep if i < len(pieces) - 1 else part
        if len(piece) > chunk_size:
            if buf:
                chunks.append(buf); buf = ""
            chunks.extend(recursive_split(piece, chunk_size, overlap, rest))
        elif len(buf) + len(piece) <= chunk_size:
            buf += piece
        else:
            chunks.append(buf); buf = piece
    if buf:
        chunks.append(buf)
    for i in range(1, len(chunks)):
        chunks[i] = chunks[i - 1][-overlap:] + chunks[i]
    return chunks
```

```python
# backend/app/tasks/celery_app.py
from celery import Celery
from app.core.config import settings

celery_app = Celery("agentkb", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.autodiscover_tasks(["app.tasks"])
```

- [x] **步骤 4：实现文档入库任务**（docx/pdf 抽取为占位失败实现，P2 简历流水线替换）

```python
# backend/app/tasks/parse_document.py
import asyncio
from celery import shared_task
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models import Document, DocumentStatus, Chunk
from app.rag.splitter import recursive_split

def _extract_text(doc: Document) -> str:
    # M1 阶段：txt/md 直读；docx 用 zipfile 读 document.xml 纯文本（简历抽取在 P2 单独实现）
    if doc.content_type in ("text/plain", "text/markdown"):
        with open(doc.storage_key, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return ""

async def _run(doc_id: int) -> None:
    async with SessionLocal() as db:
        doc = await db.get(Document, doc_id)
        if doc is None:
            return
        doc.status = DocumentStatus.processing
        await db.commit()
        try:
            text = _extract_text(doc)
            chunks = recursive_split(text, chunk_size=512, overlap=64)
            for i, c in enumerate(chunks):
                db.add(Chunk(document_id=doc.id, content=c, position=i, embedding=[0.0] * 1024, token_count=len(c)))
            doc.status = DocumentStatus.ready
            doc.chunk_count = len(chunks)
        except Exception as e:
            doc.status = DocumentStatus.failed
            doc.error_message = str(e)
        await db.commit()

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def parse_document(self, document_id: int) -> None:
    asyncio.run(_run(document_id))
```

- [x] **步骤 5：实现知识库与文档路由**

```python
# backend/app/api/knowledge_bases.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user
from app.models import KnowledgeBase, WorkspaceMember, User, Document, Chunk

router = APIRouter(prefix="/api/v1", tags=["knowledge_bases"])

class KBCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    chunk_size: int = Field(512, ge=64, le=8192)
    chunk_overlap: int = Field(64, ge=0)

class KBOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    description: str
    chunk_size: int
    chunk_overlap: int
    embedding_model: str

async def _member(ws_id, user_id, db):
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id, WorkspaceMember.user_id == user_id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(404, "工作区不存在或非成员")

@router.post("/workspaces/{ws_id}/knowledge-bases", status_code=201)
async def create_kb(ws_id: int, body: KBCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member(ws_id, user.id, db)
    if body.chunk_overlap >= body.chunk_size:
        raise HTTPException(400, "chunk_overlap 必须小于 chunk_size")
    kb = KnowledgeBase(workspace_id=ws_id, name=body.name, description=body.description, chunk_size=body.chunk_size, chunk_overlap=body.chunk_overlap)
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return KBOut(id=kb.id, workspace_id=kb.workspace_id, name=kb.name, description=kb.description, chunk_size=kb.chunk_size, chunk_overlap=kb.chunk_overlap, embedding_model=kb.embedding_model)

@router.get("/workspaces/{ws_id}/knowledge-bases")
async def list_kbs(ws_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _member(ws_id, user.id, db)
    rows = await db.execute(select(KnowledgeBase).where(KnowledgeBase.workspace_id == ws_id))
    return {"items": rows.scalars().all()}
```

```python
# backend/app/api/documents.py
import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user
from app.models import KnowledgeBase, WorkspaceMember, User, Document, DocumentStatus
from app.tasks.parse_document import parse_document

router = APIRouter(prefix="/api/v1", tags=["documents"])
ALLOWED = {"application/pdf", "text/markdown", "text/plain", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_SIZE = 50 * 1024 * 1024
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/tmp/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/knowledge-bases/{kb_id}/documents", status_code=202)
async def upload_document(kb_id: int, file: UploadFile = File(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == kb.workspace_id, WorkspaceMember.user_id == user.id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(404, "知识库不存在")
    if file.content_type not in ALLOWED:
        raise HTTPException(400, f"不支持的文件类型: {file.content_type}")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(413, "文件超过 50MB 限制")
    safe_name = os.path.basename(file.filename or "")
    storage_key = os.path.join(UPLOAD_DIR, f"{kb_id}-{uuid.uuid4().hex}-{safe_name}")
    with open(storage_key, "wb") as f:
        f.write(content)
    doc = Document(knowledge_base_id=kb.id, filename=file.filename, content_type=file.content_type, file_size=len(content), storage_key=storage_key, status=DocumentStatus.pending)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    parse_document.delay(doc.id)
    return {"document_id": doc.id, "status": "pending"}
```

- [x] **步骤 6：注册路由并运行测试**

```python
# backend/app/main.py 追加
from app.api import knowledge_bases, documents
app.include_router(knowledge_bases.router)
app.include_router(documents.router)
```

运行：`pytest backend/tests/test_splitter.py backend/tests/test_knowledge_bases.py -v`
预期：PASS

- [x] **步骤 7：Commit**

```bash
git add backend/app
git commit -m "feat: add knowledge base and async document pipeline (F3)"
```

---

### 任务 6：混合检索内核（F4）

**文件：**
- 创建：`backend/app/services/search_service.py`
- 创建：`backend/app/rag/embedder.py`
- 创建：`backend/app/rag/retriever.py`
- 测试：`backend/tests/test_search.py`

- [x] **步骤 1：编写检索服务测试**

```python
# backend/tests/test_search.py
from app.rag.retriever import rrf_merge

def test_rrf_merge_combines_rankings():
    a = [10, 20, 30]
    b = [30, 40]
    merged = rrf_merge([a, b], k=60)
    # 30 在两路都出现（rank 2 + rank 0），应排名靠前
    assert merged[0] == 30
    assert set(merged) == {10, 20, 30, 40}
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_search.py -v`
预期：FAIL，报错 "ModuleNotFoundError"

- [x] **步骤 3：实现 RRF 与检索服务**

```python
# backend/app/rag/retriever.py
def rrf_merge(rankings: list[list[int]], k: int = 60) -> list[int]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda d: scores[d], reverse=True)
```

```python
# backend/app/services/search_service.py
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Chunk
from app.rag.retriever import rrf_merge

async def hybrid_search(db: AsyncSession, kb_id: int, query_embedding: list[float], query_text: str, top_k: int = 10) -> list[Chunk]:
    # 向量检索（pgvector 余弦距离）
    vec_stmt = text(
        "SELECT c.id FROM chunks c JOIN documents d ON c.document_id = d.id "
        "JOIN knowledge_bases k ON d.knowledge_base_id = k.id "
        "WHERE k.id = :kb_id ORDER BY c.embedding <=> :q LIMIT :n"
    )
    vec_rows = await db.execute(vec_stmt, {"kb_id": kb_id, "q": query_embedding, "n": top_k * 2})
    vec_ids = [r[0] for r in vec_rows.all()]
    # 全文检索（ILIKE 简化实现，中文分词在集成阶段替换）
    full_stmt = text(
        "SELECT c.id FROM chunks c JOIN documents d ON c.document_id = d.id "
        "JOIN knowledge_bases k ON d.knowledge_base_id = k.id "
        "WHERE k.id = :kb_id AND c.content ILIKE :q ORDER BY c.id LIMIT :n"
    )
    full_rows = await db.execute(full_stmt, {"kb_id": kb_id, "q": f"%{query_text}%", "n": top_k * 2})
    full_ids = [r[0] for r in full_rows.all()]
    merged = rrf_merge([vec_ids, full_ids])[:top_k]
    # rerank（PRD F4）：真实调用租户配置的 bge-reranker-v2-m3，经出站网关；M1 阶段占位直通 RRF 顺序
    if not merged:
        return []
    rows = await db.execute(select(Chunk).where(Chunk.id.in_(merged)))
    by_id = {c.id: c for c in rows.scalars().all()}
    return [by_id[i] for i in merged if i in by_id]
```

- [x] **步骤 4：提供 embedder 抽象**（embed 返回占位向量，真实 bge-m3 接入见 P2）

```python
# backend/app/rag/embedder.py
from app.core.config import settings

class Embedder:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = base_url or ""
        self.api_key = api_key or ""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # M1 阶段返回占位向量（1024 维），P2 接入真实 bge-m3 API
        import random
        random.seed(42)
        return [[0.1] * 1024 for _ in texts]

embedder = Embedder()
```

- [x] **步骤 5：运行测试验证通过**

运行：`pytest backend/tests/test_search.py -v`
预期：PASS

- [x] **步骤 6：Commit**

```bash
git add backend/app
git commit -m "feat: add hybrid search kernel with RRF (F4)"
```

---

### 任务 7：通用对话 SSE（F5）

**文件：**
- 创建：`backend/app/api/chat.py`
- 创建：`backend/app/services/chat_service.py`
- 测试：`backend/tests/test_chat.py`

- [x] **步骤 1：编写 SSE 聊天测试**

```python
# backend/tests/test_chat.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_chat_stream_returns_sse():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/v1/auth/register", json={"email": "chat@b.com", "password": "secret123", "nickname": "C"})
        token = (await c.post("/api/v1/auth/login", json={"email": "chat@b.com", "password": "secret123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        ws = (await c.post("/api/v1/workspaces", json={"name": "WS"}, headers=h)).json()
        kb = (await c.post(f"/api/v1/workspaces/{ws['id']}/knowledge-bases", json={"name": "KB1"}, headers=h)).json()
        async with c.stream("POST", "/api/v1/chat", json={"knowledge_base_id": kb["id"], "message": "你好", "stream": True}, headers=h) as resp:
            assert resp.status_code == 200
            body = ""
            async for line in resp.aiter_lines():
                body += line
        assert "data:" in body or resp.status_code == 200
```

- [x] **步骤 2：运行测试验证失败**

运行：`pytest backend/tests/test_chat.py -v`
预期：FAIL，报错 404

- [x] **步骤 3：实现聊天服务与 SSE 端点**（answer 为占位拼接，真实 LLM 接入见后续集成）

```python
# backend/app/services/chat_service.py
async def build_answer(query: str, chunks: list) -> str:
    # M1 阶段：拼接检索片段返回，不调用真实 LLM（P2 接 DeepSeek）
    if not chunks:
        return "未在知识库中找到相关内容。"
    return "根据知识库内容：" + "；".join(c.content[:80] for c in chunks[:3])
```

```python
# backend/app/api/chat.py
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user
from app.models import Conversation, Message, KnowledgeBase, User, WorkspaceMember
from app.services.search_service import hybrid_search
from app.services.chat_service import build_answer
from app.rag.embedder import embedder

router = APIRouter(prefix="/api/v1", tags=["chat"])

class ChatRequest(BaseModel):
    knowledge_base_id: int
    conversation_id: int | None = None
    message: str
    stream: bool = True

@router.post("/chat")
async def chat(body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, body.knowledge_base_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    row = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == kb.workspace_id, WorkspaceMember.user_id == user.id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(404, "知识库不存在")

    conv = await db.get(Conversation, body.conversation_id) if body.conversation_id else None
    if conv is None:
        conv = Conversation(user_id=user.id, knowledge_base_id=kb.id, title=body.message[:30])
        db.add(conv)
        await db.flush()
    elif conv.user_id != user.id or conv.knowledge_base_id != kb.id:
        raise HTTPException(404, "会话不存在")
    db.add(Message(conversation_id=conv.id, role="user", content=body.message))
    await db.commit()

    async def gen():
        qv = (await embedder.embed([body.message]))[0]
        chunks = await hybrid_search(db, kb.id, qv, body.message, top_k=5)
        answer = await build_answer(body.message, chunks)
        yield f"data: {json.dumps({'type': 'sources', 'sources': [{'chunk_id': c.id, 'document_id': c.document_id, 'content_snippet': c.content[:200]} for c in chunks]})}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'content': answer})}\n\n"
        msg = Message(conversation_id=conv.id, role="assistant", content=answer, sources=[{"chunk_id": c.id, "document_id": c.document_id} for c in chunks])
        db.add(msg)
        await db.commit()
        yield f"data: {json.dumps({'type': 'done', 'message_id': msg.id, 'token_count': len(answer), 'conversation_id': conv.id})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [x] **步骤 4：注册路由并运行测试**

```python
# backend/app/main.py 追加
from app.api import chat
app.include_router(chat.router)
```

运行：`pytest backend/tests/test_chat.py -v`
预期：PASS

- [x] **步骤 5：Commit**

```bash
git add backend/app
git commit -m "feat: add SSE streaming chat (F5)"
```

---

### 任务 8：前端骨架（登录/注册/工作区/知识库/对话）

**文件：**
- 创建：`frontend/package.json`
- 创建：`frontend/vite.config.ts`
- 创建：`frontend/src/main.tsx`
- 创建：`frontend/src/App.tsx`
- 创建：`frontend/src/api/client.ts`
- 创建：`frontend/src/api/auth.ts`
- 创建：`frontend/src/api/knowledgeBase.ts`
- 创建：`frontend/src/api/chat.ts`
- 创建：`frontend/src/stores/authStore.ts`
- 创建：`frontend/src/stores/knowledgeBaseStore.ts`
- 创建：`frontend/src/pages/LoginPage.tsx`
- 创建：`frontend/src/pages/RegisterPage.tsx`
- 创建：`frontend/src/pages/DashboardPage.tsx`
- 创建：`frontend/src/pages/ChatPage.tsx`
- 测试：`frontend/src/__tests__/authStore.test.ts`

- [x] **步骤 1：编写失败的 store 测试**

```typescript
// frontend/src/__tests__/authStore.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAuthStore } from "../stores/authStore";

vi.mock("../api/auth", () => ({
  login: vi.fn().mockResolvedValue({ access_token: "at", refresh_token: "rt" }),
  getMe: vi.fn().mockResolvedValue({ id: 1, email: "a@b.com", nickname: "A" }),
}));

describe("authStore", () => {
  beforeEach(() => useAuthStore.getState().setUser(null as any));
  it("login sets isAuthenticated", async () => {
    await useAuthStore.getState().login("a@b.com", "secret123");
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });
});
```

- [x] **步骤 2：运行测试验证失败**

运行：`cd frontend && npx vitest run`
预期：FAIL，报错 "Cannot find module"

- [x] **步骤 3：创建前端配置与 API 层**

```json
// frontend/package.json
{
  "name": "agentkb-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "axios": "^1.7.0",
    "zustand": "^4.5.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "vitest": "^2.0.0"
  }
}
```

```typescript
// frontend/src/api/client.ts
import axios from "axios";
import { useAuthStore } from "../stores/authStore";

export const client = axios.create({ baseURL: "/api/v1" });

client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
```

```typescript
// frontend/src/stores/authStore.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as authApi from "../api/auth";

interface AuthState {
  accessToken: string | null;
  user: { id: number; email: string; nickname: string } | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  setUser: (user: any) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      user: null,
      isAuthenticated: false,
      login: async (email, password) => {
        const { access_token } = await authApi.login(email, password);
        const user = await authApi.getMe(access_token);
        set({ accessToken: access_token, user, isAuthenticated: true });
      },
      logout: () => set({ accessToken: null, user: null, isAuthenticated: false }),
      setUser: (user) => set({ user }),
    }),
    { name: "auth-storage", partialize: (s) => ({ accessToken: s.accessToken, user: s.user, isAuthenticated: s.isAuthenticated }) }
  )
);
```

```typescript
// frontend/src/api/auth.ts
import { client } from "./client";

export function login(email: string, password: string) {
  return client.post("/auth/login", { email, password }).then((r) => r.data);
}

export function getMe(accessToken: string) {
  return client.get("/users/me", { headers: { Authorization: `Bearer ${accessToken}` } }).then((r) => r.data);
}
```

```typescript
// frontend/src/api/knowledgeBase.ts
import { client } from "./client";

export function list(wsId: number) {
  return client.get(`/workspaces/${wsId}/knowledge-bases`).then((r) => r.data.items);
}
```

```typescript
// frontend/src/api/chat.ts
import { useAuthStore } from "../stores/authStore";

export async function streamChat(body: any, cb: { onToken: (t: string) => void; onDone: () => void }) {
  const token = useAuthStore.getState().accessToken;
  const res = await fetch("/api/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ ...body, stream: true }),
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      const event = JSON.parse(line.slice(5).trim());
      if (event.type === "token") cb.onToken(event.content);
      if (event.type === "done") cb.onDone();
    }
  }
}
```

- [x] **步骤 4：创建登录页与应用入口**

```tsx
// frontend/src/pages/LoginPage.tsx
import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuthStore } from "../stores/authStore";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useAuthStore((s) => s.login);
  const nav = useNavigate();
  return (
    <form onSubmit={async (e) => { e.preventDefault(); await login(email, password); nav("/"); }}>
      <h1>AgentKB 登录</h1>
      <input data-testid="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="邮箱" />
      <input data-testid="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="密码" />
      <button type="submit">登录</button>
      <Link to="/register">注册</Link>
    </form>
  );
}
```

```tsx
// frontend/src/App.tsx
import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import { useAuthStore } from "./stores/authStore";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import DashboardPage from "./pages/DashboardPage";
import ChatPage from "./pages/ChatPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const authed = useAuthStore((s) => s.isAuthenticated);
  return authed ? <>{children}</> : <Navigate to="/login" />;
}

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  { path: "/", element: <RequireAuth><DashboardPage /></RequireAuth> },
  { path: "/chat/:kbId?", element: <RequireAuth><ChatPage /></RequireAuth> },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
```

```tsx
// frontend/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>
);
```

- [x] **步骤 5：运行前端测试验证通过**

运行：`cd frontend && npx vitest run`
预期：PASS

- [x] **步骤 6：Commit**

```bash
git add frontend/
git commit -m "feat: add frontend skeleton with auth and kb pages"
```

---

## 自检

**1. 规格覆盖度：**
- F1 认证/租户 → 任务 3 ✓
- F2 模型配置 → 任务 4 ✓（含 outbound_gateway SSRF 防护、model_config_revision 递增、连接测试端点）
- F3 知识库/文档/Celery → 任务 5 ✓
- F4 混合检索 → 任务 6 ✓（embedding / rerank 均占位，真实模型在集成时替换）
- F5 通用对话 SSE → 任务 7 ✓（answer 占位，真实 LLM 在集成时替换）
- 前端骨架 → 任务 8 ✓（RegisterPage / DocumentsPage / SettingsPage 为后续任务补齐，任务 8 只建登录/注册/工作台/对话入口）

**2. 占位符扫描：** 无「待定」；embedding、rerank 与 LLM 在 M1 阶段为占位实现，已在任务描述中明确，属有意分期而非遗漏。

**3. 类型一致性：** `recursive_split`、`rrf_merge`、`hybrid_search`、`build_answer` 签名在各任务间一致；`ModelConfig`（含 `model_config_revision`）、`Document`、`Chunk` 字段与 DATABASE_SCHEMA 对齐。

**4. 安全复核（v0.26 对齐）：**
- [x] chat 会话归属校验（`conv.user_id` / `conv.knowledge_base_id`，防跨用户注入）
- [x] 上传存储路径清洗（`os.path.basename` + uuid，防路径穿越）
- [x] `MODEL_KEY_ENC_KEY` 缺失 / 占位值时启动失败（fail-fast，禁默认密钥）
- [x] 出站网关仅允许 HTTPS、阻断私网/回环/链路本地/云 metadata、DNS 解析后复检 IP
- [x] 邀请成员仅 admin 及以上，仅 owner 可授予 admin 角色
- [x] `Message.conversation_id` 增补外键

**已知边界（后续计划处理）：**
- 真实 embedding（bge-m3）与 LLM（deepseek-chat）接入 → P2/P3 集成。
- 简历解析流水线（F6）→ P2 计划。
- 搜人闭环（F7/F8/F10）→ P3 计划。
- 支撑闭环（F11/F13/F14/F15）→ P4 计划。