# 数据库设计文档（DATABASE_SCHEMA）

> 项目：MaxKB Replica —— 多租户 RAG 知识库平台
> 数据库：PostgreSQL 16 + pgvector 扩展
> ORM：SQLAlchemy 2.0（async，`Mapped` / `mapped_column` 风格）
> 迁移工具：Alembic
> API Base URL：`/api/v1`

本文档覆盖：ER 图、完整表设计、索引策略、迁移顺序、关键查询示例、多租户隔离策略。

---

## 1. ER 图（ASCII art）

```
┌──────────────────┐          ┌──────────────────────┐
│      users       │          │     workspaces       │
├──────────────────┤          ├──────────────────────┤
│ PK id            │◄────┐    │ PK id                │
│    email (UQ)    │     │    │    name              │
│    hashed_password│    │    │ FK owner_id ─────────┼──┐
│    nickname      │     │    │    created_at        │  │
│    is_active     │     │    │ UQ(owner,name)       │  │
│    is_superuser  │     │    └──────────┬───────────┘  │
│    created_at    │     │               │              │
│    updated_at    │     │               │ 1:N          │
└──────┬───────────┘     │               ▼              │
       │                 │    ┌──────────────────────┐  │
       │ 1:N             │    │  workspace_members   │  │
       │                 │    ├──────────────────────┤  │
       │                 └────┤ FK user_id           │  │
       │                      │ PK id                │  │
       │                      │ FK workspace_id ─────┼──┤ (指向上方 workspaces)
       │                      │    role (enum)       │  │
       │                      │    joined_at         │  │
       │                      │ UQ(workspace,user)   │  │
       │                      └──────────────────────┘  │
       │                                                │
       │◄───────────────────────────────────────────────┘
       │
       ├────────────────────────────────────────────────────────┐
       │ 1:N                                                    │
       ▼                                                        │
┌──────────────────────┐   1:N    ┌──────────────────────┐      │
│   knowledge_bases    │◄─────────┤     documents        │      │
├──────────────────────┤          ├──────────────────────┤      │
│ PK id                │          │ PK id                │      │
│ FK workspace_id      │          │ FK knowledge_base_id │      │
│    name              │          │    filename          │      │
│    description       │          │    content_type      │      │
│    embedding_model   │          │    file_size         │      │
│    chunk_size        │          │    storage_key       │      │
│    chunk_overlap     │          │    status (enum)     │      │
│    created_at        │          │    chunk_count       │      │
│    updated_at        │          │    error_message     │      │
│ UQ(workspace,name)   │          │    created_at        │      │
│                      │          │    updated_at        │      │
└──────┬───────────────┘          └──────────┬───────────┘      │
       │                                     │ 1:N              │
       │                                     ▼                  │
       │                          ┌──────────────────────┐      │
       │                          │       chunks         │      │
       │                          ├──────────────────────┤      │
       │                          │ PK id                │      │
       │                          │ FK document_id       │      │
       │                          │    content (text)    │      │
       │                          │    position          │      │
       │                          │    embedding         │      │
       │                          │      vector(1024)    │      │
       │                          │    metadata (jsonb)  │      │
       │                          │    token_count       │      │
       │                          │    created_at        │      │
       │                          │ HNSW(embedding)      │      │
       │                          └──────────────────────┘      │
       │                                                        │
       │ 1:N                                                    │
       ▼                                                        │
┌──────────────────────┐   1:N    ┌──────────────────────┐      │
│    conversations     │◄─────────┤      messages        │      │
├──────────────────────┤          ├──────────────────────┤      │
│ PK id                │          │ PK id                │      │
│ FK user_id ──────────┼──────────┼──────────────────────┼──────┤ (users)
│ FK knowledge_base_id │          │ FK conversation_id   │      │
│    title             │          │    role (enum)       │      │
│    system_prompt     │          │    content (text)    │      │
│    created_at        │          │    sources (jsonb)   │      │
│    updated_at        │          │    token_count       │      │
└──────────────────────┘          │    created_at        │      │
                                  └──────────────────────┘      │
                                                                │
┌──────────────────────┐          ┌──────────────────────┐      │
│     token_usage      │          │      api_keys        │      │
├──────────────────────┤          ├──────────────────────┤      │
│ PK id                │          │ PK id                │      │
│ FK user_id ──────────┼──────────┼──────────────────────┼──────┘ (users)
│ FK workspace_id      │          │ FK user_id           │
│    tokens_in         │          │    name              │
│    tokens_out        │          │    hashed_key (UQ)   │
│    model             │          │    prefix (varchar8) │
│    cost_usd          │          │    expires_at        │
│    created_at        │          │    created_at        │
└──────────────────────┘          │    last_used_at      │
                                  └──────────────────────┘
```

**关系汇总：**

| 关系 | 基数 | 说明 |
|---|---|---|
| users → workspaces (owner) | 1:N | 一个用户可拥有多个工作空间 |
| users ↔ workspaces（经 workspace_members） | M:N | 多对多，带角色属性 |
| workspaces → knowledge_bases | 1:N | 知识库归属于工作空间（租户隔离核心） |
| knowledge_bases → documents | 1:N | 一个知识库包含多个文档 |
| documents → chunks | 1:N | 一个文档切分为多个分片 |
| users → conversations | 1:N | 用户发起多个对话 |
| knowledge_bases → conversations | 1:N | 对话绑定到某个知识库 |
| conversations → messages | 1:N | 一个对话包含多条消息 |
| users → token_usage | 1:N | 按用户记录用量 |
| workspaces → token_usage | 1:N | 按工作空间聚合计费 |
| users → api_keys | 1:N | 一个用户可创建多个 API Key |

---

## 2. 完整表设计

### 公共基础设施

所有模型共享的基类与命名约定：

```python
# app/db/base.py
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 统一命名约定，方便 Alembic 自动生成稳定的约束名
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
    """created_at / updated_at 统一由数据库默认值生成，避免应用层遗漏。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        onupdate=utcnow,
        nullable=False,
    )
```

**设计决策：**

1. **主键统一使用 int64 自增**（`BigInteger` + `primary_key=True, autoincrement=True`，PostgreSQL 侧为 BIGSERIAL/IDENTITY）。
   - 8 字节紧凑、B-tree 顺序插入，写入性能与索引局部性优于 UUID；外键 join 代价更低。
   - ID 可枚举不构成安全问题：`/api/v1` 下所有资源接口都强制鉴权 + 租户归属校验（见第 6 节），安全不依赖 ID 不可猜。
2. **时间戳使用 `server_default="now()"`** 而非 Python 端 `default=`，保证即使绕过 ORM 直接写 SQL 也有值；列类型显式使用 `DateTime(timezone=True)`（timestamptz），应用层兜底一律 `datetime.now(timezone.utc)`（禁用已弃用的 `datetime.utcnow()`）。
3. **命名约定（naming_convention）**：Alembic autogenerate 依赖稳定的约束名，否则每次生成的迁移文件名和约束名都随机。

---

### 2.1 users —— 用户表

```python
# app/models/user.py
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    # 关系（仅声明，按需 lazy="selectin"）
    owned_workspaces = relationship("Workspace", back_populates="owner")
    memberships = relationship(
        "WorkspaceMember", back_populates="user", passive_deletes=True
    )
    api_keys = relationship("APIKey", back_populates="user", passive_deletes=True)
```

**索引：**

| 索引 | 列 | 原因 |
|---|---|---|
| `uq_users_email`（唯一） | `email` | 登录查询 `WHERE email = ?` 是最高频路径；唯一性由数据库保证而非应用层 |

**约束：**

- `UNIQUE (email)`：邮箱即登录名。
- `CHECK (char_length(hashed_password) > 0)`（可选）：防止空密码哈希写入。

**设计决策：**

- **只存 `hashed_password`，绝不存明文**。使用 `passlib[bcrypt]` 或 `argon2-cffi`，哈希结果自带 salt，长度可达 60~100 字符，故给 255。
- `is_active` 用于软禁用（封禁/离职），比物理删除安全——该用户的历史消息、用量记录仍保持外键完整。
- `is_superuser` 标记平台级超级管理员（跨租户运维/调试），与 workspace 内的角色体系正交，默认 `False`。
- `nickname` / `is_active` 使用 `server_default` 而非 `default`：与迁移定义保持一致，绕过 ORM 直接写入时也有默认值。
- 不在此表放 `workspace_id`：用户与工作空间是 M:N 关系，通过 `workspace_members` 连接。

---

### 2.2 workspaces —— 工作空间（租户）表

```python
# app/models/workspace.py
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_workspace_owner_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )

    owner = relationship("User", back_populates="owned_workspaces")
    members = relationship(
        "WorkspaceMember", back_populates="workspace", passive_deletes=True
    )
    knowledge_bases = relationship(
        "KnowledgeBase", back_populates="workspace", passive_deletes=True
    )
```

**索引：**

| 索引 | 列 | 原因 |
|---|---|---|
| `ix_workspaces_owner_id` | `owner_id` | "列出我拥有的工作空间"；外键列建索引可避免级联操作时的锁升级 |
| `uq_workspace_owner_name`（唯一） | `(owner_id, name)` | 同一拥有者下工作空间不允许重名，防止误建重复空间 |

**约束：**

- `FK owner_id → users.id, ON DELETE RESTRICT`：拥有者账号存在时禁止删除工作空间归属链；删除用户前必须先转移 ownership。
- `UNIQUE (owner_id, name)`：同一拥有者下空间名唯一。

**设计决策：**

- **workspace 即租户边界**。后续所有业务表（knowledge_bases、token_usage 等）都带 `workspace_id`，这是多租户隔离的锚点。
- `owner_id` 与 `workspace_members` 中的 `role='owner'` 语义重复，但保留冗余字段的原因：owner 转移、删除保护等管理操作需要 O(1) 定位，不必每次 join 成员表。创建 workspace 时在同一事务内写入两条记录（workspace + 一条 role='owner' 的 member），保证一致性。

---

### 2.3 workspace_members —— 成员关系表

```python
# app/models/workspace_member.py
import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WorkspaceRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_member_workspace_user"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=WorkspaceRole.member,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="memberships")
```

**索引：**

| 索引 | 列 | 原因 |
|---|---|---|
| `uq_member_workspace_user`（唯一） | `(workspace_id, user_id)` | 同一用户在同一空间只能有一条记录；该唯一约束本身是 B-tree，同时覆盖"列出某空间全部成员"（按 workspace_id 前缀扫描） |
| `ix_workspace_members_user_id` | `user_id` | "列出我加入的所有空间"——唯一约束的前缀是 workspace_id，无法服务按 user_id 的查询 |

**约束：**

- `UNIQUE (workspace_id, user_id)`：防止重复加入。
- 两个 FK 均 `ON DELETE CASCADE`：删空间则成员关系消失；删用户则其成员关系消失。

**设计决策：**

- 角色用 **PostgreSQL 原生 enum** 而非 varchar + check：存储更紧凑（4 字节 OID），且类型安全。代价是新增枚举值需要 `ALTER TYPE ... ADD VALUE`（Alembic 支持 `op.execute`）。若预期角色会频繁扩展，可退回 `VARCHAR(16) + CHECK`。
- 保留独立 `id` 主键而非用复合主键：方便 REST 风格 API（`/api/v1/members/{id}`）与审计日志引用。

---

### 2.4 knowledge_bases —— 知识库表

```python
# app/models/knowledge_base.py
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_kb_workspace_name"),
        CheckConstraint("chunk_size BETWEEN 64 AND 8192", name="ck_chunk_size_range"),
        CheckConstraint(
            "chunk_overlap >= 0 AND chunk_overlap < chunk_size",
            name="ck_overlap_lt_size",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding_model: Mapped[str] = mapped_column(
        String(128), nullable=False, default="bge-m3"
    )
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=128)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    workspace = relationship("Workspace", back_populates="knowledge_bases")
    documents = relationship(
        "Document",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    conversations = relationship(
        "Conversation", back_populates="knowledge_base", passive_deletes=True
    )
```

**索引：**

| 索引 | 列 | 原因 |
|---|---|---|
| `uq_kb_workspace_name`（唯一） | `(workspace_id, name)` | 同一租户内知识库名称唯一；前缀 workspace_id 同时服务"列出本空间知识库"的高频查询 |

**约束：**

- `CHECK (chunk_size BETWEEN 64 AND 8192)`：防止误配置导致切分爆炸或单 chunk 超出 embedding 模型上下文。
- `CHECK (chunk_overlap < chunk_size)`：overlap 必须小于 chunk 本身，否则切分死循环。
- FK `ON DELETE CASCADE`：删空间则级联删除知识库及其全部文档/分片。

**设计决策：**

- **`embedding_model`、`chunk_size`、`chunk_overlap` 放在知识库级别**而非文档级别：同一知识库内所有文档必须使用同一 embedding 模型，否则向量空间不一致，检索结果无意义。这是 RAG 系统的硬约束，放在 schema 层强制。
- `embedding_model` 默认 `bge-m3`（1024 维），与 `chunks.embedding` 的维度约定一致。
- `description` 允许空字符串但不允许 NULL：减少应用层 `None` 分支判断。

---

### 2.5 documents —— 文档表

```python
# app/models/document.py
import enum
from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class DocumentStatus(str, enum.Enum):
    pending = "pending"        # 已上传，等待进入切分队列
    processing = "processing"  # 正在解析/切分/embedding
    ready = "ready"            # 全部 chunk 入库完成，可检索
    failed = "failed"          # 处理失败，见 error_message


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=DocumentStatus.pending,
        index=True,
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
```

**索引：**

| 索引 | 列 | 原因 |
|---|---|---|
| `ix_documents_knowledge_base_id` | `knowledge_base_id` | "列出知识库下所有文档"；FK 列建索引避免级联删除锁升级 |
| `ix_documents_status` | `status` | 后台 worker 轮询 `WHERE status IN ('pending','processing')` 拉取待处理任务 |

**约束：**

- `CHECK (file_size >= 0)`（可选）。
- FK `ON DELETE CASCADE`：删知识库连带删除文档及其 chunks。

**设计决策：**

- **状态机放在数据库**（enum）而非仅应用层：worker 崩溃后可通过 `status='processing' AND updated_at < now() - interval '10 min'` 找回僵死任务。
- `error_message` 只在 `status='failed'` 时有值，故允许 NULL。
- `chunk_count` 冗余存储：列表页展示文档分片数无需 `COUNT(*)` 扫 chunks 表（chunks 是全库最大的表）。
- 不存文件二进制：原始文件放对象存储（MinIO/S3），本表只存元数据，`storage_key` 记录对象存储路径。

---

### 2.6 chunks —— 分片 + 向量表（核心）

```python
# app/models/chunk.py
from datetime import datetime

from sqlalchemy import BigInteger, Computed, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base

EMBEDDING_DIM = 1024  # 默认 embedding 模型 bge-m3 的输出维度


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        # HNSW 向量索引，余弦距离
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # 全文检索列的 GIN 索引（hybrid search 用）
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        # (document_id, position) 唯一：重建文档分片时防重复
        Index("uq_chunks_document_position", "document_id", "position", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )

    # 由 content 自动维护的 tsvector 生成列（hybrid search 的 BM25 侧）
    content_tsv = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', content)", persisted=True),
        nullable=False,
    )

    document = relationship("Document", back_populates="chunks")
```

> 说明：`TSVECTOR` 来自 `sqlalchemy.dialects.postgresql`，`Computed` 来自 `sqlalchemy`。`'simple'` 分词配置对中文需配合 zhparser/pg_jieba 插件，未安装时用 `simple` 保底。生成列由数据库自动维护，写入 `content` 时 `content_tsv` 自动更新。

**索引：**

| 索引 | 类型 | 列 | 原因 |
|---|---|---|---|
| `ix_chunks_embedding_hnsw` | HNSW | `embedding` | 向量近似最近邻检索，余弦距离 |
| `ix_chunks_content_tsv` | GIN | `content_tsv` | BM25/全文检索侧，hybrid search 必需 |
| `uq_chunks_document_position` | B-tree（唯一） | `(document_id, position)` | 防止同一文档重复写入相同序号分片；支持"按文档顺序读取分片" |

**约束：**

- `CHECK (position >= 0)`（可选）。
- FK `ON DELETE CASCADE`：删文档连带删分片。

**设计决策：**

- **`metadata` 用 JSONB**：不同文档类型的元数据差异大（PDF 有页码、网页有 URL、表格有 sheet 名），JSONB 避免频繁 DDL；需要过滤的键可后续单独建 GIN 表达式索引。
- **`embedding` 维度固定 1024**：默认模型 `bge-m3` 输出 1024 维；维度由 `knowledge_bases.embedding_model` 决定，换模型 = 新建知识库。pgvector 的 `vector(n)` 维度是类型的一部分，混维度无法建统一索引。
- `token_count` 冗余：用于检索时按上下文窗口预算截断（如凑满 8k token 即停）。
- chunk 表**不直接挂 `workspace_id`**：检索路径是 `workspace → knowledge_base → chunks`，隔离过滤通过 join knowledge_bases 完成；在 chunks 上冗余 workspace_id 可换取检索时免 join，代价是写入/一致性维护成本。本项目选择 join 方案（chunks 是最大表，保持窄行）。

---

### 2.7 conversations —— 对话表

```python
# app/models/conversation.py
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", text("updated_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_base_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="新对话")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    user = relationship("User")
    knowledge_base = relationship("KnowledgeBase", back_populates="conversations")
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )
```

**索引：**

| 索引 | 列 | 原因 |
|---|---|---|
| `ix_conversations_user_updated`（复合） | `(user_id, updated_at DESC)` | 覆盖"我的对话按最近活跃排序"这一最高频查询；最左前缀同时服务按 user_id 的等值查询，无需单独的 user_id 索引 |
| `ix_conversations_knowledge_base_id` | `knowledge_base_id` | 删除知识库前列出其关联对话 |

**约束：**

- 两个 FK 均 `ON DELETE CASCADE`。

**设计决策：**

- `system_prompt` 存在对话级别：允许用户为每个对话定制人设/指令，发送时拼接为 messages 的首条 system 消息之外的模板。
- 对话不挂 `workspace_id`：对话归属于**用户**而非租户（个人问答历史）。若产品要求团队共享对话，可加 `workspace_id` 列。

---

### 2.8 messages —— 消息表

```python
# app/models/message.py
import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )

    conversation = relationship("Conversation", back_populates="messages")
```

`sources` 的 JSONB 结构约定（assistant 消息引用命中的 chunk，字段与 API_SPEC 对齐）：

```json
[
  {
    "chunk_id": 8612,
    "document_id": 204,
    "filename": "产品手册.pdf",
    "score": 0.87,
    "content_snippet": "……前 200 字……"
  }
]
```

**索引：**

| 索引 | 列 | 原因 |
|---|---|---|
| `ix_messages_conversation_created`（复合） | `(conversation_id, created_at)` | "加载某对话的消息并按时间排序"——唯一高频查询，一个复合索引全覆盖 |

**约束：**

- FK `ON DELETE CASCADE`：删对话连带删消息。

**设计决策：**

- **只建一个复合索引**：messages 是写多读多的热表，索引越多写入越慢；除"按对话拉消息"外不存在其他访问路径（不做全局消息搜索）。
- `sources` 用 JSONB 而非建 `message_sources` 关联表：引用信息是**快照**——即使原 chunk 后来被删除，历史消息仍应能展示当时的引用；外键关联反而会因级联删除破坏历史。
- 无 `updated_at`：消息不可变（immutable），编辑 = 删除后重发。

---

### 2.9 token_usage —— 用量计费表

```python
# app/models/token_usage.py
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TokenUsage(Base):
    __tablename__ = "token_usage"
    __table_args__ = (
        Index("ix_token_usage_user_created", "user_id", "created_at"),
        Index("ix_token_usage_workspace_created", "workspace_id", "created_at"),
        CheckConstraint(
            "tokens_in >= 0 AND tokens_out >= 0",
            name="ck_token_usage_tokens_nonneg",
        ),
        CheckConstraint("cost_usd >= 0", name="ck_token_usage_cost_nonneg"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
```

**索引：**

| 索引 | 列 | 原因 |
|---|---|---|
| `ix_token_usage_user_created`（复合） | `(user_id, created_at)` | "某用户本月用量"聚合 |
| `ix_token_usage_workspace_created`（复合） | `(workspace_id, created_at)` | "某空间本月账单"聚合 |

**约束：**

- `CHECK (tokens_in >= 0 AND tokens_out >= 0)`。
- `CHECK (cost_usd >= 0)`。

**设计决策：**

- **append-only 流水表**，永不 UPDATE：每次 LLM 调用插入一行。聚合靠 `SUM() ... GROUP BY` + 时间范围索引扫描。
- `cost_usd` 用 `Numeric(12,6)` 而非 float：货币计算必须精确；6 位小数足够表达单条调用的微小成本。
- 数据量大后按月分区（`PARTITION BY RANGE (created_at)`）或定期归档，schema 不变。

---

### 2.10 api_keys —— API 密钥表

```python
# app/models/api_key.py
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    hashed_key: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", back_populates="api_keys")
```

**索引：**

| 索引 | 列 | 原因 |
|---|---|---|
| `uq_api_keys_hashed_key`（唯一） | `hashed_key` | 请求鉴权时用 key 的哈希做等值查找，O(log n) |
| `ix_api_keys_user_id` | `user_id` | "列出我的 API Key" |

**约束：**

- `UNIQUE (hashed_key)`：防碰撞（理论上 sha256 不会撞，唯一约束是最后防线）。
- FK `ON DELETE CASCADE`：删用户连带吊销其全部 key。

**设计决策：**

- **数据库只存 `hashed_key`（SHA-256），明文只在创建时返回一次**。即使数据库泄露，攻击者也无法还原可用密钥。
- `prefix`（如 `sk-a3b9`）明文存储：用于管理界面展示"这是哪把 key"，无需解密/还原。
- `expires_at` 允许 NULL 表示永不过期；鉴权时 `WHERE expires_at IS NULL OR expires_at > now()`。
- `last_used_at` 每次鉴权成功后异步更新（可容忍分钟级延迟，避免每请求一次 UPDATE 热点行）。

---

## 3. 索引策略

### 3.1 总原则

1. **先跑起来，再加索引**。Alembic 加索引是 `CREATE INDEX CONCURRENTLY` 一条语句的事，过早加索引只会拖慢写入、膨胀存储。
2. **每个索引必须对应一个真实查询**。没有查询支撑的索引是纯负债。
3. **外键列默认建索引**：PostgreSQL 不会自动为 FK 建索引；缺失时级联删除/更新会全表扫描子表并持有锁。
4. **复合索引遵循最左前缀**：把等值条件列放前面，范围/排序列放后面。

### 3.2 各表索引清单与理由

| 表 | 索引 | 类型 | 服务的查询 |
|---|---|---|---|
| users | `uq_users_email` | B-tree 唯一 | 登录 |
| workspaces | `ix_workspaces_owner_id` | B-tree | 我的空间列表 |
| workspaces | `uq_workspace_owner_name` | B-tree 唯一 | 同一 owner 下空间名去重 |
| workspace_members | `uq_member_workspace_user` | B-tree 唯一 | 成员列表 / 去重 |
| workspace_members | `ix_..._user_id` | B-tree | 我加入的空间 |
| knowledge_bases | `uq_kb_workspace_name` | B-tree 唯一 | 空间内知识库列表 / 去重 |
| documents | `ix_documents_knowledge_base_id` | B-tree | 知识库文档列表 |
| documents | `ix_documents_status` | B-tree | worker 拉取待处理任务 |
| chunks | `ix_chunks_embedding_hnsw` | HNSW | 向量检索 |
| chunks | `ix_chunks_content_tsv` | GIN | 全文检索 |
| chunks | `uq_chunks_document_position` | B-tree 唯一 | 防重复 / 顺序读取 |
| conversations | `ix_conversations_user_updated` | B-tree 复合 | 对话列表按活跃排序 |
| messages | `ix_messages_conversation_created` | B-tree 复合 | 对话消息加载 |
| token_usage | `ix_token_usage_user_created` | B-tree 复合 | 用户用量聚合 |
| token_usage | `ix_token_usage_workspace_created` | B-tree 复合 | 空间账单聚合 |
| api_keys | `uq_api_keys_hashed_key` | B-tree 唯一 | 密钥鉴权查找 |

### 3.3 HNSW 向量索引

```sql
CREATE INDEX ix_chunks_embedding_hnsw
ON chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

**参数解释：**

| 参数 | 取值 | 含义 |
|---|---|---|
| `m` | 16 | 每个节点的最大邻居连接数。越大召回越好、内存与构建时间越高。16 是 pgvector 默认值，对百万级以下数据足够 |
| `ef_construction` | 64 | 建索引时的候选队列宽度。越大索引质量越高、构建越慢。64 为默认平衡值 |
| `ef_search`（查询参数） | 建议 40~100 | 查询时的候选宽度：`SET hnsw.ef_search = 60;` 越大越准、越慢 |

**为什么选 HNSW 而不是 IVFFlat：**

- HNSW 召回率更高、查询更快，且**不需要预先训练聚类中心**（IVFFlat 需要 `CREATE INDEX ... WITH (lists = ...)` 且数据分布变化后需重建）。
- HNSW 支持增量插入；IVFFlat 插入新数据后质量逐渐退化。
- 代价：HNSW 构建更慢、内存占用更高。本系统 chunks 规模（<500 万）完全可承受。

**距离函数选择余弦（`vector_cosine_ops`）**：文本 embedding 模型（bge-m3 等）输出已归一化或应归一化使用，余弦距离对向量模长不敏感，是文本语义检索的标准选择。注意：查询时必须用 `<=>` 操作符（`ORDER BY embedding <=> $1`）才会命中该索引。

**构建注意事项：**

- 大表上建 HNSW 用 `CREATE INDEX CONCURRENTLY` 避免长时间锁写（Alembic 中需 `op.execute` + `connection.execution_options(isolation_level="AUTOCOMMIT")`）。
- `m`、`ef_construction` 一旦建好不可修改，改参数 = 重建索引。

### 3.4 何时新增索引

出现以下信号时再动手：

1. `EXPLAIN ANALYZE` 显示 Seq Scan 且该查询在 p95 延迟中占比显著；
2. 某列反复出现在 `WHERE` 等值/范围条件且表已超过 ~10 万行；
3. 排序查询（`ORDER BY ... LIMIT`）出现 filesort（Sort 节点且 `Sort Method: external merge`）。

加索引流程：生产环境一律 `CREATE INDEX CONCURRENTLY`；加完用 `pg_stat_user_indexes.idx_scan` 观察一个月，`idx_scan = 0` 的索引考虑移除。

---

## 4. 迁移顺序（Alembic）

依赖链决定顺序：**被依赖的表先建**。

```
users ──┬──> workspaces ──> workspace_members
        │         │
        │         └──> knowledge_bases ──> documents ──> chunks
        │
        ├──> conversations ──> messages
        │        (依赖 users + knowledge_bases)
        ├──> token_usage (依赖 users + workspaces)
        └──> api_keys
```

| 序号 | 迁移文件 | 内容 | 依赖 |
|---|---|---|---|
| 1 | `0001_create_users.py` | users 表 | 无 |
| 2 | `0002_create_workspaces.py` | workspaces + workspace_members + role enum | users |
| 3 | `0003_create_knowledge_bases.py` | knowledge_bases | workspaces |
| 4 | `0004_create_documents.py` | documents + status enum | knowledge_bases |
| 5 | `0005_create_chunks.py` | `CREATE EXTENSION vector` + chunks + HNSW/GIN 索引 | documents |
| 6 | `0006_create_conversations.py` | conversations + messages + role enum | users, knowledge_bases |
| 7 | `0007_create_token_usage.py` | token_usage | users, workspaces |
| 8 | `0008_create_api_keys.py` | api_keys | users |

### 迁移 1：users

```python
"""create users

Revision ID: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("nickname", sa.String(64), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )


def downgrade() -> None:
    op.drop_table("users")
```

### 迁移 2：workspaces + workspace_members

```python
"""create workspaces and members

Revision ID: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"

workspace_role = sa.Enum("owner", "admin", "member", name="workspace_role")


def upgrade() -> None:
    workspace_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_workspaces_owner_id_users"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("owner_id", "name", name="uq_workspace_owner_name"),
    )
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])

    op.create_table(
        "workspace_members",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE", name="fk_workspace_members_workspace_id_workspaces"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_workspace_members_user_id_users"),
            nullable=False,
        ),
        sa.Column("role", workspace_role, nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_member_workspace_user"),
    )
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])


def downgrade() -> None:
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    workspace_role.drop(op.get_bind(), checkfirst=True)
```

### 迁移 5：chunks（含 pgvector 扩展）—— 最关键的迁移

```python
"""create chunks with pgvector

Revision ID: 0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    # pgvector 扩展（需要超级用户或预先安装）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("documents.id", ondelete="CASCADE", name="fk_chunks_document_id_documents"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        # 生成列：自动维护全文检索向量
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', content)", persisted=True),
            nullable=False,
        ),
        sa.UniqueConstraint("document_id", "position", name="uq_chunks_document_position"),
    )

    # GIN 全文索引（普通方式即可，数据量小）
    op.create_index(
        "ix_chunks_content_tsv",
        "chunks",
        ["content_tsv"],
        postgresql_using="gin",
    )

    # HNSW 索引：大表上应 CONCURRENTLY；初始建库数据为空，直接建即可
    op.execute(
        """
        CREATE INDEX ix_chunks_embedding_hnsw
        ON chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.drop_table("chunks")
    # 不 DROP EXTENSION：其他库/表可能依赖
```

> 生产环境数据量大时重建 HNSW 索引的写法：

```python
def upgrade() -> None:
    conn = op.get_bind()
    conn.execution_options(isolation_level="AUTOCOMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
```

其余迁移（3、4、6、7、8）结构与上述一致，按第 2 节各表的列/约束/索引逐一 `op.create_table` + `op.create_index`，此处不重复展开。

**回滚原则：** 每个迁移的 `downgrade()` 按依赖逆序 `drop_table`；enum 类型在最后一个使用者的 downgrade 中 `drop`。

---

## 5. 关键查询示例

以下示例使用 SQLAlchemy 2.0 async 风格（`AsyncSession`）。

### 5.1 向量相似度检索（余弦距离）

```python
from sqlalchemy import select
from app.models.chunk import Chunk
from app.models.knowledge_base import KnowledgeBase
from app.models.document import Document, DocumentStatus


async def vector_search(
    session,
    workspace_id: int,
    knowledge_base_id: int,
    query_embedding: list[float],
    top_k: int = 5,
):
    """在指定知识库内做向量检索，返回 top_k 个最相似 chunk。"""
    stmt = (
        select(
            Chunk.id,
            Chunk.content,
            Chunk.metadata_,
            Document.filename,
            # 余弦距离：0 完全相同，2 完全相反；相似度 = 1 - distance
            (1 - Chunk.embedding.cosine_distance(query_embedding)).label("score"),
        )
        .join(Document, Chunk.document_id == Document.id)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.workspace_id == workspace_id,  # 租户隔离
            Document.status == DocumentStatus.ready,
        )
        .order_by(Chunk.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )
    result = await session.execute(stmt)
    return result.all()
```

生成的 SQL 核心：

```sql
SELECT c.id, c.content, c.metadata, d.filename,
       1 - (c.embedding <=> :query_vec) AS score
FROM chunks c
JOIN documents d      ON c.document_id = d.id
JOIN knowledge_bases kb ON d.knowledge_base_id = kb.id
WHERE kb.id = :kb_id
  AND kb.workspace_id = :ws_id
  AND d.status = 'ready'
ORDER BY c.embedding <=> :query_vec
LIMIT 5;
```

> 注意：`<=>` 是余弦距离操作符，`ORDER BY embedding <=> $1` 才能走 HNSW 索引。可在会话级调召回：`SET LOCAL hnsw.ef_search = 60;`

### 5.2 混合检索（向量 + BM25 全文）

```python
import sqlalchemy as sa
from sqlalchemy import select

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase


async def hybrid_search(
    session,
    workspace_id: int,
    knowledge_base_id: int,
    query_text: str,
    query_embedding: list[float],
    top_k: int = 5,
    vector_weight: float = 0.7,
):
    """RRF（Reciprocal Rank Fusion）融合向量与全文两路结果。"""
    tsv_query = " | ".join(query_text.split())  # 生产环境应做分词

    vector_leg = (
        select(
            Chunk.id.label("chunk_id"),
            sa.func.row_number()
              .over(order_by=Chunk.embedding.cosine_distance(query_embedding))
              .label("rank"),
        )
        .join(Document, Chunk.document_id == Document.id)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.workspace_id == workspace_id,
            KnowledgeBase.id == knowledge_base_id,
            Document.status == DocumentStatus.ready,
        )
        .order_by(Chunk.embedding.cosine_distance(query_embedding))
        .limit(top_k * 2)
        .cte("vector_leg")
    )

    text_leg = (
        select(
            Chunk.id.label("chunk_id"),
            sa.func.row_number()
              .over(order_by=sa.func.ts_rank(Chunk.content_tsv, sa.func.plainto_tsquery("simple", query_text)).desc())
              .label("rank"),
        )
        .join(Document, Chunk.document_id == Document.id)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.workspace_id == workspace_id,
            KnowledgeBase.id == knowledge_base_id,
            Document.status == DocumentStatus.ready,
            Chunk.content_tsv.op("@@")(sa.func.plainto_tsquery("simple", query_text)),
        )
        .order_by(sa.func.ts_rank(Chunk.content_tsv, sa.func.plainto_tsquery("simple", query_text)).desc())
        .limit(top_k * 2)
        .cte("text_leg")
    )

    # RRF: score = Σ 1 / (k + rank)，k 取 60
    fused = (
        select(
            Chunk.id,
            Chunk.content,
            (
                vector_weight * sa.func.coalesce(1.0 / (60 + vector_leg.c.rank), 0)
                + (1 - vector_weight) * sa.func.coalesce(1.0 / (60 + text_leg.c.rank), 0)
            ).label("rrf_score"),
        )
        .select_from(Chunk)
        .outerjoin(vector_leg, Chunk.id == vector_leg.c.chunk_id)
        .outerjoin(text_leg, Chunk.id == text_leg.c.chunk_id)
        .where(
            sa.or_(vector_leg.c.chunk_id.isnot(None), text_leg.c.chunk_id.isnot(None))
        )
        .order_by(sa.text("rrf_score DESC"))
        .limit(top_k)
    )
    result = await session.execute(fused)
    return result.all()
```

**设计要点：**

- 两路各自取 `top_k * 2` 候选再融合，避免单路漏召回。
- 两路均只检索 `Document.status == DocumentStatus.ready` 的文档：处理中/失败的文档不参与召回。
- text_leg 在 `.limit()` 前先 `.order_by(ts_rank DESC)`：保证截断留下的是排名最高的候选（与窗口函数排序一致）。
- RRF 不需要对两路分数做归一化（余弦距离与 ts_rank 量纲不同，直接加权不可比），只依赖排名，工程上最稳。
- `@@` 操作符命中 GIN 索引 `ix_chunks_content_tsv`。

### 5.3 获取对话及其消息

```python
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from app.models.conversation import Conversation
from app.models.message import Message


async def get_conversation_with_messages(
    session,
    conversation_id: int,
    user_id: int,
):
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))  # 一次 IN 查询加载全部消息，避免 N+1
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,  # 只能看自己的对话
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
```

若消息量大需分页：

```python
stmt = (
    select(Message)
    .where(Message.conversation_id == conversation_id)
    .order_by(Message.created_at, Message.id)
    .limit(50)
    .offset(offset)
)
```

### 5.4 用户本月 token 用量

```python
from datetime import datetime, timezone
from sqlalchemy import select, func


async def get_monthly_usage(session, user_id: int):
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    stmt = (
        select(
            TokenUsage.model,
            func.sum(TokenUsage.tokens_in).label("total_in"),
            func.sum(TokenUsage.tokens_out).label("total_out"),
            func.sum(TokenUsage.cost_usd).label("total_cost"),
            func.count().label("call_count"),
        )
        .where(
            TokenUsage.user_id == user_id,
            TokenUsage.created_at >= month_start,
            TokenUsage.created_at < now,
        )
        .group_by(TokenUsage.model)
    )
    result = await session.execute(stmt)
    return result.all()
```

走索引 `ix_token_usage_user_created`：`(user_id, created_at)` 复合索引先定位用户再范围扫描时间段。

### 5.5 多租户隔离查询模式

**铁律：任何涉及租户数据的查询，WHERE 子句必须含 `workspace_id`。**

```python
async def list_knowledge_bases(session, workspace_id: int):
    stmt = (
        select(KnowledgeBase)
        .where(KnowledgeBase.workspace_id == workspace_id)  # 永远带租户过滤
        .order_by(KnowledgeBase.created_at.desc())
    )
    return (await session.execute(stmt)).scalars().all()


async def get_document(session, workspace_id: int, document_id: int):
    """跨表资源必须先 join 回租户锚点验证归属，再返回。"""
    stmt = (
        select(Document)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(
            Document.id == document_id,
            KnowledgeBase.workspace_id == workspace_id,  # 防越权
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()
```

反例（**禁止**）：

```python
# 危险：只按主键查，任何知道 document_id 的租户都能读到别人的文档
stmt = select(Document).where(Document.id == document_id)
```

---

## 6. 多租户隔离策略

### 6.1 隔离模型选择

| 方案 | 隔离强度 | 成本 | 本项目选择 |
|---|---|---|---|
| 每租户独立数据库 | 最强 | 运维/连接数爆炸 | 否 |
| 每租户独立 schema | 强 | 迁移需逐 schema 执行 | 否 |
| **共享表 + workspace_id 行级过滤** | 中（靠纪律） | 最低 | **是** |
| RLS（行级安全策略） | 强（数据库兜底） | 需维护策略 | 作为增强项 |

选择共享表方案的理由：单实例即可承载大量租户；所有列表查询天然带 `workspace_id` 索引前缀，性能不受影响。代价是隔离依赖应用层纪律——用下面的中间件 + code review 规则补偿。

### 6.2 中间件方案：JWT → workspace_id → 查询上下文

```
请求 → JWT 鉴权中间件 → 校验成员资格 → 注入 request.state.workspace_id
     → 路由 handler → 所有 service 函数强制接收 workspace_id 参数
```

```python
# app/middleware/tenant.py
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.auth import decode_jwt
from app.services.membership import assert_membership


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. 从 JWT 解析用户
        payload = decode_jwt(request.headers.get("Authorization", ""))
        if payload is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        request.state.user_id = int(payload["sub"])

        # 2. 从路径/Header 提取目标 workspace，并校验该用户是成员
        ws_raw = request.headers.get("X-Workspace-ID")
        if ws_raw:
            workspace_id = int(ws_raw)
            role = await assert_membership(request.state.user_id, workspace_id)
            if role is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
            request.state.workspace_id = workspace_id
            request.state.role = role

        return await call_next(request)
```

```python
# app/deps.py —— 依赖注入，service 层无法"忘记"传租户参数
from fastapi import Request


def get_workspace_id(request: Request) -> int:
    ws_id = getattr(request.state, "workspace_id", None)
    if ws_id is None:
        raise HTTPException(status_code=400, detail="X-Workspace-ID required")
    return ws_id


# 路由用法：
@router.get("/knowledge-bases")
async def list_kbs(
    ws_id: int = Depends(get_workspace_id),
    session: AsyncSession = Depends(get_session),
):
    return await kb_service.list_knowledge_bases(session, ws_id)
```

**关键点：**

- `workspace_id` 来自**服务端校验后的 JWT + 成员表**，绝不信任客户端自行声明的租户身份。
- service 层函数签名强制包含 `workspace_id` 参数（而非全局变量），让"漏过滤"在 code review 中可见。
- 跨租户资源（如 document_id）的访问必须 join 回 `knowledge_bases.workspace_id` 验证（见 5.5）。

### 6.3 Row-Level Security（可选增强）

应用层过滤是主防线，RLS 作为数据库层兜底——即使某条 SQL 漏写过滤条件，数据库也拒绝返回其他租户的行。

```sql
-- 为带 workspace_id 的表启用 RLS
ALTER TABLE knowledge_bases ENABLE ROW LEVEL SECURITY;
ALTER TABLE token_usage     ENABLE ROW LEVEL SECURITY;
-- documents/chunks 没有 workspace_id 列，通过 knowledge_bases 间接保护：
-- 方案 A：给 documents 冗余 workspace_id 列后直接加策略
-- 方案 B：保持 join 隔离，仅对有列的表启用 RLS

-- 策略：应用连接通过 set_config('app.workspace_id', ..., true) 声明当前租户
CREATE POLICY tenant_isolation_kb ON knowledge_bases
    USING (workspace_id = current_setting('app.workspace_id')::bigint);

CREATE POLICY tenant_isolation_usage ON token_usage
    USING (workspace_id = current_setting('app.workspace_id')::bigint);

-- 表 owner 默认绕过 RLS，应用账号必须不是 owner
ALTER TABLE knowledge_bases FORCE ROW LEVEL SECURITY;
```

应用侧每个请求开始时：

```python
async def set_tenant_context(session, workspace_id: int):
    await session.execute(
        sa.text("SELECT set_config('app.workspace_id', :ws, true)"),
        {"ws": str(workspace_id)},
    )
```

**RLS 落地注意事项：**

1. 应用数据库账号不能是表 owner（owner 默认 BYPASS RLS），需单独创建 `app_user` 角色并 `GRANT`。
2. `set_config(..., true)` 第三个参数为 `true` 时仅在当前事务内生效（等价于 `SET LOCAL`），配合连接池必须在每个事务开始时设置，事务结束自动清理——切勿用会话级设置污染归还连接。
3. RLS 策略本身消耗少量查询规划开销，且会让 EXPLAIN 计划变复杂；先上应用层隔离，RLS 作为二期加固。
4. Alembic 迁移账号需要 BYPASSRLS 权限，否则迁移时看不到数据。

### 6.4 隔离检查清单

- [ ] 所有业务表查询 WHERE 含 `workspace_id`（直接或间接 join）
- [ ] 中间件校验成员资格后才注入 `workspace_id`
- [ ] service 层函数签名强制 `workspace_id` 参数
- [ ] 按主键访问跨租户资源的接口，先 join 验证归属
- [ ] 集成测试包含"租户 A 访问租户 B 资源返回 404/403"用例
- [ ] （二期）RLS 策略覆盖所有含 workspace_id 的表，应用账号非 owner

---

## 附录：设计决策速查

| 决策 | 结论 | 理由 |
|---|---|---|
| 主键类型 | int64 自增（BigInteger） | 紧凑、顺序写入、join 友好；安全靠鉴权与租户过滤，不靠 ID 不可猜 |
| 时间戳 | `DateTime(timezone=True)` + `datetime.now(timezone.utc)` | timestamptz 免时区歧义；禁用已弃用的 `utcnow()` |
| 租户模型 | 共享表 + workspace_id | 成本最低，索引前缀保证性能 |
| 向量索引 | HNSW (m=16, ef_construction=64) | 召回/查询速度优于 IVFFlat，支持增量 |
| 距离函数 | 余弦 `<=>` | 文本 embedding 标准选择 |
| 混合检索融合 | RRF | 免归一化，工程最稳 |
| embedding 配置层级 | 知识库级 | 保证向量空间一致 |
| 默认 embedding 模型 | bge-m3（1024 维） | 全局统一默认值，与 chunks.embedding 维度一致 |
| messages.sources | JSONB 快照 | 引用是历史快照，不受 chunk 删除影响 |
| token_usage | append-only 流水 | 聚合灵活，可分区扩展 |
| api_key 存储 | 只存 SHA-256 哈希 | 库泄露不泄露可用密钥 |
| enum 实现 | PG 原生 enum | 紧凑、类型安全；扩展用 ALTER TYPE |
