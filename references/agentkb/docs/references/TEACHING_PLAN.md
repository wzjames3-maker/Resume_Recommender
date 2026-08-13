# MaxKB 复刻 — 全栈工程师教学计划

> 目标：通过复刻 MaxKB（22.4k⭐ RAG 知识库平台），培养全栈工程师的工程能力
> 周期：8 周 × 每天 2-3h
> 技术栈：FastAPI + React/TS + PostgreSQL/pgvector + Redis + Docker + GitHub Actions

---

## 教学方法论

每个教学单元遵循五步闭环：

```
┌─────────────────────────────────────────────────────────────┐
│ ① 讲（15min）│ 我讲概念 + 读源码，建立"为什么"的认知       │
│ ② 演（15min）│ 我写代码/敲命令，你观察完整过程             │
│ ③ 练（60min）│ 你独立实现，我不干预，卡住 30min 才介入     │
│ ④ 审（15min）│ 我 Code Review 你的代码，指出问题           │
│ ⑤ 验（15min）│ 跑测试/验收标准，确认你真正掌握             │
└─────────────────────────────────────────────────────────────┘
```

**验收原则：** 不是"代码跑通了"就算过，而是：
- 能不看笔记复述原理
- 能解释每个设计决策的"为什么"
- 能回答我随机追问的 3 个问题
- 测试全绿 + 覆盖率达标

---

## W1：项目骨架 + Git 工作流 + JWT 认证

### 教学目标

学完本周你能：
- 用规范流程初始化一个生产级项目（不是 `mkdir + touch`）
- 用 Git 分支 + PR 流程管理代码（不是直接 push main）
- 实现完整的 JWT 认证链路并解释每一步的安全考量
- 用 Docker Compose 一键启动多服务环境

---

### D1：项目初始化 + Git 规范

**① 讲（15min）**

我讲：
- 读 MaxKB 源码目录结构（`apps/`、`ui/`），解释为什么这么分
- monorepo vs 多仓库的取舍
- `.gitignore` 该忽略什么、为什么
- 分支命名规范：`feat/xxx`、`fix/xxx`、`docs/xxx`
- Conventional Commits 格式：`type(scope): description`

**② 演（15min）**

我演示：
```bash
mkdir maxkb-replica && cd maxkb-replica
git init
# 创建目录结构
mkdir -p backend/app/{api,core,models,schemas,services,tasks,rag}
mkdir -p backend/tests
mkdir -p frontend/src/{components,pages,stores,api,hooks}
mkdir -p docs scripts nginx .github/workflows
# 注意：alembic/ 不手动建，W1D3 由 `alembic init` 生成

# 写 .gitignore（逐项解释为什么）
# 写 README.md（项目定位 + 技术栈 + 启动方式）

git add .
git commit -m "chore: initialize project structure"
```

**③ 练（60min）**

你做：
1. 克隆 MaxKB 源码备查：`git clone https://github.com/1Panel-dev/MaxKB.git ~/reference/maxkb`（仅作参考阅读，不修改）
2. 在你的目录下独立重建整个目录结构（不看我的演示）
3. 写 `.gitignore`（Python + Node + IDE + 环境变量）
4. 写 `README.md`（项目名、一句话描述、技术栈表格、启动命令）
5. 创建分支 `feat/project-init`，提交，合并回 main
6. 创建 `Makefile`，包含 `init`、`dev`、`test`、`lint` 四个 target

**④ 审（15min）**

我检查：
- 目录结构是否合理（为什么 `rag/` 单独一层？）
- `.gitignore` 是否遗漏（`.env` 有没有？`__pycache__` 有没有？）
- commit message 是否规范
- README 是否让一个新人 3 分钟内知道怎么跑起来

**⑤ 验（15min）**

验收标准：
- [ ] `tree -L 2` 输出结构合理
- [ ] `git log --oneline` 只有一条规范 commit
- [ ] 我能看着 README 把项目跑起来（虽然现在是空壳）
- [ ] 你口头回答：为什么 backend/frontend 分开？为什么不用 monorepo 工具（turborepo）？

---

### D2：FastAPI 骨架 + 配置管理 + 结构化日志

**① 讲（15min）**

我讲：
- FastAPI 项目分层：`api/`（路由）→ `services/`（逻辑）→ `models/`（数据）
- 为什么用 pydantic-settings 管理配置（不是硬编码、不是 `.env` 直接读）
- 结构化日志（JSON 格式）vs print 的区别
- request_id 中间件：为什么每个请求需要唯一 ID

**② 演（15min）**

我演示：
```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "MaxKB Replica"
    database_url: str
    redis_url: str
    jwt_secret: str
    jwt_expire_minutes: int = 30

    class Config:
        env_file = ".env"

settings = Settings()
```

```python
# backend/app/core/logging.py — JSON 结构化日志
import logging, json, uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": self.formatTime(record),
            "level": record.levelname,
            "request_id": request_id_var.get(),
            "msg": record.getMessage(),
        }, ensure_ascii=False)
```

```python
# backend/app/main.py
from fastapi import FastAPI, Request
import uuid

app = FastAPI(title=settings.app_name)

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

**③ 练（60min）**

你做：
1. 创建 `backend/pyproject.toml`（用 uv 管理依赖）
2. 实现 `config.py`（database_url, redis_url, jwt_secret 从环境变量读）
3. 实现 JSON 结构化日志 + request_id 中间件
4. 实现 `/health` 端点
5. 写 `.env.example`（不含真实值）
6. 写第一个测试：`test_health.py`（用 httpx TestClient）
7. 分支 `feat/api-skeleton`，commit：`feat: add FastAPI skeleton with structured logging`

**④ 审（15min）**

我检查：
- 配置是否全部从环境变量来（没有硬编码密码）
- 日志是否真的是 JSON（不是 print）
- request_id 是否贯穿整个请求生命周期
- 测试是否用了 fixture（不是每个测试函数重复创建 client）

**⑤ 验（15min）**

验收标准：
- [ ] `uvicorn app.main:app --reload` 启动成功
- [ ] `curl localhost:8000/health` 返回 `{"status":"ok"}`
- [ ] 响应头有 `X-Request-ID`
- [ ] 日志输出是 JSON 格式且包含 request_id
- [ ] `pytest` 全绿
- [ ] 你口头回答：为什么不用 `os.getenv` 直接读？pydantic-settings 多了什么？

---

### D3：数据库 + ORM + 迁移

**① 讲（15min）**

我讲：
- SQLAlchemy 2.0 新语法（`Mapped`、`mapped_column`、`select`）
- 为什么用 Alembic 做迁移（不是 `create_all`）
- 迁移的本质：版本化的 DDL，可前进可回滚
- User 表设计：为什么密码存 hash 不存明文

**② 演（15min）**

我演示：
```python
# backend/app/models/user.py
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
import datetime

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=lambda: datetime.datetime.now(datetime.timezone.utc))
```

```bash
# 初始化 Alembic + 生成第一个迁移
alembic init alembic
alembic revision --autogenerate -m "add users table"
alembic upgrade head
```

> **注意（最常见卡点）：** Alembic 模板默认只支持同步 engine，而本项目用的是 async engine。
> `alembic init` 后必须改 `alembic/env.py`：把 `run_migrations` 改成用 `AsyncEngine.connect()`
> + `connection.run_sync(do_run_migrations)` 跑迁移，否则 autogenerate 直接报错。课上现场演示改法。

**③ 练（60min）**

你做：
1. 配置 `database.py`（async engine + session factory）
2. 实现 User 模型
3. 初始化 Alembic，生成并执行迁移
4. 写测试：创建用户 → 查询 → 验证字段
5. 写测试：重复 email 报 IntegrityError
6. 分支 `feat/db-schema`，commit：`feat: add user model with alembic migration`

**④ 审（15min）**

我检查：
- 是否用了 async session（不是同步）
- `alembic/env.py` 是否改成了 async engine（不是偷偷换同步 engine 绕过）
- 迁移文件是否生成了正确的 DDL
- 测试是否用了独立数据库（不是污染开发库）
- `email` 是否加了 unique 约束和 index

**⑤ 验（15min）**

验收标准：
- [ ] `alembic upgrade head` 成功建表
- [ ] `alembic downgrade -1` 能回滚
- [ ] 测试全绿（创建 + 查询 + 唯一约束）
- [ ] 你口头回答：为什么不用 `Base.metadata.create_all`？迁移解决了什么问题？

---

### D4：JWT 认证完整链路

**① 讲（15min）**

我讲：
- JWT 三段结构（header.payload.signature）
- access_token vs refresh_token 的分工
- 密码哈希：bcrypt/argon2，为什么不能存明文
- 认证流程：注册 → 登录 → 携带 token → 刷新 → 登出
- 安全考量：token 存哪里（内存 vs localStorage vs httpOnly cookie）

**② 演（15min）**

我演示完整的 4 个 API：
```
POST /auth/register  → 创建用户，返回 user_id
POST /auth/login     → 验证密码，返回 access + refresh token
POST /auth/refresh   → 用 refresh token 换新 access token（JSON body 传 refresh_token）
POST /auth/logout    → 将 refresh token 加入黑名单（Redis）
```

密码哈希 + JWT 签发/校验（`bcrypt` + `PyJWT`）：
```python
# backend/app/core/security.py
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int, kind: str) -> str:
    """kind: "access"（30min）或 "refresh"（7d）"""
    minutes = settings.jwt_expire_minutes if kind == "access" else 7 * 24 * 60
    payload = {
        "sub": str(user_id),
        "type": kind,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:  # 过期/篡改/签名不对统一处理，不暴露细节
        raise HTTPException(401, "token 无效或已过期")
```

认证守卫 + Redis 黑名单：
```python
# backend/app/api/deps.py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer()


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db=Depends(get_db),
    redis=Depends(get_redis),
) -> User:
    token = creds.credentials
    # 黑名单检查：已登出的 token 不能再用
    if await redis.get(f"token:blacklist:{token}"):
        raise HTTPException(401, "token 无效或已过期")
    payload = decode_token(token)
    user = await db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(401, "token 无效或已过期")
    return user


class RefreshBody(BaseModel):  # refresh/logout 都用 JSON body 传 token
    refresh_token: str


# /auth/logout：refresh token 进黑名单（TTL 取剩余有效期，到期自动清理）
@router.post("/auth/logout")
async def logout(body: RefreshBody, redis=Depends(get_redis)):
    await redis.set(f"token:blacklist:{body.refresh_token}", "1", ex=7 * 24 * 3600)


# /auth/refresh：先查黑名单再校验（JSON body：{"refresh_token": "..."}）
@router.post("/auth/refresh")
async def refresh(body: RefreshBody, redis=Depends(get_redis)):
    if await redis.get(f"token:blacklist:{body.refresh_token}"):
        raise HTTPException(401, "token 无效或已过期")
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(401, "token 无效或已过期")
    return {"access_token": create_token(int(payload["sub"]), "access")}
```

重点演示：
- `bcrypt` 库直接做密码 hash（不用 passlib —— 长期未维护、与新版 bcrypt 有兼容问题）
- `PyJWT` 生成/验证 JWT（不用 python-jose —— 停止维护且有 CVE）
- FastAPI `Depends` 做认证守卫
- Redis 存 token 黑名单（logout/refresh 都要查）

**③ 练（60min）**

你做：
1. 实现 `POST /auth/register`（密码 hash + 存库）
2. 实现 `POST /auth/login`（验证 + 签发双 token）
3. 实现 `POST /auth/refresh`（验证 refresh + 签发新 access）
4. 实现 `POST /auth/logout`（refresh token 进 Redis 黑名单）
5. 实现 `get_current_user` 依赖（从 Authorization header 解析）
6. 写测试覆盖：正常流程 + 错误密码 + 过期 token + 已登出 token
7. 分支 `feat/auth`，PR 合并

**④ 审（15min）**

我检查：
- 密码是否 hash 存储（数据库里看不到明文）
- token 过期时间是否合理（access 30min，refresh 7d）
- refresh 时是否检查了黑名单
- 错误响应是否统一格式（不暴露"用户不存在"vs"密码错误"的区别）
- 测试是否覆盖了所有异常路径

**⑤ 验（15min）**

验收标准：
- [ ] 注册 → 登录 → 带 token 访问 → 刷新 → 登出，全链路 curl 走通
- [ ] 登出后 refresh token 不能再用
- [ ] 错误密码返回 401，不暴露用户是否存在
- [ ] 测试覆盖率 > 95%（认证模块）
- [ ] 你口头回答：为什么 access token 要短命？refresh token 为什么要能作废？

---

### D5：Docker Compose + 开发环境

**① 讲（15min）**

我讲：
- Docker 解决什么问题（"在我机器上是好的"）
- docker-compose 编排多服务（app + postgres + redis）
- 卷（volume）持久化数据
- healthcheck 控制启动顺序
- Makefile 封装常用命令

**② 演（15min）**

我演示：
```yaml
# docker-compose.yml
services:
  app:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
    volumes: ["./backend:/app"]  # 开发热重载

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: maxkb
      POSTGRES_PASSWORD: ${DB_PASSWORD}
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

volumes:
  pgdata:
```

**③ 练（60min）**

你做：
1. 写 `backend/Dockerfile`（多阶段构建，非 root 用户）
2. 写 `docker-compose.yml`（app + db + redis）
3. 写 `Makefile`（up/down/logs/test/lint/migrate）
4. 验证：`make up` → 三个容器全 healthy → `curl /health` 通
5. 验证：`make test` 在容器内跑测试全绿
6. 分支 `feat/docker`，commit：`feat: add docker-compose dev environment`

**④ 审（15min）**

我检查：
- Dockerfile 是否多阶段（最终镜像不含 pip 缓存和构建工具）
- 是否用了非 root 用户
- `.env` 是否没被打进镜像
- healthcheck 是否配了
- depends_on 是否用了 condition

**⑤ 验（15min）**

验收标准：
- [ ] `make up` 一条命令启动全部服务
- [ ] `docker compose ps` 三个容器全 healthy
- [ ] `make test` 在容器内跑测试全绿
- [ ] `docker image ls` 镜像 < 300MB
- [ ] 你口头回答：为什么 depends_on 不够，还要 healthcheck？多阶段构建省了什么？

---

### D6：GitHub Actions CI

**① 讲（15min）**

我讲：
- CI 的目的：每次 push 自动验证代码质量
- 管线分段：lint → test → build（快的先跑）
- GitHub Actions 语法：on/jobs/steps/services
- 为什么测试需要 services（真实 PostgreSQL）

**② 演（15min）**

我演示完整的 `.github/workflows/ci.yml`：
```yaml
name: CI
on: [push, pull_request]
jobs:
  lint-test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend   # 后端代码在 backend/ 子目录
    services:
      postgres:
        image: postgres:16-alpine
        env: { POSTGRES_PASSWORD: test }
        ports: ["5432:5432"]
        options: --health-cmd pg_isready --health-interval 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: astral-sh/setup-uv@v4   # 项目用 uv + pyproject.toml 管理依赖
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run pytest --cov=app --cov-fail-under=80
```

**③ 练（60min）**

你做：
1. 写 `.github/workflows/ci.yml`
2. push 到 GitHub，观察 Actions 跑
3. 故意写一个 lint 错误，观察 CI 红灯
4. 修复，观察 CI 绿灯
5. 设置分支保护：main 必须 CI 通过才能合并
6. 分支 `feat/ci`，PR 合并（这是第一个走完整 PR 流程的）

**④ 审（15min）**

我检查：
- CI 是否包含 lint + test 两步
- 测试是否用了真实 PostgreSQL（不是 SQLite mock）
- 覆盖率门禁是否设了
- 分支保护是否生效

**⑤ 验（15min）**

验收标准：
- [ ] push 触发 CI，绿灯
- [ ] 故意破坏代码，CI 红灯
- [ ] main 分支保护生效（不能直接 push）
- [ ] 你口头回答：为什么 CI 里用真实 PG 而不是 SQLite？`--cov-fail-under` 的作用？

---

### D7：周复盘 + 面试准备

**教学内容：**

1. **画架构图**（你画，我审）：
   - 画出本周搭建的完整架构：Client → FastAPI → PG/Redis
   - 标注每个组件的职责

2. **整理面试话术**（你写，我改）：
   - "项目怎么组织的？" → 30 秒回答
   - "JWT 怎么做的？" → 30 秒回答
   - "Docker 怎么用的？" → 30 秒回答

3. **Git 复盘**：
   - `git log --oneline --graph` 看本周所有 commit
   - 检查：每条 commit message 是否规范？分支是否都合并了？

4. **自测**（我问，你答）：
   - 为什么用 pydantic-settings 不用 os.getenv？
   - JWT 的 signature 是怎么生成的？篡改 payload 会怎样？
   - Docker 多阶段构建为什么能减小镜像？
   - CI 里为什么要 `--cov-fail-under=80`？

---

## W2：文档入库管线 + 异步任务 + Mock 测试

### 教学目标

学完本周你能：
- 设计文件上传 API（multipart + 大小限制 + 类型校验）
- 用 Celery 处理耗时任务，解释为什么不能同步做
- 实现 PDF/MD/TXT 解析 + 递归切片
- 用 Mock 测试异步任务（不依赖真实 Worker）
- 用 `git rebase` 整理提交历史

---

### D1：文件上传 API

**① 讲（15min）**

我讲：
- 读 MaxKB 的文档上传源码，看它怎么做的
- multipart/form-data 的原理（为什么文件上传不用 JSON）
- FastAPI 的 `UploadFile` 用法
- 安全：文件类型白名单、大小限制、文件名清洗（`secure_filename`）

**② 演（15min）**

我演示：
```python
from fastapi import UploadFile, File, HTTPException

ALLOWED_TYPES = {"application/pdf", "text/markdown", "text/plain"}
MAX_SIZE = 50 * 1024 * 1024  # 50MB

# 文档必须挂在某个知识库下 → 嵌套路由（REST 资源归属）
@app.post("/knowledge-bases/{kb_id}/documents", status_code=201)
async def upload_document(kb_id: int, file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"不支持的文件类型: {file.content_type}")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(413, "文件超过 50MB 限制")
    # 校验 kb_id 存在 + 存文件 + 创建 Document 记录 + 触发异步解析
    ...
```

**③ 练（60min）**

你做：
1. 实现 KnowledgeBase 模型（id, name, created_at）—— W4D4 配置、W6D1 多租户都基于它，先把表建好
2. 实现 Document 模型（id, knowledge_base_id 外键, filename, status, size, created_at）
3. 实现 `POST /knowledge-bases/{kb_id}/documents` 上传接口（文档必须归属知识库）
4. 实现 `GET /knowledge-bases/{kb_id}/documents` 列表 + `GET /documents/{id}` 详情
5. 实现 `DELETE /documents/{id}` 删除
6. 安全校验：类型白名单 + 大小限制 + secure_filename
7. 测试：正常上传 + 类型错误 + 超大文件 + 列表/删除
8. 分支 `feat/doc-upload`

**④ 审（15min）**

我检查：
- 文件名是否做了清洗（防路径穿越）
- 大文件是否流式读取（不是一次性 `file.read()` 撑爆内存）
- 状态字段是否设计了（pending/processing/ready/failed）
- 测试是否覆盖了所有异常路径

**⑤ 验（15min）**

验收标准：
- [ ] curl 上传 PDF 返回 201 + document_id
- [ ] 上传 .exe 返回 400
- [ ] 上传 60MB 文件返回 413
- [ ] 测试全绿，覆盖率 > 90%
- [ ] 你口头回答：为什么文件上传不用 JSON？`secure_filename` 防的是什么攻击？

---

### D2：Celery 异步任务

**① 讲（15min）**

我讲：
- 为什么文档解析不能同步做（50MB PDF 解析要 30 秒，HTTP 超时）
- Celery 架构：Broker（Redis）→ Worker → Backend
- 任务生命周期：PENDING → STARTED → SUCCESS/FAILURE
- 重试策略：`autoretry_for`、`retry_backoff`

**② 演（15min）**

我演示：
```python
# backend/app/tasks/parse_document.py
from celery import shared_task

@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def parse_document(self, document_id: int):
    """异步解析文档：提取文本 → 切片 → embedding → 入库"""
    doc = get_document(document_id)
    try:
        text = extract_text(doc)       # 解析
        chunks = split_text(text)      # 切片
        vectors = embed_chunks(chunks) # 向量化
        store_vectors(chunks, vectors) # 入库
        doc.status = "ready"
    except Exception as e:
        doc.status = "failed"
        raise  # 让 Celery 重试
```

**③ 练（60min）**

你做：
1. 配置 Celery（Redis 作 Broker）
2. 实现 `parse_document` 任务骨架（先只打日志，不真解析）
3. 上传 API 中触发异步任务
4. 实现 `GET /documents/{id}/status` 查询任务进度
5. docker-compose 加 celery worker 服务
6. 测试：Mock Celery 任务（不启动真实 Worker）
7. 分支 `feat/celery-tasks`

**④ 审（15min）**

我检查：
- 任务是否幂等（重复执行不会重复入库）
- 失败后状态是否正确更新
- 重试是否有上限（不是无限重试）
- 测试是否 Mock 了 Celery（不依赖真实 Worker）

**⑤ 验（15min）**

验收标准：
- [ ] 上传后文档状态从 pending → processing → ready
- [ ] Worker 日志可见任务执行过程
- [ ] 模拟解析失败，状态变 failed，重试 3 次后停止
- [ ] 测试全绿（Mock 模式，不需要真实 Worker）
- [ ] 你口头回答：为什么用 Redis 做 Broker 而不是 RabbitMQ？任务幂等怎么保证？

---

### D3：文档解析器

**① 讲（15min）**

我讲：
- PDF 解析的难点（双栏、表格、扫描件）
- PyMuPDF（fitz）的基本用法
- Markdown/TXT 直接用正则/编码器
- 解析失败怎么办（降级策略）

**② 演（15min）**

我演示三种解析器的实现 + 策略模式：
```python
class ParserFactory:
    @staticmethod
    def get_parser(content_type: str) -> BaseParser:
        if content_type == "application/pdf":
            return PDFParser()
        elif content_type == "text/markdown":
            return MarkdownParser()
        return PlainTextParser()
```

**③ 练（60min）**

你做：
1. 实现 `PDFParser`（PyMuPDF 提取文本）
2. 实现 `MarkdownParser`（保留标题结构）
3. 实现 `PlainTextParser`
4. 实现 `ParserFactory`（策略模式）
5. 准备 3 个测试文件（PDF/MD/TXT），写参数化测试
6. 分支 `feat/parsers`

**④ 审（15min）**

我检查：
- 是否用了策略模式（不是 if-else 堆砌）
- PDF 解析是否处理了空页面/加密文件
- 测试文件是否覆盖了边界（空文件、纯图片 PDF）

**⑤ 验（15min）**

验收标准：
- [ ] 3 种格式都能正确提取文本
- [ ] 空文件不报错，返回空字符串
- [ ] 参数化测试全绿
- [ ] 你口头回答：为什么用策略模式？遇到扫描件 PDF（纯图片）怎么办？

---

### D4：文本切片

**① 讲（15min）**

我讲：
- 为什么要切片（embedding 模型有输入长度限制 + 小片段检索更精准）
- 递归分割的原理（按 `\n\n` → `\n` → `.` → 空格逐级尝试）
- overlap 的作用（防止语义被截断）
- 切片大小的取舍（太小丢上下文，太大噪声多）

**② 演（15min）**

我演示递归切片实现 + overlap 逻辑：
```python
# backend/app/rag/splitter.py
def recursive_split(text: str, chunk_size: int = 512, overlap: int = 64,
                    separators: tuple[str, ...] = ("\n\n", "\n", "。", " ")) -> list[str]:
    """递归分割：优先用粗分隔符，单段超长时降级到细分隔符，最后按字符硬切"""
    if len(text) <= chunk_size:
        return [text] if text else []
    if not separators:  # 兜底：按字符硬切（超长且无可切分点的极端情况）
        step = max(chunk_size - overlap, 1)
        return [text[i:i + chunk_size] for i in range(0, len(text), step)]

    sep, rest = separators[0], separators[1:]
    pieces = text.split(sep)

    chunks, buf = [], ""
    for i, p in enumerate(pieces):
        part = p + sep if i < len(pieces) - 1 else p  # 保留分隔符本身
        if len(part) > chunk_size:
            # 单段超长 → 用更细的分隔符递归切
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(recursive_split(part, chunk_size, overlap, rest))
        elif len(buf) + len(part) <= chunk_size:
            buf += part  # 装得下就继续累积
        else:
            chunks.append(buf)  # 装不下 → 当前 buf 成块
            buf = part
    if buf:
        chunks.append(buf)

    # overlap：把上一块的尾部带到下一块开头，防止语义被截断
    for i in range(1, len(chunks)):
        chunks[i] = chunks[i - 1][-overlap:] + chunks[i]
    return chunks
```

现场跑一个例子：800 字文本按 `\n\n` 切成两段各 400 字 → 各自不超限直接成块 → 第二块头部带 64 字 overlap。

**③ 练（60min）**

你做：
1. 实现递归切片函数
2. 实现 overlap 逻辑
3. 实现 Chunk 模型（id, document_id, content, chunk_index, metadata）
4. 测试：正常文本 + 短文本（不切）+ 超长段落（强制切）
5. 测试：overlap 区域确实有重叠
6. 分支 `feat/chunking`

**④ 审（15min）**

我检查：
- 切片是否尊重语义边界（不是在词中间切）
- overlap 计算是否正确
- 空文本/单字符文本是否处理了
- 测试是否验证了"切片后拼回来 ≈ 原文"

**⑤ 验（15min）**

验收标准：
- [ ] 512 字文本切成 ~1 块，1024 字切成 ~2 块
- [ ] 相邻块有 64 字重叠
- [ ] 不会在句子中间切断（优先在句号/换行处切）
- [ ] 测试全绿
- [ ] 你口头回答：overlap 太大太小各有什么问题？为什么不用按 token 数切？

---

### D5：Embedding + pgvector 入库

**① 讲（15min）**

我讲：
- Embedding 模型选择（BGE-M3 中文好，OpenAI 方便）
- pgvector 的 vector 类型 + HNSW 索引
- 批量入库的性能考量（不是逐条 INSERT）

**② 演（15min）**

我演示：
```python
# 批量 embedding + 写入 pgvector
from pgvector.sqlalchemy import Vector

class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    content: Mapped[str]
    embedding = mapped_column(Vector(1024))  # BGE-M3 维度
```

**③ 练（60min）**

你做：
1. 安装 pgvector 扩展（Docker 里用 `pgvector/pgvector:pg16` 镜像）
2. Chunk 模型加 embedding 列
3. 实现 `embed_chunks()`（调 BGE API 或 OpenAI）
4. 实现批量入库：`await session.execute(insert(Chunk), [list_of_dicts])`（注意：async session 没有 `bulk_insert_mappings`，那是同步 Session 的 API）
5. 把 D2 的任务骨架串起来：解析 → 切片 → embedding → 入库
6. 集成测试：上传 → 等待 → 验证 chunks 表有数据
7. 分支 `feat/embedding-pipeline`

**④ 审（15min）**

我检查：
- 是否批量入库（不是 for 循环逐条）
- embedding 维度是否和模型匹配
- 失败时是否清理了半成品数据
- 集成测试是否用了真实 pgvector（不是 Mock）

**⑤ 验（15min）**

验收标准：
- [ ] 上传一个 MD 文件 → 状态变 ready → chunks 表有数据 → embedding 非空
- [ ] `SELECT embedding FROM chunks LIMIT 1` 返回 1024 维向量
- [ ] 集成测试全绿
- [ ] 你口头回答：为什么用 pgvector 不用 Milvus？HNSW 索引什么时候建？

---

### D6：错误处理 + 重试 + Git rebase

**① 讲（15min）**

我讲：
- 入库管线的错误分类：可重试（网络超时）vs 不可重试（文件格式错）
- Celery 重试策略：`retry_backoff` 指数退避
- 死信处理：重试耗尽后怎么办
- **Git rebase**：把本周零散 commit 整理成逻辑清晰的几个 commit

**② 演（15min）**

我演示：
```bash
# 交互式 rebase：把 5 个零散 commit 整理成 2 个
git rebase -i HEAD~5
# pick → squash → reword
```

**③ 练（60min）**

你做：
1. 完善错误处理：区分可重试/不可重试异常
2. 实现重试耗尽后的告警（日志 + 状态标记）
3. 用 `git rebase -i` 整理本周所有 commit
4. 确保 rebase 后 CI 仍然绿灯
5. 分支 `feat/error-handling`

**④ 审（15min）**

我检查：
- 错误分类是否合理
- rebase 后历史是否清晰（每个 commit 一个逻辑单元）
- CI 是否仍然通过

**⑤ 验（15min）**

验收标准：
- [ ] 模拟网络超时 → 自动重试 3 次 → 成功
- [ ] 模拟格式错误 → 不重试 → 直接标记 failed
- [ ] `git log --oneline` 历史清晰，无 "fix typo" 类 commit
- [ ] 你口头回答：rebase 和 merge 的区别？什么时候该 rebase 什么时候该 merge？

---

### D7：周复盘

**教学内容：**

1. **画入库流程图**（你画，我审）：
   - 上传 → Celery 任务 → 解析 → 切片 → embedding → pgvector 入库，标注每步的状态流转（pending → processing → ready/failed）
   - 标注每个组件的职责（API / Worker / PG / Redis）

2. **整理面试话术**（你写，我改）：
   - "文档解析为什么用异步任务？" → 30 秒回答
   - "入库管线怎么设计的？失败怎么办？" → 30 秒回答
   - "任务幂等怎么保证？" → 30 秒回答

3. **Git 复盘**：
   - `git log --oneline --graph` 看本周所有 commit
   - 检查：rebase 整理后的历史是否每个 commit 一个逻辑单元？分支命名是否规范？

4. **自测**（我问，你答）：
   - 为什么文档解析必须异步？同步做会怎样？
   - Celery 任务失败怎么重试？重试耗尽后怎么办？
   - 切片为什么用递归分割？chunk_size 和 overlap 怎么取舍？
   - 批量入库为什么不能 for 循环逐条 INSERT？

---

## W3：RAG 检索核心

### 教学目标

学完本周你能：
- 实现向量检索 + BM25 双路召回，解释各自适用场景
- 用 RRF 融合两路结果，推导公式中 k 的作用
- 用 Cross-Encoder 做精排，解释两级检索的延迟/精度权衡
- 实现 SSE 流式问答 + 引用标注，完成 RAG 全链路闭环

---

### D1：pgvector 向量检索 + HNSW 索引

**① 讲（15min）**

我讲：
- 读 MaxKB 源码 `rag/vector` 目录，看它的检索入口怎么写的
- 三种距离度量：余弦相似度（方向）、L2（绝对距离）、内积（幅度），为什么文本检索用余弦
- HNSW 原理：分层可导航小世界图，上层稀疏长跳、下层稠密短跳，类似跳表
- 关键参数：`m`（每个节点邻居数）、`ef_construction`（建图质量）、`ef_search`（查询精度），三者的精度/速度权衡
- 为什么向量检索会漏掉精确关键词（"SKU-12345" 被语义化后丢失字面信息）

**② 演（15min）**

我演示：
```sql
-- 余弦检索 Top-K（<=> 是余弦距离，1 - 距离 = 相似度）
SELECT id, content, 1 - (embedding <=> $1) AS score
FROM chunks
ORDER BY embedding <=> $1
LIMIT 5;

-- 建 HNSW 索引
CREATE INDEX idx_chunks_embedding_hnsw
ON chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 查询时精度旋钮
SET hnsw.ef_search = 40;

-- 验证走了索引
EXPLAIN ANALYZE
SELECT id FROM chunks ORDER BY embedding <=> $1 LIMIT 5;
```

```python
# backend/app/rag/schemas.py — 统一检索结果类型（vector/bm25/hybrid/rerank 共用）
from dataclasses import dataclass


@dataclass
class ChunkHit:
    id: int
    content: str
    score: float
```

```python
# backend/app/rag/vector_search.py
from app.rag.schemas import ChunkHit


async def vector_search(db, query: str, top_k: int = 5) -> list[ChunkHit]:
    qv = await embed(query)  # 复用 W2 的 embedding 客户端
    stmt = (
        select(Chunk, (1 - Chunk.embedding.cosine_distance(qv)).label("score"))
        .order_by(Chunk.embedding.cosine_distance(qv))
        .limit(top_k)
    )
    rows = (await db.execute(stmt)).all()
    return [ChunkHit(id=c.id, content=c.content, score=float(s)) for c, s in rows]
```

**③ 练（60min）**

你做：
1. 实现 `app/rag/vector_search.py` 的 `vector_search(query, top_k)`
2. 写 Alembic 迁移：给 `chunks.embedding` 加 HNSW 索引
3. 写召回测试：插入 20 条已知内容的 chunks，断言语义最近的 query 命中预期条目
4. 用 `EXPLAIN ANALYZE` 对比建索引前后的执行计划，把结果贴进 PR 描述
5. 分支 `feat/vector-search`，commit：`feat: add pgvector search with hnsw index`

**④ 审（15min）**

我检查：
- 是否用了余弦距离而不是 L2（为什么？）
- HNSW 参数是否抄的默认值还是理解过（m=16/ef_construction=64 的出处）
- 测试是否用真实 pgvector（不是 Mock embedding）
- 排序方向是否正确（距离升序 = 相似度降序，新手常搞反）

**⑤ 验（15min）**

验收标准：
- [ ] 给定 query 返回语义最近的 Top-K，且顺序正确
- [ ] `EXPLAIN ANALYZE` 显示 Index Scan（不是 Seq Scan）
- [ ] 召回测试全绿
- [ ] 你口头回答：`ef_search` 调大调小分别影响什么？为什么余弦检索前向量要归一化？

---

### D2：BM25 关键词检索

**① 讲（15min）**

我讲：
- TF-IDF 的两个问题：词频无饱和（出现 100 次和 1000 次差别过大）、长文档天然得分高
- BM25 公式逐项拆解：`score = Σ IDF(qi) * (f(qi,D) * (k1+1)) / (f(qi,D) + k1 * (1 - b + b * |D|/avgdl))`
- `k1`（词频饱和速度，典型 1.2~2.0）、`b`（长度归一化强度，典型 0.75）
- PG 全文检索：`tsvector`/`tsquery` + GIN 索引；PG 内置分词不理解中文（zhparser/pg_jieba 扩展配置太重），教学用 `simple` 配置 + `pg_trgm` 三元组兜底
- 向量检索和关键词检索的互补性（语义泛化 vs 字面精确）

**② 演（15min）**

我演示：
```sql
-- tsvector 列 + 触发器维护
-- 注意：to_tsvector 不是 IMMUTABLE 函数，不能用作生成列（GENERATED ALWAYS AS 会报错），
-- 所以用触发器维护 content_tsv
ALTER TABLE chunks ADD COLUMN content_tsv tsvector;

CREATE OR REPLACE FUNCTION chunks_tsv_update() RETURNS trigger AS $$
BEGIN
  NEW.content_tsv := to_tsvector('simple', coalesce(NEW.content, ''));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_chunks_tsv
BEFORE INSERT OR UPDATE OF content ON chunks
FOR EACH ROW EXECUTE FUNCTION chunks_tsv_update();

CREATE INDEX idx_chunks_tsv ON chunks USING gin(content_tsv);
UPDATE chunks SET content_tsv = to_tsvector('simple', content);  -- 回填存量数据

-- 中文没有天然词边界，simple 配置不会分词 → 加 pg_trgm 三元组索引支持 ILIKE 精确查找
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_chunks_content_trgm ON chunks USING gin(content gin_trgm_ops);

-- 关键词检索（ts_rank 近似 BM25 排序；精确编号/英文走 tsvector）
SELECT c.id, c.content, ts_rank(c.content_tsv, q) AS score
FROM chunks c, plainto_tsquery('simple', 'SKU-12345') q
WHERE c.content_tsv @@ q
ORDER BY score DESC
LIMIT 5;

-- 中文关键词走三元组 ILIKE
SELECT id, content, similarity(content, '保修') AS score
FROM chunks
WHERE content ILIKE '%' || '保修' || '%'
ORDER BY score DESC
LIMIT 5;
```

> **说明：** 中文全文检索生产环境建议用 Elasticsearch，这里用 PG 简化演示。
> 教学场景的关键词命中（产品编号、人名等）用上面的 tsvector + pg_trgm 组合足够。

```python
# backend/app/rag/bm25_search.py
from app.rag.schemas import ChunkHit


async def bm25_search(db, query: str, top_k: int = 5) -> list[ChunkHit]:
    stmt = text("""
        SELECT c.id, c.content, ts_rank(c.content_tsv, q) AS score
        FROM chunks c, plainto_tsquery('simple', :query) q
        WHERE c.content_tsv @@ q
        ORDER BY score DESC LIMIT :top_k
    """)
    rows = (await db.execute(stmt, {"query": query, "top_k": top_k})).all()
    return [ChunkHit(id=r.id, content=r.content, score=float(r.score)) for r in rows]
```

**③ 练（60min）**

你做：
1. 写 Alembic 迁移：加 `content_tsv` 列 + 更新触发器 + GIN 索引（再加 pg_trgm 三元组索引）
2. 实现 `bm25_search(query, top_k)`
3. 写测试：插入含产品编号 "SKU-12345" 的 chunk，断言精确关键词能命中
4. 写对比测试：同一个编号 query，向量检索 miss 而 BM25 命中（证明互补性）
5. 分支 `feat/bm25-search`，commit：`feat: add bm25 keyword search with pg fts`

**④ 审（15min）**

我检查：
- `content_tsv` 是否用触发器维护（而不是应用层手动维护，会忘更新）；能否解释为什么不能用生成列（`to_tsvector` 不是 IMMUTABLE）
- 是否建了 GIN 索引（否则 `@@` 全表扫描）
- 中文关键词是否走 pg_trgm ILIKE 通路（不依赖 zhparser 扩展）
- 测试是否证明了"BM25 能救向量检索的漏"

**⑤ 验（15min）**

验收标准：
- [ ] 精确关键词（产品编号/人名）能命中
- [ ] 对比测试：编号类 query BM25 命中、向量检索 miss
- [ ] `EXPLAIN ANALYZE` 显示 Bitmap Index Scan on GIN
- [ ] 你口头回答：BM25 里 `b=0` 意味着什么？为什么不能只用 BM25 不用向量？

---

### D3：RRF 混合检索

**① 讲（15min）**

我讲：
- 为什么不能直接加权融合分数：两路 score 量纲完全不同（余弦相似度 [0,1] vs ts_rank 无上界）
- RRF（Reciprocal Rank Fusion）只依赖排名不依赖分数：`score(d) = Σ 1/(k + rank_i(d))`，k=60
- k 的作用：k 越大，排名靠前和靠后的文档得分差距越小（抑制头部效应）；k=60 是论文经验值
- RRF 的优点：无需调权、对分数分布不敏感、可轻松扩展到三路以上

**② 演（15min）**

我演示：
```python
# backend/app/rag/hybrid_search.py
import asyncio
from collections import defaultdict

from app.rag.schemas import ChunkHit


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """rankings: 多路召回结果，每路是 chunk_id 按相关性排序的列表"""
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


async def hybrid_search(db, query: str, top_k: int = 10, recall: int = 50) -> list[ChunkHit]:
    vec, bm = await asyncio.gather(  # 两路并发召回，不是串行等待
        vector_search(db, query, top_k=recall),
        bm25_search(db, query, top_k=recall),
    )
    fused = rrf_fuse([[h.id for h in vec], [h.id for h in bm]])
    pool = {h.id: h for h in vec + bm}
    return [ChunkHit(id=cid, content=pool[cid].content, score=s)
            for cid, s in fused[:top_k]]
```

我现场手算一个例子：文档 A 在两路都排第 1 → `2/(60+1) = 0.0328`；文档 B 只在一路排第 1 → `1/61 = 0.0164`，直观感受融合逻辑。

**③ 练（60min）**

你做：
1. 实现 `rrf_fuse()`（纯函数，不依赖 DB）
2. 实现 `hybrid_search()`（两路并发召回：`asyncio.gather`）
3. 单元测试：手写 3 路排名数据，断言 RRF 排序结果（含只出现在一路的文档）
4. 集成测试：构造"语义相关但无关键词"+"含关键词但语义弱"两组数据，断言混合检索都能召回
5. 分支 `feat/hybrid-search`，commit：`feat: add rrf hybrid search`

**④ 审（15min）**

我检查：
- 两路召回是否并发（`asyncio.gather`）还是串行等待
- RRF 是否用的排名而不是分数（检查有没有人偷偷加权 score）
- 召回深度 recall 是否大于最终 top_k（先粗召回 50 再融合取 10）
- 单元测试是否覆盖了"文档只被一路召回"的边界

**⑤ 验（15min）**

验收标准：
- [ ] 融合后排序优于任意单路（集成测试证明）
- [ ] RRF 单元测试全绿，手算结果与代码一致
- [ ] 两路召回并发执行（日志时间戳证明）
- [ ] 你口头回答：k=1 和 k=1000 分别会怎样？为什么 RRF 不用归一化分数？

---

### D4：Rerank（Cross-Encoder）

**① 讲（15min）**

我讲：
- Bi-Encoder（双塔）：query 和 doc 各自编码再算相似度 → 可预计算、快，但无交互、精度低
- Cross-Encoder：`[CLS] query [SEP] doc [SEP]` 拼接后进同一个 Transformer → 有深度交互、精度高，但每对都要现算、无法预计算
- 所以必须两级：粗排（Bi-Encoder/BM25 召回 50）→ 精排（Cross-Encoder 打分取 5）
- bge-reranker-v2-m3：多语言、支持中文、可本地跑也可 API
- 延迟账：50 个候选 × Cross-Encoder 一次前向 ≈ 200-400ms，这是 RAG 延迟大头

**② 演（15min）**

我演示：
```python
# backend/app/rag/reranker.py
from sentence_transformers import CrossEncoder

_reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)

def rerank(query: str, chunks: list[str], top_n: int = 5) -> list[tuple[int, float]]:
    """返回 (原索引, 相关性分数)，按分数降序"""
    if not chunks:
        return []
    scores = _reranker.predict([(query, c) for c in chunks])
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    return [(i, float(scores[i])) for i in order[:top_n]]
```

```python
# 串进 hybrid_search（hybrid_search 返回 list[ChunkHit]）
fused = await hybrid_search(db, query, top_k=50)
contents = [hit.content for hit in fused]
top = rerank(query, contents, top_n=5)
final = [(fused[i], score) for i, score in top]  # list[tuple[ChunkHit, float]]
```

**③ 练（60min）**

你做：
1. 实现 `reranker.py`（模型路径走配置，支持本地/API 切换）
2. 把 rerank 串进检索管线：hybrid(50) → rerank(5)
3. 写精度测试：构造 10 个候选（1 个高度相关 + 9 个干扰），断言 rerank 后相关的进 Top-1
4. 写测试：rerank 前后对比，Top-5 命中率提升
5. 加分项：模型加载做成单例（不要每次请求都加载）
6. 分支 `feat/rerank`，commit：`feat: add cross-encoder rerank stage`

**④ 审（15min）**

我检查：
- 模型是否单例加载（每次请求加载 = 灾难）
- rerank 的输入是否来自粗排结果（不是重新查库）
- 空候选/单候选边界是否处理
- 测试是否真的度量了"精度提升"（有 before/after 对比）

**⑤ 验（15min）**

验收标准：
- [ ] Rerank 后 Top-5 精度优于不 Rerank（测试数据说话）
- [ ] 干扰项测试：相关文档被排到 Top-1
- [ ] 模型只加载一次（日志证明）
- [ ] 你口头回答：为什么 Cross-Encoder 不能用来做全库检索？rerank 延迟太高怎么优化？

---

### D5：Prompt 拼接 + token 预算控制

**① 讲（15min）**

我讲：
- LLM 客户端：凡是 OpenAI 兼容协议的服务（OpenAI/通义 DashScope/vLLM 等）都能用 httpx 封装同一套客户端；配置三件套 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 走 Settings，换供应商只改配置
- 流式输出：LLM 的 `stream=true` 返回逐块 SSE，客户端用 async generator 逐块 yield，明天 D6 的 SSE 端点直接复用它
- token 预算分配：`模型窗口 = system prompt + 参考资料 + 历史对话 + 用户问题 + 预留输出`，先扣固定的，剩下的才是参考资料预算
- 为什么按 token 算不是按字符算（中文 1 字 ≈ 1-2 token，英文 1 词 ≈ 1.3 token）
- tiktoken 计数原理（BPE 分词）
- 引用标注约定：每段资料前加 `[1]`、`[2]` 编号，LLM 回答中引用同样编号，前端据此渲染来源

**② 演（15min）**

我演示：
```python
# backend/app/core/config.py — Settings 增加 LLM 配置三件套
class Settings(BaseSettings):
    ...
    llm_api_key: str
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
```

```python
# backend/app/services/llm.py — OpenAI 兼容协议客户端（httpx 封装）
import json
from collections.abc import AsyncIterator

import httpx

from app.core.config import settings


class LLMClient:
    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=60,
        )

    def _body(self, messages: list[dict], stream: bool) -> dict:
        return {"model": settings.llm_model, "messages": messages, "stream": stream}

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """流式：async generator 逐块 yield 增量文本"""
        async with self._client.stream(
            "POST", "/chat/completions", json=self._body(messages, stream=True),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":  # OpenAI 协议的上游流结束标记
                    break
                delta = json.loads(data)["choices"][0]["delta"]
                if delta.get("content"):
                    yield delta["content"]

    async def complete(self, prompt: str) -> str:
        """非流式：Query Rewriting / 摘要等短回复用"""
        resp = await self._client.post(
            "/chat/completions",
            json=self._body([{"role": "user", "content": prompt}], stream=False),
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


llm = LLMClient()  # 模块级单例
```

```python
# backend/app/rag/prompt_builder.py
import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(_enc.encode(text))

SYSTEM_PROMPT = "你是知识库助手。仅根据【参考资料】回答，用 [n] 标注引用。不知道就说不知道。"

def build_prompt(question: str, chunks: list[str], history: list[dict],
                 window: int = 8192, reserve_output: int = 1024) -> tuple[list[dict], list[int]]:
    budget = window - reserve_output
    budget -= count_tokens(SYSTEM_PROMPT) + count_tokens(question)
    budget -= sum(count_tokens(m["content"]) for m in history)

    picked: list[int] = []
    ref_parts: list[str] = []
    for i, c in enumerate(chunks):
        part = f"[{i + 1}] {c}"
        cost = count_tokens(part)
        if budget - cost < 0:
            break
        budget -= cost
        picked.append(i)
        ref_parts.append(part)

    user = "【参考资料】\n" + "\n".join(ref_parts) + f"\n\n【问题】{question}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, *history,
            {"role": "user", "content": user}], picked
```

**③ 练（60min）**

你做：
1. Settings 加 `llm_api_key` / `llm_base_url` / `llm_model`，实现 `LLMClient`（httpx 封装 OpenAI 兼容协议，`stream()` 是 async generator）
2. 实现 `prompt_builder.py`（含 `count_tokens` + `build_prompt`）
3. 测试：塞 50 个 chunks，断言最终 messages 总 token < window
4. 测试：预算不够时按相关性顺序截断（低分的被丢弃，不是随机丢）
5. 测试：引用编号连续且与返回的 picked 索引对应
6. 测试：history 为空 / history 本身就超预算的边界
7. 测试：Mock httpx 响应，断言 `LLMClient.stream()` 逐块解析出增量文本
8. 分支 `feat/prompt-builder`，commit：`feat: add prompt builder and llm client with token budget`

**④ 审（15min）**

我检查：
- 预算扣减顺序是否正确（先扣固定的 system/question/history，剩余给资料）
- 是否预留了输出 token（新手常忘，导致模型被截断）
- 截断是"整段丢弃"还是"切半段"（应整段丢，半段资料会误导模型）
- 测试是否真的用 tiktoken 验证总长，而不是只数 chunks 个数

**⑤ 验（15min）**

验收标准：
- [ ] 任何输入下 messages 总 token 不超窗口
- [ ] 来源标注正确：picked 索引 ↔ prompt 中 [n] 编号一一对应
- [ ] 边界测试全绿（空资料/资料全超预算/history 超长）
- [ ] 你口头回答：为什么按 token 不按字符？预留输出不够会发生什么？

---

### D6：SSE 流式生成 + 引用标注

**① 讲（15min）**

我讲：
- SSE 协议格式：`Content-Type: text/event-stream`，每条消息 `data: ...\n\n`
- SSE vs WebSocket：SSE 单向、基于 HTTP、自动重连、天然过代理；问答场景只需要服务端推，够用
- 事件协议（与 API_SPEC 对齐，字段全 snake_case）：`sources`（1 次，先于正文）→ `token`（N 次）→ `done`（1 次，必须是最后一条）
- 流式引用策略：先推 `sources` 事件（前端立刻渲染来源卡片），再逐 token 推正文
- FastAPI 用 `StreamingResponse` + async generator 实现

**② 演（15min）**

我演示：
```python
# backend/app/api/chat.py
import json
from fastapi.responses import StreamingResponse

@app.post("/chat")
async def chat(req: ChatRequest, db=Depends(get_db)):
    async def event_stream():
        hits = await full_retrieve(db, req.question)          # hybrid + rerank
        messages, picked = build_prompt(req.question, [h.content for h in hits], req.history)
        # ① sources 先推：前端可立即渲染来源卡片（先于 token）
        sources = [{"chunk_id": hits[i].id, "content": hits[i].content[:100],
                    "score": hits[i].score} for i in picked]
        yield sse({"type": "sources", "sources": sources})
        # ② token 增量推送
        async for token in llm.stream(messages):
            yield sse({"type": "token", "content": token})
        # ③ done 收尾（message_id/token_count 在 W4 消息落库后填真实值）
        yield sse({"type": "done", "message_id": 0, "token_count": 0})

    return StreamingResponse(event_stream(), media_type="text/event-stream")

def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

```bash
# 验证
curl -N -X POST localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"question": "保修期多久？", "history": []}'
```

**③ 练（60min）**

你做：
1. 实现 `POST /chat` SSE 端点（串起 D1-D5 全部成果）
2. 事件类型：`sources`（1 次）→ 多个 `token` → `done`（1 次），字段全 snake_case
3. 错误处理：检索为空时先推 `{"type": "sources", "sources": []}`，再推 `token` 回复"知识库中未找到相关内容"，不能挂起
4. 写测试：用 httpx 流式读取，断言事件顺序（sources 先于 token，done 收尾）
5. 用 `curl -N` 手工验证打字机效果
6. 分支 `feat/chat-sse`，commit：`feat: add sse streaming chat endpoint`

**④ 审（15min）**

我检查：
- generator 里异常是否被吞掉（客户端会永远等待 → 必须 try/except 后推 error 事件）
- 是否每个事件都 `\n\n` 结尾（少一个换行前端就卡住）
- `ensure_ascii=False`（否则中文变成 `\uXXXX`）
- 测试是否真的逐条解析 SSE 事件（不是把整个 body 当 JSON 读）

**⑤ 验（15min）**

验收标准：
- [ ] `curl -N` 看到逐 token 输出（打字机效果）
- [ ] sources 事件先到达，包含 chunk_id、content 摘要和 score
- [ ] 检索为空时不挂起，正常返回兜底回复
- [ ] 流式测试全绿
- [ ] 你口头回答：SSE 为什么不用 WebSocket？流式中途客户端断开，服务端会发生什么？

---

### D7：周复盘 + 延迟预算分配

**教学内容：**

1. **延迟预算分配**（我讲 + 你算）：
   - 端到端目标：首 token < 2s。拆预算：embedding 100ms + 双路召回（并发取 max）80ms + RRF 5ms + rerank 300ms + prompt 拼接 10ms + LLM 首 token 800ms ≈ 1.3s，留 700ms 余量
   - 你给每一步定 SLO，超预算的步骤要说出优化方案

2. **耗时实测**（你写，我审）：
   ```python
   # 计时装饰器，把每步耗时打进结构化日志
   import time, functools

   def timed(stage: str):
       def deco(fn):
           @functools.wraps(fn)
           async def wrapper(*args, **kwargs):
               t0 = time.perf_counter()
               result = await fn(*args, **kwargs)
               logger.info("latency", extra={"stage": stage, "ms": (time.perf_counter() - t0) * 1000})
               return result
           return wrapper
       return deco
   ```
   - 跑 20 次真实 query，用 matplotlib 画每步耗时饼图 + P50/P99 表

3. **画 RAG 全链路图**（你画，我审）：
   - Query → 双路召回 → RRF → Rerank → Prompt → LLM → SSE，每步标注实测耗时

4. **自测**（我问，你答）：
   - 为什么混合检索优于单路？举一个单路失败的真实 case
   - RRF 的 k=60 改成 k=1 会怎样？
   - Rerank 延迟占比多少？如果预算砍半你先砍哪里？
   - SSE 连接中途断了，你的服务端代码会发生什么？

---

## W4：对话管理 + API 规范

### 教学目标

学完本周你能：
- 设计会话/消息数据模型，支持多轮对话历史
- 用滑动窗口 + 摘要控制多轮上下文 token
- 用 LLM 做 Query Rewriting 解决指代问题
- 把检索参数做成知识库级配置
- 输出规范的 OpenAPI 文档和统一错误码，全项目覆盖率 > 80%

---

### D1：会话 CRUD + 消息历史

**① 讲（15min）**

我讲：
- 读 MaxKB 的会话模型源码，看它怎么组织 conversation/message/chat 三层
- 数据模型设计：Conversation（会话元信息）1-N Message（单条消息）
- 为什么消息要存 role（user/assistant/system）
- 为什么删除用软删除（is_deleted 标记）：审计 + 误删恢复
- 列表接口的分页设计（cursor vs offset）

**② 演（15min）**

我演示：
```python
# backend/app/models/conversation.py
class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kb_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"))
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    is_deleted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=lambda: datetime.datetime.now(datetime.timezone.utc))

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # 引用来源快照（与 SSE sources 事件同构）
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=lambda: datetime.datetime.now(datetime.timezone.utc))
```

> **注意：** `KnowledgeBase` 模型已在 W2D1 创建（Document 归属知识库时就建了表），这里只引用它的外键，不要重复建表。

```
POST   /conversations                 创建会话
GET    /conversations?cursor=&limit=  会话列表（分页）
GET    /conversations/{id}/messages   消息历史
DELETE /conversations/{id}            软删除
```

**③ 练（60min）**

你做：
1. 实现 Conversation + Message 模型 + Alembic 迁移
2. 实现 4 个 API（创建/列表/历史/软删除）
3. `POST /chat` 改造：接收 conversation_id，问答双方消息落库
4. 测试：创建 → 聊 2 轮 → 历史接口返回 4 条且顺序正确
5. 测试：软删除后列表不可见，但数据库记录还在
6. 测试：不能访问别人的会话（404，不是 403 —— 不暴露资源存在）
7. 分支 `feat/conversations`，commit：`feat: add conversation crud with message history`

**④ 审（15min）**

我检查：
- 外键和索引是否齐全（conversation_id 没索引 = 历史查询全表扫）
- 是否软删除（物理 DELETE 直接打回）
- 消息是否按 created_at + id 排序（只按时间戳在毫秒级会乱序）
- 跨用户访问是否返回 404

**⑤ 验（15min）**

验收标准：
- [ ] 创建/列表/删除/历史查询全部 curl 走通
- [ ] 聊天后消息自动落库，历史顺序正确
- [ ] 软删除生效
- [ ] 测试全绿，覆盖率 > 90%（本模块）
- [ ] 你口头回答：为什么跨用户访问返回 404 而不是 403？分页为什么用 cursor 不用 offset？

---

### D2：多轮上下文管理（滑动窗口 + 摘要）

**① 讲（15min）**

我讲：
- 问题：20 轮对话 ≈ 8k token，直接塞进 prompt 会挤爆参考资料预算
- 策略一：滑动窗口 —— 只保留最近 N 轮，简单但丢长期信息
- 策略二：摘要压缩 —— 把旧对话让 LLM 总结成一段，保留语义丢细节
- 组合拳：最近 5 轮原文 + 更早的压缩成摘要
- 摘要触发时机：窗口滑出时异步生成，不阻塞当前请求

**② 演（15min）**

我演示：
```python
# backend/app/services/context_manager.py
def sliding_window(messages: list[Message], max_tokens: int = 1500) -> list[dict]:
    """从新到旧贪心装填，装不下即停"""
    window, used = [], 0
    for m in reversed(messages):
        cost = count_tokens(m.content) + 4  # role 开销
        if used + cost > max_tokens:
            break
        window.insert(0, {"role": m.role, "content": m.content})
        used += cost
    return window

async def summarize_old(messages: list[Message], llm) -> str:
    text = "\n".join(f"{m.role}: {m.content}" for m in messages)
    return await llm.complete(f"用 100 字以内总结这段对话的关键信息：\n{text}")
```

**③ 练（60min）**

你做：
1. 实现 `sliding_window()`（纯函数）
2. 实现 `summarize_old()`（Mock LLM 测试）
3. 实现组合策略：`build_context(history)` = 摘要（如有）+ 最近 N 轮原文
4. Conversation 模型加 `summary` 字段（迁移）
5. 测试：构造 20 轮对话，断言输出 token < 预算且最近 5 轮完整保留
6. 测试：窗口滑出的消息触发了摘要更新
7. 分支 `feat/context-window`，commit：`feat: add sliding window context with summary`

**④ 审（15min）**

我检查：
- 窗口装填是否从新到旧（保新弃旧，不是保旧弃新）
- token 计数是否包含 role 开销
- 摘要生成是否异步（同步会让当前请求多等一次 LLM）
- 测试是否用真实 token 计数验证预算

**⑤ 验（15min）**

验收标准：
- [ ] 20 轮对话构造的 context 不超预算
- [ ] 最近 5 轮原文完整，更早的变成摘要
- [ ] 摘要测试全绿（Mock LLM）
- [ ] 你口头回答：滑动窗口和摘要各丢什么信息？为什么摘要要异步？

---

### D3：Query Rewriting（LLM 改写指代）

**① 讲（15min）**

我讲：
- 问题："它的价格是多少？" —— "它" 指什么？检索引擎不知道
- 解法：用 LLM 结合对话历史把当前问题改写成独立问题："XX 产品的价格是多少？"
- 改写 prompt 设计：给历史 + 当前问题，要求输出"不依赖上下文即可理解的问题"
- 不改写的情况：问题本身已独立 → LLM 原样返回
- 成本权衡：多一次 LLM 调用（~300ms），可用小模型

**② 演（15min）**

我演示：
```python
# backend/app/rag/query_rewriter.py
REWRITE_PROMPT = """根据对话历史，把用户最新的问题改写成一个独立、完整、不依赖上下文的问题。
如果问题本身已经独立，原样返回。只输出改写后的问题，不要解释。

对话历史：
{history}

用户问题：{question}

改写后："""

async def rewrite_query(llm, question: str, history: list[dict]) -> str:
    if not history:
        return question
    text = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])
    rewritten = await llm.complete(REWRITE_PROMPT.format(history=text, question=question))
    return rewritten.strip() or question
```

**③ 练（60min）**

你做：
1. 实现 `rewrite_query()`
2. 串进 /chat 管线：history → rewrite → retrieve（用改写后的 query 检索）
3. 测试（Mock LLM）：
   - "它的价格" + 历史提到 "MaxKB Pro" → 改写为 "MaxKB Pro 的价格"
   - 无历史 → 原样返回
   - LLM 返回空 → 兜底用原问题
4. 集成测试：多轮对话第二轮用指代词，仍能检索到第一轮的相关文档
5. 分支 `feat/query-rewrite`，commit：`feat: add llm query rewriting for coreference`

**④ 审（15min）**

我检查：
- 检索用的是改写后的 query（不是原问题 —— 新手最常串错）
- LLM 失败/超时是否兜底到原问题（改写是增强不是关键路径）
- 历史截断是否合理（不把 20 轮全塞给改写 LLM）
- prompt 是否要求"只输出问题"（否则 LLM 会输出"改写后的问题是：..."）

**⑤ 验（15min）**

验收标准：
- [ ] "它的价格" → "XX 产品的价格"（测试证明）
- [ ] 独立问题不被过度改写
- [ ] LLM 挂掉时降级到原问题，请求不失败
- [ ] 你口头回答：改写为什么放在检索前而不是 prompt 拼接前？用小模型改写的权衡？

---

### D4：知识库配置（top_k/温度/prompt 模板）

**① 讲（15min）**

我讲：
- 读 MaxKB 知识库配置源码：每个知识库独立的检索/生成参数
- 为什么参数要按知识库走：FAQ 库要低温度高精确，创意写作库要高温度
- 配置项设计：top_k、similarity_threshold、temperature、prompt_template、是否启用 rerank
- 配置校验：temperature ∈ [0,2]、top_k ∈ [1,50]，用 pydantic 约束
- 默认值策略：缺省给合理默认，用户只覆盖关心的

**② 演（15min）**

我演示：
```python
# backend/app/models/knowledge_base.py
# 表在 W2D1 已创建（id, name, created_at），今天用迁移加检索/生成配置字段
class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    top_k: Mapped[int] = mapped_column(default=5)
    temperature: Mapped[float] = mapped_column(default=0.3)
    enable_rerank: Mapped[bool] = mapped_column(default=True)
    prompt_template: Mapped[str] = mapped_column(
        Text, default="仅根据【参考资料】回答用户问题。\n{question}")

# schemas 里做校验
class KBConfigUpdate(BaseModel):
    top_k: int = Field(ge=1, le=50, default=5)
    temperature: float = Field(ge=0.0, le=2.0, default=0.3)
```

```python
# /chat 里读配置驱动管线
kb = await get_kb(db, req.kb_id)
hits = await full_retrieve(db, rewritten, top_k=kb.top_k, rerank=kb.enable_rerank)
```

**③ 练（60min）**

你做：
1. KnowledgeBase 模型（W2D1 已建）加配置字段：top_k / temperature / enable_rerank / prompt_template + 迁移
2. 实现知识库 CRUD API（`POST/GET/PATCH/DELETE /knowledge-bases`）
3. 检索管线参数化：top_k/rerank 开关从知识库配置读取
4. prompt_template 支持 `{question}` 占位符渲染
5. 测试：两个知识库不同 top_k，同一 query 返回条数不同
6. 测试：非法配置（temperature=5）返回 422
7. 分支 `feat/kb-config`，commit：`feat: add per-kb retrieval and generation config`

**④ 审（15min）**

我检查：
- 配置是否真的驱动了管线（改 top_k 后检索条数真的变了）
- pydantic 校验边界是否齐全
- prompt_template 渲染是否防注入（用户模板不能覆盖 system prompt 的安全约束）
- 删除知识库时 chunks 是否级联清理

**⑤ 验（15min）**

验收标准：
- [ ] 不同知识库不同 top_k/温度生效（测试证明）
- [ ] 非法配置返回 422 + 清晰错误信息
- [ ] prompt 模板渲染正确
- [ ] 你口头回答：temperature=0 和 1 的区别？配置存数据库 vs 存配置文件的取舍？

---

### D5：OpenAPI 文档 + 统一错误码

**① 讲（15min）**

我讲：
- FastAPI 自动生成 OpenAPI 的原理：从类型注解 + pydantic schema 推导
- 让文档可用：每个端点写 summary/description/response_model/status_code + tags 分组
- 统一错误格式：`{"code": "AUTH_EXPIRED", "message": "...", "request_id": "..."}`
- 错误码规范：字符串码（可读）+ HTTP 状态码（机器可路由），双轨制
- 全局异常处理器：业务异常 → 统一格式，兜底 500 不泄露堆栈
- 版本化：业务路由挂到 `/v1` 前缀下，对外 base URL 固定为 `/api/v1`（`/api` 前缀由 vite 代理/Nginx 剥掉，见 API_SPEC）—— 前端下周联调，今天必须定死

**② 演（15min）**

我演示：
```python
# backend/app/core/errors.py
class BizError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status

class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str

@app.exception_handler(BizError)
async def biz_error_handler(request: Request, exc: BizError):
    return JSONResponse(status_code=exc.status, content={
        "code": exc.code, "message": exc.message,
        "request_id": request_id_var.get(),
    })

@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.exception("unhandled error")
    return JSONResponse(status_code=500, content={
        "code": "INTERNAL", "message": "服务器内部错误",
        "request_id": request_id_var.get(),
    })
```

```python
# 端点文档化示例
@router.post("/chat", summary="流式问答", status_code=200, tags=["chat"],
             responses={429: {"model": ErrorResponse}})
```

```python
# backend/app/main.py — 业务路由统一挂到 /v1
from app.api import api_router  # 聚合 auth/knowledge-bases/documents/chat/conversations

app.include_router(api_router, prefix="/v1")
# 开发环境 vite 代理 /api → 剥掉 /api 前缀；生产 Nginx location /api/ → 剥掉 /api
# 所以对外 base URL 统一是 /api/v1（与 docs/API_SPEC.md 一致）
```

**③ 练（60min）**

你做：
1. 定义错误码表（docs/error_codes.md）：AUTH_*、KB_*、QUOTA_*、INTERNAL
2. 实现 BizError + 两个全局异常处理器
3. 把前几周散落的 HTTPException 全部替换为 BizError + 错误码
4. 给所有端点补齐 summary/description/response_model/tags
5. 测试：触发各类异常，断言响应格式统一且含 request_id
6. 测试：500 兜底不泄露堆栈信息
7. 分支 `feat/api-convention`，commit：`feat: unify error codes and openapi docs`

**④ 审（15min）**

我检查：
- Swagger UI（/docs）里每个端点是否都有中文描述和错误响应示例
- 是否还有裸 HTTPException 漏网（grep 检查）
- 500 处理器是否记了日志但没把异常信息返给客户端
- request_id 是否贯穿错误响应（方便排查）

**⑤ 验（15min）**

验收标准：
- [ ] Swagger 完整：所有端点有 summary + 错误响应 schema
- [ ] 任意错误响应都是 `{code, message, request_id}` 格式
- [ ] 500 不泄露堆栈
- [ ] 你口头回答：错误码用字符串还是数字？API 版本管理（/v1）什么时候该引入？

---

### D6：全量集成测试 + 覆盖率冲刺

**① 讲（15min）**

我讲：
- 集成测试 vs 单元测试的分工：单元测逻辑分支，集成测真实链路
- E2E 黄金路径：注册 → 登录 → 建知识库 → 上传文档 → 等待入库 → 提问 → 拿到带引用的回答
- Mock 边界：LLM/Embedding 用 Mock，数据库/Redis 用真实（docker 起测试环境）
- 覆盖率冲刺策略：`pytest --cov-report=term-missing` 找未覆盖行，按模块补齐

**② 演（15min）**

我演示黄金路径集成测试骨架：
```python
# backend/tests/integration/test_golden_path.py
async def test_full_rag_flow(client, test_db, mock_llm):
    # 1. 注册 + 登录
    token = await register_and_login(client, "e2e@test.com")
    h = {"Authorization": f"Bearer {token}"}
    # 2. 建知识库 + 上传文档（文档入库是嵌套路由，W2D1 定的）
    kb_id = (await client.post("/v1/knowledge-bases", json={"name": "faq"}, headers=h)).json()["id"]
    await client.post(f"/v1/knowledge-bases/{kb_id}/documents",
                      files={"file": ("faq.md", FAQ_MD)}, headers=h)
    # 3. 轮询等待入库完成
    await wait_until(lambda: doc_status(client, h) == "ready", timeout=30)
    # 4. 提问
    events = await collect_sse(client, "/v1/chat", {"kb_id": kb_id, "question": "保修期多久？"}, h)
    assert events[0]["type"] == "sources"
    assert "保修" in "".join(e["content"] for e in events if e["type"] == "token")
```

**③ 练（60min）**

你做：
1. 写黄金路径集成测试（上面 4 步全链路）
2. 写失败路径集成测试：未登录提问 401、不存在的知识库 404，并验证所有端点返回统一错误格式（`{code, message, request_id}`；配额 429 在 W6D3 才实现，这里不测）
3. `pytest --cov=app --cov-report=term-missing`，把覆盖率从当前值冲到 > 80%
4. 给 CI 的 `--cov-fail-under` 提到 80
5. 分支 `feat/integration-tests`，commit：`test: add e2e golden path and raise coverage to 80%`

**④ 审（15min）**

我检查：
- 集成测试是否用真实 PG + Redis（不是 SQLite）
- LLM Mock 是否可配置返回（不同测试场景不同回复）
- 覆盖率是否靠"无断言的测试"刷的（刷出来的覆盖率打回）
- 测试之间是否隔离（每个测试独立数据，不依赖执行顺序）

**⑤ 验（15min）**

验收标准：
- [ ] 黄金路径测试一条命令跑通
- [ ] 全项目覆盖率 > 80%（CI 门禁生效）
- [ ] 失败路径测试覆盖 401/404，且所有错误响应为统一格式
- [ ] 你口头回答：哪些代码不值得追覆盖率？Mock LLM 的测试能证明什么、不能证明什么？

---

### D7：周复盘

**教学内容：**

1. **画对话链路图**（你画，我审）：
   - 用户提问 → Query Rewrite → 检索 → Prompt（含滑动窗口历史）→ LLM → SSE → 消息落库
   - 标注每个环节读写了哪张表

2. **API 设计 3 分钟陈述**（你讲，我挑刺）：
   - 资源命名、错误码规范、分页方案、版本策略，一次讲清

3. **Git 复盘**：
   - `git log --oneline --graph` 检查本周分支/commit 规范
   - 检查是否有遗漏的 TODO/FIXME（`grep -rn "TODO" backend/app`）

4. **自测**（我问，你答）：
   - 多轮对话 token 爆了怎么办？你的三级策略是什么？
   - Query Rewriting 挂了会怎样？为什么这样设计？
   - 错误码为什么双轨制（字符串码 + HTTP 状态码）？
   - 集成测试和单元测试的边界你怎么划？

---

## W5：React 前端

### 教学目标

学完本周你能：
- 用 Vite + React + TS 搭建规范前端工程
- 实现 JWT 认证前端全链路（登录/拦截器/无感刷新）
- 完成知识库管理、文档上传、切片预览等核心页面
- 实现 SSE 流式对话界面（打字机 + Markdown + 引用）
- 用 Zustand 管理状态，Playwright 跑 E2E

---

### D1：Vite + React + TS 初始化 + 路由

**① 讲（15min）**

我讲：
- 为什么 Vite（ESM dev server 秒启，Rollup 打包）vs Webpack
- 前端目录约定：`pages/`（路由级）、`components/`（复用）、`api/`（请求层）、`stores/`（状态）、`hooks/`
- React Router v6：`createBrowserRouter` + 布局路由 + 路由守卫思路
- TS 严格模式：`strict: true` 从第一天开

**② 演（15min）**

我演示：
```bash
cd frontend
pnpm create vite@latest . --template react-ts
# 一次性装齐本周用到的依赖（也可以按天分批装）
pnpm add react-router-dom axios zustand react-markdown remark-gfm react-window
pnpm add -D @types/node eslint prettier @playwright/test
```

```ts
// frontend/vite.config.ts — 开发代理：/api → 后端，剥掉 /api 前缀
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),  // /api/v1/chat → /v1/chat
      },
    },
  },
});
```

```tsx
// frontend/src/router.tsx
import { createBrowserRouter, Navigate } from "react-router-dom";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: <RequireAuth><AppLayout /></RequireAuth>,
    children: [
      { index: true, element: <Navigate to="/knowledge-bases" replace /> },
      { path: "knowledge-bases", element: <KnowledgeBaseList /> },
      { path: "chat", element: <ChatPage /> },
    ],
  },
]);

// RequireAuth：无 token 跳 /login
function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem("access_token");
  return token ? <>{children}</> : <Navigate to="/login" replace />;
}
```

**③ 练（60min）**

你做：
1. 初始化 Vite + React + TS 项目（strict 模式）
2. 配 `vite.config.ts` 代理：`/api` → `localhost:8000`，rewrite 剥掉 `/api` 前缀（对外 base URL 是 `/api/v1`）
3. 实现路由表 + AppLayout（侧边栏：知识库/对话）
4. 实现 RequireAuth 路由守卫
5. 配 ESLint + Prettier，加 `pnpm run lint`
6. 分支 `feat/frontend-init`，commit：`feat: init vite react frontend with routing`

**④ 审（15min）**

我检查：
- 代理配置是否正确（开发环境不跨域）
- 路由守卫是否真的拦住了（直接访问 /chat 会跳登录）
- 目录结构是否和后端分层对应
- tsconfig 是否 strict（不是 any 满天飞）

**⑤ 验（15min）**

验收标准：
- [ ] `pnpm run dev` 能跑，页面正常渲染
- [ ] 未登录访问受保护路由跳转 /login
- [ ] `pnpm run lint` 零错误
- [ ] 你口头回答：Vite 开发模式为什么快？代理解决了什么问题？

---

### D2：登录页 + JWT 存储 + axios 拦截器

**① 讲（15min）**

我讲：
- token 存哪：localStorage（简单但怕 XSS）vs httpOnly cookie（防 XSS 但要防 CSRF），本项目的取舍
- axios 请求拦截器：自动附加 Authorization
- 响应拦截器：401 → 用 refresh token 换新 access → 重放原请求（无感刷新）
- 并发 401 的坑：多个请求同时 401 会触发多次 refresh → 要加锁

**② 演（15min）**

我演示：
```ts
// frontend/src/api/client.ts
import axios from "axios";

export const api = axios.create({ baseURL: "/api/v1" });  // 对外 base URL 固定 /api/v1

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshing: Promise<string> | null = null;

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config;
    if (err.response?.status === 401 && !original._retried) {
      original._retried = true;
      refreshing ??= api.post("/auth/refresh", {
        refresh_token: localStorage.getItem("refresh_token"),
      }).then((r) => {
        localStorage.setItem("access_token", r.data.access_token);
        return r.data.access_token;
      }).finally(() => { refreshing = null; });
      const token = await refreshing;
      original.headers.Authorization = `Bearer ${token}`;
      return api(original);
    }
    return Promise.reject(err);
  }
);
```

**③ 练（60min）**

你做：
1. 实现登录页（表单 + 校验 + 错误提示）
2. 登录成功后存双 token + 跳转首页
3. 实现 axios 实例 + 请求/响应拦截器（含无感刷新）
4. 实现登出（清 token + 调后端 /auth/logout + 跳登录页）
5. 测试：access 过期后请求自动刷新重放（用 MSW 或后端短过期时间验证）
6. 分支 `feat/login`，commit：`feat: add login page with jwt refresh interceptor`

**④ 审（15min）**

我检查：
- 并发 401 是否只 refresh 一次（有没有加锁/Promise 复用）
- refresh 也失败时是否跳转登录页（不是无限循环）
- `_retried` 标记是否防了重放死循环
- 密码框是否 type="password"、表单是否防默认提交刷新

**⑤ 验（15min）**

验收标准：
- [ ] 登录 → 跳转 → 刷新页面不掉线
- [ ] access 过期后无感刷新，用户无感知
- [ ] refresh 过期后跳回登录页
- [ ] 你口头回答：token 存 localStorage 的风险？如果改用 httpOnly cookie 要额外防什么？

---

### D3：知识库列表 + 文档上传

**① 讲（15min）**

我讲：
- 列表页模式：加载态/空态/错误态三态渲染
- 文件上传：`FormData` + `multipart/form-data`，axios 的 `onUploadProgress` 做进度条
- 乐观更新 vs 保守更新：删除用保守（等后端确认），避免闪回
- 组件拆分：页面组件（数据）vs 展示组件（UI）

**② 演（15min）**

我演示：
```tsx
// frontend/src/api/documents.ts
export function uploadDocument(kbId: number, file: File, onProgress: (p: number) => void) {
  const form = new FormData();
  form.append("file", file);
  return api.post(`/knowledge-bases/${kbId}/documents`, form, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (e) => onProgress(Math.round((e.loaded / (e.total ?? 1)) * 100)),
  });
}
```

```tsx
// 列表三态
if (loading) return <Spin />;
if (error) return <ErrorBanner message={error} onRetry={refetch} />;
if (list.length === 0) return <Empty text="暂无知识库" />;
return <KBTable data={list} onDelete={handleDelete} />;
```

**③ 练（60min）**

你做：
1. 实现知识库列表页（三态渲染 + 新建对话框 + 删除确认）
2. 实现文档上传组件（拖拽/点击选择 + 类型校验 + 上传进度条）
3. 实现文档列表（文件名/大小/状态/删除）
4. 上传失败（类型错/超大）显示后端错误信息
5. 分支 `feat/kb-pages`，commit：`feat: add knowledge base list and doc upload pages`

**④ 审（15min）**

我检查：
- 三态是否齐全（新手常只写成功态）
- 上传进度是否真的联动 UI
- 删除是否有确认弹窗（防误删）
- 错误信息是否来自后端 code/message（不是写死的）

**⑤ 验（15min）**

验收标准：
- [ ] 知识库 CRUD 全可用
- [ ] 上传 PDF/MD 显示进度条，完成后出现在列表
- [ ] 上传 .exe 显示"不支持的文件类型"
- [ ] 你口头回答：大文件上传为什么要进度条？乐观更新的适用场景？

---

### D4：切片预览 + 入库进度轮询

**① 讲（15min）**

我讲：
- 轮询 vs WebSocket vs SSE：入库进度是低频短生命周期 → 轮询最简单
- 轮询 etiquette：间隔 2s、页面隐藏暂停（`document.visibilityState`）、组件卸载清理定时器
- 虚拟列表：切片可能上千条，不能全渲染（用 react-window）
- 状态机渲染：pending/processing/ready/failed 四态 UI

**② 演（15min）**

我演示：
```tsx
// frontend/src/hooks/usePolling.ts
export function usePolling(fn: () => Promise<boolean>, intervalMs = 2000) {
  useEffect(() => {
    let timer: number;
    let stopped = false;
    const tick = async () => {
      if (document.visibilityState === "hidden") { timer = setTimeout(tick, intervalMs); return; }
      const done = await fn();  // 返回 true 表示停止
      if (!done && !stopped) timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => { stopped = true; clearTimeout(timer); };
  }, []);
}

// 用法：轮询文档状态直到 ready/failed
usePolling(async () => {
  const { data } = await api.get(`/documents/${docId}`);
  setStatus(data.status);
  return data.status === "ready" || data.status === "failed";
});
```

**③ 练（60min）**

你做：
1. 实现 `usePolling` hook（含可见性暂停 + 卸载清理）
2. 实现文档状态徽标（四态颜色区分），processing 时轮询
3. 实现切片预览页：分页展示 chunks 内容 + 总数
4. 切片列表用虚拟滚动（>200 条时）
5. 测试：轮询在状态变 ready 后停止（不会无限请求）
6. 分支 `feat/chunk-preview`，commit：`feat: add chunk preview with ingest polling`

**④ 审（15min）**

我检查：
- 组件卸载后定时器是否清理（内存泄漏 + setState on unmounted）
- 轮询是否有终止条件（ready/failed 必须停）
- 切走 tab 是否暂停轮询
- 大列表是否虚拟滚动（打开 DevTools 看 DOM 节点数）

**⑤ 验（15min）**

验收标准：
- [ ] 上传后状态实时从 processing → ready
- [ ] ready 后轮询停止（Network 面板无新请求）
- [ ] 切片预览正确显示内容和总数
- [ ] 你口头回答：为什么不用 WebSocket？轮询间隔怎么定？

---

### D5：对话界面（Markdown + SSE 流式 + 引用）

**① 讲（15min）**

我讲：
- 前端消费 SSE：`fetch` + `ReadableStream` 手动解析（EventSource 不支持 POST + 自定义 header，所以不用）
- SSE 解析的坑：一个 `read()` 可能拿到半条或多条事件 → 要维护 buffer 按 `\n\n` 切分
- Markdown 渲染：react-markdown + 代码高亮
- 引用渲染：sources 事件先渲染来源卡片，正文中的 [n] 渲染成可点击角标
- 流式渲染性能：每个 token 都 setState 会卡 → 用 requestAnimationFrame 批量 flush

**② 演（15min）**

我演示：
```ts
// frontend/src/api/chat.ts
export async function streamChat(
  body: object,
  onEvent: (ev: { type: string; data: any }) => void,
  signal?: AbortSignal,
) {
  const res = await fetch("/api/v1/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json",
               Authorization: `Bearer ${localStorage.getItem("access_token")}` },
    body: JSON.stringify(body),
    signal,
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop()!;  // 最后一段可能不完整，留在 buffer
    for (const p of parts) {
      const line = p.replace(/^data: /, "");
      if (!line) continue;
      const event = JSON.parse(line);  // sources / token / done / error
      if (event.type === "done") return;
      onEvent(event);
    }
  }
}
```

**③ 练（60min）**

你做：
1. 实现 `streamChat()`（含 buffer 切分逻辑）
2. 实现对话页：消息列表 + 输入框 + 发送
3. 流式渲染：token 事件追加到当前消息（rAF 批量更新）
4. sources 事件渲染来源卡片，[n] 角标点击展开对应切片
5. Markdown 渲染（代码块高亮）
6. "停止生成"按钮（AbortController）
7. 分支 `feat/chat-ui`，commit：`feat: add streaming chat ui with markdown and citations`

**④ 审（15min）**

我检查：
- buffer 切分逻辑是否正确（半条事件会不会被 JSON.parse 炸掉）
- 停止生成是否真的 abort 了请求
- 流式过程中是否每个 token 都触发整树重渲染（性能）
- XSS：Markdown 渲染是否禁用了原始 HTML（react-markdown 默认安全，别加 dangerouslySetInnerHTML）

**⑤ 验（15min）**

验收标准：
- [ ] 打字机效果流畅（无卡顿）
- [ ] 引用卡片先出现，角标可点击展开切片内容
- [ ] Markdown 代码块正确高亮
- [ ] 停止生成立即生效
- [ ] 你口头回答：为什么不用 EventSource？流式渲染为什么卡，你怎么解决的？

---

### D6：Zustand 状态管理 + 响应式 + E2E

**① 讲（15min）**

我讲：
- 状态管理选型：Context（简单但全量重渲染）vs Redux（重）vs Zustand（轻 + selector 精准订阅）
- store 拆分：authStore / kbStore / chatStore，按领域不按页面
- selector 防重渲染：`useAuthStore(s => s.user)` 只订阅 user
- 响应式：移动断言用 CSS media query，交互用统一的点击目标尺寸
- E2E 用 Playwright：跑真实浏览器打真实后端

**② 演（15min）**

我演示：
```ts
// frontend/src/stores/auth.ts
import { create } from "zustand";

interface AuthState {
  user: { id: number; email: string } | null;
  setUser: (u: AuthState["user"]) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
  logout: () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    set({ user: null });
  },
}));
```

```ts
// frontend/e2e/flow.spec.ts
import { test, expect } from "@playwright/test";

test("golden path", async ({ page }) => {
  await page.goto("/login");
  await page.fill('[name="email"]', "e2e@test.com");
  await page.fill('[name="password"]', "Passw0rd!");
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL(/knowledge-bases/);
  await page.click("text=新建知识库");
  await page.fill('[name="name"]', "e2e-kb");
  await page.click("text=确定");
  await expect(page.locator("text=e2e-kb")).toBeVisible();
});
```

**③ 练（60min）**

你做：
1. 把散落在组件里的全局状态迁到 Zustand（auth/kb/chat 三个 store）
2. 检查所有订阅都用 selector（React DevTools Profiler 验证无多余重渲染）
3. 移动端适配：侧边栏折叠 + 对话页单列布局（375px 断点）
4. 写 Playwright E2E：登录 → 建知识库 → 上传 → 提问 → 看到流式回答
5. 配 `pnpm run e2e`，接入 Makefile
6. 分支 `feat/state-e2e`，commit：`feat: add zustand stores and playwright e2e`

**④ 审（15min）**

我检查：
- store 是否按领域拆分（一个巨型 store 打回）
- 是否有组件直接 `useAuthStore()` 不带 selector（全量订阅）
- E2E 是否打真实后端（不是全 Mock —— 那就退化成组件测试了）
- E2E 是否稳定（跑 3 次不 flaky，用 expect 的自动等待而不是 sleep）

**⑤ 验（15min）**

验收标准：
- [ ] Playwright 跑通完整流程（登录→上传→提问→流式回答）
- [ ] 375px 宽度下布局可用
- [ ] Profiler 验证状态更新无多余重渲染
- [ ] 你口头回答：为什么选 Zustand 不选 Redux？E2E flaky 的常见原因？

---

### D7：周复盘 + tag v0.1.0

**教学内容：**

1. **前端架构 3 分钟陈述**（你讲，我挑刺）：
   - 目录结构、状态管理、请求层、路由守卫、流式渲染方案，一次讲清

2. **打第一个版本 tag**：
   ```bash
   git tag -a v0.1.0 -m "release: v0.1.0 前后端核心功能闭环"
   git push origin v0.1.0
   ```
   - 讲 semantic versioning：MAJOR.MINOR.PATCH 各自什么时候 bump

3. **Git 复盘**：
   - `git log --oneline --graph` 检查本周 commit
   - 前后端联调产生的 "fix" 类 commit 是否该 squash

4. **自测**（我问，你答）：
   - React 状态管理你怎么选型？
   - 流式渲染的性能问题具体是什么，怎么定位怎么解决？
   - JWT 在前端存哪里，被 XSS 了怎么办？
   - E2E 和集成测试的边界？

---

## W6：多租户 + 首次上线

### 教学目标

学完本周你能：
- 设计行级多租户隔离（workspace_id），解释三种隔离方案的取舍
- 实现 RBAC 权限模型 + 鉴权中间件
- 用 Redis + Lua 做 token 配额控制
- 把项目部署到云服务器：Docker + Nginx + HTTPS + 限流
- 完成首次上线 + hotfix 演练

---

### D1：多租户数据模型（workspace_id 隔离）

**① 讲（15min）**

我讲：
- 三种隔离方案：独立数据库（强隔离、贵）→ 独立 schema（中）→ 行级共享表（便宜、靠纪律）
- 行级隔离的核心纪律：每条业务 SQL 必须带 workspace_id 条件，漏一次 = 数据泄露事故
- 读 MaxKB 的多租户设计源码
- 落地手段：所有租户表继承 mixin + 仓储层强制注入过滤，不靠人肉记住
- 迁移策略：存量表加 workspace_id 列 + 回填默认值

**② 演（15min）**

我演示：
```python
# backend/app/models/base.py
class WorkspaceMixin:
    workspace_id: Mapped[int] = mapped_column(index=True, nullable=False)

class KnowledgeBase(WorkspaceMixin, Base):
    __tablename__ = "knowledge_bases"
    ...

# backend/app/core/tenant.py — 从 JWT 解析当前 workspace
async def get_workspace(user=Depends(get_current_user)) -> Workspace:
    return user.current_workspace  # 简化：每用户一个默认 workspace

# 仓储层强制过滤
async def list_kbs(db, workspace_id: int):
    return (await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.workspace_id == workspace_id)
    )).scalars().all()
```

**③ 练（60min）**

你做：
1. 实现 Workspace 模型 + WorkspaceMixin
2. 迁移：knowledge_bases/documents/chunks/conversations 加 workspace_id 并回填
3. 所有查询/写入接口接入 workspace 过滤（Depends 注入）
4. 测试：用户 A 建的知识库，用户 B 列表看不到、详情 404
5. 测试：跨 workspace 的 chunks 不会出现在检索结果里（重要！）
6. 分支 `feat/multi-tenant`，commit：`feat: add workspace-level row isolation`

**④ 审（15min）**

我检查：
- 是否有漏网的查询没带 workspace_id（逐个端点过）
- 检索管线是否也隔离了（chunks 表 join 时最容易漏）
- 迁移回填是否有默认值策略（NOT NULL 列加列必须带 default）
- 测试是否真的用两个用户交叉验证

**⑤ 验（15min）**

验收标准：
- [ ] A 用户看不到 B 的知识库/文档/会话
- [ ] 跨租户检索零泄露（测试证明）
- [ ] 迁移可前进可回滚
- [ ] 你口头回答：行级隔离最大的风险是什么？怎么用制度/工具防？什么时候该升级到独立 schema？

---

### D2：RBAC + 鉴权中间件

**① 讲（15min）**

我讲：
- RBAC 模型：User → Role → Permission，角色是权限的集合
- 本项目三个角色：owner（全权）/ admin（管理成员+知识库）/ member（使用+提问）
- 鉴权两层：认证（你是谁，W1 已做）→ 授权（你能干什么，今天做）
- 实现方式：`require_permission("kb:delete")` 依赖注入装饰器
- 为什么权限码用 `资源:动作` 格式（方便按资源批量授权）

**② 演（15min）**

我演示：
```python
# backend/app/core/rbac.py
ROLE_PERMISSIONS = {
    "owner":  {"kb:create", "kb:read", "kb:update", "kb:delete", "member:manage", "chat:use"},
    "admin":  {"kb:create", "kb:read", "kb:update", "member:manage", "chat:use"},
    "member": {"kb:read", "chat:use"},
}

def require_permission(perm: str):
    async def checker(user=Depends(get_current_user), ws=Depends(get_workspace)):
        role = await get_user_role(ws.id, user.id)
        if perm not in ROLE_PERMISSIONS.get(role, set()):
            raise BizError("FORBIDDEN", "无权限执行此操作", status=403)
        return user
    return checker

@router.delete("/knowledge-bases/{kb_id}", dependencies=[Depends(require_permission("kb:delete"))])
async def delete_kb(...): ...
```

**③ 练（60min）**

你做：
1. 实现 Role/Permission 模型（或常量表）+ workspace_members 表
2. 实现 `require_permission` 依赖
3. 给所有端点挂权限（逐个标注，列清单）
4. 实现成员管理 API：邀请/改角色/移除（仅 owner/admin）
5. 测试矩阵：3 角色 × 关键操作，断言 200/403
6. 测试：member 删知识库 → 403，owner 删 → 200
7. 分支 `feat/rbac`，commit：`feat: add rbac with permission guards`

**④ 审（15min）**

我检查：
- 是否每个写操作端点都有权限守卫（grep 逐个核对）
- 403 响应是否统一错误码格式
- 角色变更是否即时生效（没有缓存旧角色）
- 测试矩阵是否覆盖"admin 不能删 owner"这类边界

**⑤ 验（15min）**

验收标准：
- [ ] 越权操作返回 403 + 统一错误格式
- [ ] 3 角色权限矩阵测试全绿
- [ ] 成员管理 API 可用
- [ ] 你口头回答：RBAC vs ABAC 区别？权限校验放中间件还是端点依赖，各有什么问题？

---

### D3：Token 配额 + 用量统计

**① 讲（15min）**

我讲：
- 为什么需要配额：LLM 调用是真金白银，多租户必须限额
- 配额模型：workspace 月度 token 额度，每次问答按实际消耗扣减
- 并发扣减的坑：先读后写会超卖 → 用 Redis Lua 脚本原子扣减
- 用量统计：每次调用记录 prompt_tokens/completion_tokens（从 LLM 响应 usage 字段拿）
- 超额策略：返回 429 + QUOTA_EXCEEDED 错误码

**② 演（15min）**

我演示：
```lua
-- backend/app/core/quota.lua
-- KEYS[1] = quota:{workspace_id}:{month}  ARGV[1] = 消耗  ARGV[2] = 额度
local used = redis.call('INCRBY', KEYS[1], ARGV[1])
if used > tonumber(ARGV[2]) then
  redis.call('DECRBY', KEYS[1], ARGV[1])  -- 回滚
  return 0
end
redis.call('EXPIRE', KEYS[1], 35 * 24 * 3600)  -- 跨月自动清理
return 1
```

```python
async def check_quota(redis, workspace_id: int, tokens: int) -> bool:
    limit = await get_monthly_limit(workspace_id)
    key = f"quota:{workspace_id}:{datetime.now(timezone.utc):%Y%m}"
    return bool(await redis.eval(QUOTA_LUA, 1, key, tokens, limit))
```

**③ 练（60min）**

你做：
1. 实现 quota.lua + `check_quota()`
2. /chat 前置检查：额度不足返回 429 + QUOTA_EXCEEDED
3. 问答完成后按 usage 实际扣减（不是预估）
4. 实现用量查询 API：`GET /usage`（本月已用/额度）
5. 测试：并发 10 个请求抢剩余额度，断言总扣减不超额（原子性）
6. 测试：超额请求返回 429 且不扣减
7. 分支 `feat/quota`，commit：`feat: add token quota with atomic redis deduction`

**④ 审（15min）**

我检查：
- 扣减是否原子（Lua 单脚本，不是 GET → 判断 → SET 三步）
- 失败回滚是否正确（超额时 DECRBY 还原）
- key 是否有过期时间（否则 Redis 越积越多）
- 并发测试是否真的并发（asyncio.gather，不是顺序调用）

**⑤ 验（15min）**

验收标准：
- [ ] 超额返回 429 + QUOTA_EXCEEDED
- [ ] 并发测试证明不超卖
- [ ] 用量 API 数值准确
- [ ] 你口头回答：为什么不用数据库扣减？LLM 调用中途失败，token 怎么算？

---

### D4：云服务器部署（SSH + Docker）

**① 讲（15min）**

我讲：
- 生产环境和本地差异：镜像 registry、环境变量、数据卷、日志落盘
- SSH 安全：密钥登录、禁密码、禁 root 密码登录、改端口（可选）
- docker-compose.prod.yml：restart: always、资源限制、不挂源码卷
- 部署流程：本地 build → push 镜像（或服务器 pull 代码 build）→ compose up

**② 演（15min）**

我演示：
```bash
# 服务器初始化
ssh root@<server-ip>
adduser deploy && usermod -aG docker deploy
# SSH 密钥登录
ssh-copy-id deploy@<server-ip>
# /etc/ssh/sshd_config: PasswordAuthentication no && systemctl reload sshd

# 部署
scp docker-compose.prod.yml .env.production deploy@<server-ip>:/opt/maxkb/
ssh deploy@<server-ip>
cd /opt/maxkb && docker compose --env-file .env.production up -d
curl -s localhost:8000/health  # {"status":"ok"}
```

```yaml
# docker-compose.prod.yml（关键差异）
services:
  app:
    image: maxkb-app:${IMAGE_TAG}
    restart: always
    env_file: .env.production
    deploy: { resources: { limits: { memory: 1g } } }
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/health"]
      interval: 10s
      retries: 3
```

**③ 练（60min）**

你做：
1. 购买/准备一台云服务器，配置 SSH 密钥登录 + 禁密码
2. 装 Docker + Compose，创建 deploy 用户
3. 写 `docker-compose.prod.yml`（app + db + redis + celery worker）
4. 写 `Makefile` 的 `deploy` target（build → scp → 远程 up）
5. 部署成功：`curl <server-ip>:8000/health` 返回 ok
6. 验证数据持久化：重启容器后数据还在
7. 分支 `feat/prod-deploy`，commit：`feat: add production docker deployment`

**④ 审（15min）**

我检查：
- SSH 是否密钥登录（`ssh -o PasswordAuthentication=no` 测试）
- `.env.production` 是否没进 git（生产密钥绝不能入库）
- 生产 compose 是否挂了源码卷（挂了打回 —— 那是开发模式）
- DB 端口是否对公网暴露（5432 不能开）

**⑤ 验（15min）**

验收标准：
- [ ] SSH 密钥连接成功，密码登录被拒
- [ ] `make deploy` 一条命令部署成功
- [ ] 健康检查通，容器 restart=always 生效
- [ ] 你口头回答：生产镜像为什么不打源码卷？数据库备份策略？

---

### D5：Nginx + HTTPS + 限流

**① 讲（15min）**

我讲：
- Nginx 职责：TLS 终结、静态资源、反向代理、限流
- HTTPS 用 Let's Encrypt + certbot 自动续期
- SSE 过 Nginx 的坑：必须关 buffering（`proxy_buffering off`），否则流式变"一次性"
- 限流：`limit_req_zone` 漏桶算法，按 IP + 按用户双维度
- 安全头：HSTS、X-Content-Type-Options

**② 演（15min）**

我演示：
```nginx
# /etc/nginx/conf.d/maxkb.conf
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;

server {
    listen 80;
    server_name kb.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;                    # nginx ≥ 1.25.1：http2 从 listen 参数改为独立指令
    server_name kb.example.com;
    ssl_certificate     /etc/letsencrypt/live/kb.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kb.example.com/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;

    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://127.0.0.1:8000/;
        proxy_buffering off;            # SSE 必须
        proxy_read_timeout 300s;        # 流式长连接
        proxy_set_header X-Request-ID $request_id;
    }

    location / {
        root /opt/maxkb/frontend/dist;
        try_files $uri /index.html;     # SPA 路由
    }
}
```

```bash
certbot certonly --nginx -d kb.example.com
```

**③ 练（60min）**

你做：
1. 准备域名解析到服务器，certbot 签证书
2. 写 Nginx 配置（HTTPS + 反代 + SPA + SSE 特殊配置）
3. 配限流：30r/s + burst 20
4. 前端 build 产物部署到服务器
5. 验证：https 绿锁、SSE 流式正常、超限返回 503/429
6. 分支 `feat/nginx-https`，commit：`feat: add nginx with https and rate limiting`

**④ 审（15min）**

我检查：
- HTTP 是否 301 跳 HTTPS（不是两个都能访问）
- SSE 端点是否关了 proxy_buffering（现场验证流式）
- 限流 burst 是否 nodelay（解释区别）
- 证书自动续期是否配了（`certbot renew --dry-run`）

**⑤ 验（15min）**

验收标准：
- [ ] https 绿锁，HTTP 自动跳转
- [ ] SSE 打字机效果在生产环境正常
- [ ] ab/wrk 打超过限流阈值，出现 503
- [ ] 你口头回答：漏桶和令牌桶区别？为什么 SSE 要关 buffering？

---

### D6：E2E 跑生产环境

**① 讲（15min）**

我讲：
- 为什么要对生产跑 E2E：本地绿不代表线上绿（网络/证书/限流/Nginx 差异）
- 生产 E2E 纪律：只用专用测试账号、只建测试数据、跑完清理、不打破坏性操作
- Playwright 切环境：baseURL 走环境变量
- 冒烟测试集：从全量 E2E 里挑 5 分钟能跑完的核心路径

**② 演（15min）**

我演示：
```ts
// frontend/playwright.config.ts
export default defineConfig({
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
  },
});
```

```bash
# 本地跑全量
pnpm run e2e
# 对生产跑冒烟集
E2E_BASE_URL=https://kb.example.com pnpm exec playwright test --grep @smoke
```

**③ 练（60min）**

你做：
1. 给 E2E 用例打标签：@smoke（核心 5 条）/ @full
2. Playwright 配置支持环境变量切 baseURL
3. 创建生产专用测试账号 + 测试知识库
4. 对生产跑 @smoke 全绿
5. 写清理脚本：测试数据自动删除
6. 分支 `feat/prod-e2e`，commit：`test: add smoke e2e against production`

**④ 审（15min）**

我检查：
- 生产 E2E 是否用了专用账号（不是真实用户数据）
- 清理逻辑是否可靠（测试知识库会不会越积越多）
- @smoke 是否真的 5 分钟内跑完
- 有没有对生产做危险操作（删库/压测类用例必须排除）

**⑤ 验（15min）**

验收标准：
- [ ] Playwright 对真实生产服务器全绿
- [ ] 冒烟集 < 5 分钟
- [ ] 测试数据有清理
- [ ] 你口头回答：生产 E2E 和压测的区别？生产 E2E 失败了你的排查路径？

---

### D7：周复盘 + hotfix 演练

**教学内容：**

1. **hotfix 演练**（我埋雷，你排障）：
   - 我在生产配置里埋一个 bug（如错误的 CORS 配置）
   - 你走完 hotfix 全流程：发现问题 → `git checkout -b hotfix/xxx main` → 修复 → 测试 → 合并 → `make deploy` → 验证恢复
   - 计时：从发现到恢复 < 15 分钟

2. **画生产架构图**（你画，我审）：
   - Client → Nginx（TLS/限流）→ FastAPI → PG/Redis + Celery Worker，标注每个组件部署在哪

3. **上线 checklist 沉淀**（你写）：
   - 把本周部署踩的坑写成 `docs/deploy_checklist.md`

4. **自测**（我问，你答）：
   - 多租户怎么隔离？一条 SQL 漏了 workspace_id 怎么防？
   - 数据泄露的常见路径有哪些，你各怎么防？
   - 配额为什么用 Redis Lua 不用数据库事务？
   - hotfix 和 feature 分支流程的区别？

---

## W7：CI/CD + 监控

### 教学目标

学完本周你能：
- 搭 CD 管线：push main 自动部署，失败自动告警
- 写回滚脚本，1 分钟内恢复上一版本
- 用 Prometheus + Grafana 建 RED 指标看板
- 配告警规则：错误率/延迟/磁盘
- 用 Loki 聚合日志 + request_id 串链路
- 用 Locust 压测并输出报告

---

### D1：GitHub Actions CD（push → 自动部署）

**① 讲（15min）**

我讲：
- CI（W1 已做）vs CD：CI 验证代码，CD 交付部署
- 部署方式选型：SSH 拉代码 build（简单，本项目用）vs 镜像 registry（规范）
- 安全：部署密钥存 GitHub Secrets，绝不硬编码
- 管线门禁：只有 CI（lint+test）通过才允许部署
- 部署通知：成功/失败都要可追溯（commit SHA 打标）

**② 演（15min）**

我演示：
```yaml
# .github/workflows/cd.yml
name: CD
on:
  workflow_run:              # 跨文件依赖：等 CI workflow 跑完再触发（needs 不能跨 workflow）
    workflows: ["CI"]
    types: [completed]
    branches: [main]

jobs:
  deploy:
    # 门禁：CI 成功才部署，CI 红灯时这个 job 直接跳过
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    environment: production   # 可配手动审批
    steps:
      - uses: actions/checkout@v4

      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: deploy
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /opt/maxkb
            git fetch origin main
            git checkout ${{ github.sha }}
            docker compose build app
            docker compose up -d app
            sleep 5
            curl -sf http://localhost:8000/health || exit 1

      - name: Verify
        run: |
          sleep 10
          curl -sf https://kb.example.com/api/health
```

**③ 练（60min）**

你做：
1. 配置 GitHub Secrets（DEPLOY_HOST/DEPLOY_SSH_KEY）
2. 写 cd.yml：push main → SSH 部署 → 健康检查 → 验证线上
3. 部署脚本记录当前 SHA 到 `/opt/maxkb/VERSION`（为回滚做准备）
4. 实测：合并一个 PR 到 main，观察自动部署，2min 内线上更新
5. 故意让健康检查失败，观察 CD 红灯 + 部署中止
6. 分支 `feat/cd-pipeline`，commit：`ci: add cd pipeline with ssh deploy`

**④ 审（15min）**

我检查：
- Secrets 是否真的没出现在日志里（检查 Actions 输出）
- 部署后是否有健康检查门禁（裸部署打回）
- VERSION 文件是否更新（回滚依赖它）
- CI 红灯时 CD 是否真的不跑

**⑤ 验（15min）**

验收标准：
- [ ] push main 后 2min 内线上更新
- [ ] 部署失败时 CD 红灯且能看出失败步骤
- [ ] `cat /opt/maxkb/VERSION` 显示当前 SHA
- [ ] 你口头回答：镜像 registry 方案比 SSH build 好在哪？什么时候 CD 需要手动审批？

---

### D2：回滚脚本 + 健康检查

**① 讲（15min）**

我讲：
- 回滚的前提：版本可追溯（VERSION 文件 + git SHA + 镜像 tag）
- 回滚策略：代码回滚（git checkout 旧 SHA）vs 镜像回滚（切 tag），本项目用前者
- 健康检查三层：进程活（docker ps）→ 端口通（curl）→ 业务可用（/health 查 DB+Redis）
- 自动回滚触发：部署后健康检查 N 次失败 → 自动回滚
- 迁移兼容性：回滚代码时数据库 schema 怎么办（向后兼容迁移原则）

**② 演（15min）**

我演示：
```bash
#!/usr/bin/env bash
# scripts/rollback.sh — 回滚到上一个版本
set -euo pipefail
cd /opt/maxkb

CURRENT=$(cat VERSION)
PREV=$(git log --format=%H -2 main | tail -1)
echo "回滚: $CURRENT -> $PREV"

git checkout "$PREV"
docker compose build app
docker compose up -d app

for i in $(seq 1 10); do
  if curl -sf http://localhost:8000/health; then
    echo "$PREV" > VERSION
    echo "回滚成功"
    exit 0
  fi
  sleep 2
done
echo "回滚后健康检查仍失败，人工介入！" && exit 1
```

```python
# /health 升级为深度检查
@app.get("/health")
async def health(db=Depends(get_db), redis=Depends(get_redis)):
    await db.execute(text("SELECT 1"))
    await redis.ping()
    return {"status": "ok"}
```

**③ 练（60min）**

你做：
1. 写 `scripts/rollback.sh`（回滚 + 健康检查 + VERSION 更新）
2. Makefile 加 `rollback` target
3. /health 升级为深度检查（DB + Redis 连通性）
4. 演练：部署一个坏版本（/health 抛错）→ `make rollback` → 验证恢复
5. 计时：从执行回滚到恢复 < 1 分钟
6. 分支 `feat/rollback`，commit：`feat: add rollback script with deep health check`

**④ 审（15min）**

我检查：
- 回滚脚本是否 `set -euo pipefail`（任何一步失败立即停）
- 健康检查是否真的查了依赖（只返回写死的 ok 打回）
- 回滚后 VERSION 是否一致（否则下次回滚基准错）
- 是否考虑了迁移回滚问题（至少能说出原则）

**⑤ 验（15min）**

验收标准：
- [ ] `make rollback` 1 分钟内恢复
- [ ] 坏版本部署后健康检查红灯
- [ ] 回滚后 VERSION 正确
- [ ] 你口头回答：数据库迁移和代码回滚冲突怎么办？什么叫向后兼容的迁移？

---

### D3：Prometheus + Grafana

**① 讲（15min）**

我讲：
- 监控四金信号：延迟/流量/错误/饱和度；API 服务用 RED（Rate/Errors/Duration）
- Prometheus 拉模型：应用暴露 /metrics，Prometheus 定时 scrape
- 指标类型：Counter（只增）/ Histogram（分布，算 P99）/ Gauge（可增可减）
- Histogram 的 bucket 设计：按 SLO 设（0.05/0.1/0.3/1/2/5s）
- Grafana 看板：PromQL 三件套 —— QPS、错误率、P99

**② 演（15min）**

我演示：
```python
# backend/app/core/metrics.py
from prometheus_client import Counter, Histogram, make_asgi_app
from starlette.middleware.base import BaseHTTPMiddleware

REQ_TOTAL = Counter("http_requests_total", "Total requests", ["method", "path", "status"])
REQ_LATENCY = Histogram(
    "http_request_duration_seconds", "Request latency", ["path"],
    buckets=(0.05, 0.1, 0.3, 1.0, 2.0, 5.0),
)

class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        path = request.url.path
        REQ_TOTAL.labels(request.method, path, response.status_code).inc()
        REQ_LATENCY.labels(path).observe(time.perf_counter() - t0)
        return response

app.mount("/metrics", make_asgi_app())
```

```yaml
# prometheus.yml
scrape_configs:
  - job_name: maxkb
    scrape_interval: 15s
    static_configs: [{ targets: ["app:8000"] }]
```

```promql
# Grafana 三件套
sum(rate(http_requests_total[5m]))                                          # QPS
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))  # 错误率
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))    # P99
```

**③ 练（60min）**

你做：
1. 实现 MetricsMiddleware + /metrics 端点
2. docker-compose 加 prometheus + grafana 服务
3. Grafana 建看板：QPS / 错误率 / P99 / P50 四个面板
4. 加业务指标：`chat_tokens_total`（Counter，按 workspace 标签）
5. 制造流量，验证看板数据动起来
6. 分支 `feat/monitoring`，commit：`feat: add prometheus metrics and grafana dashboard`

**④ 审（15min）**

我检查：
- path 标签是否归一化（`/documents/123` 不能每个 ID 一个时间序列 → 用路由模板）
- Histogram bucket 是否按 SLO 设（默认 bucket 对 API 太粗）
- /metrics 是否不对公网暴露（只能内网访问）
- 看板 PromQL 是否正确（rate 窗口 5m，histogram_quantile 要 by (le)）

**⑤ 验（15min）**

验收标准：
- [ ] RED 指标看板可见且数据正确
- [ ] 手动制造 500，错误率面板上涨
- [ ] /metrics 公网不可访问
- [ ] 你口头回答：Counter 和 Gauge 区别？为什么 P99 要用 histogram 不能存平均值？

---

### D4：告警规则

**① 讲（15min）**

我讲：
- 告警原则：只告"需要人行动"的（错误率、延迟、磁盘、服务挂），不告噪声
- Alertmanager 流程：规则触发 → 分组/去重/静默 → 路由到渠道（邮件/webhook）
- `for` 子句：持续 N 分钟才告（防毛刺）
- 分级：critical（页面级，立刻处理）vs warning（工作时间处理）
- 告警疲劳的危害：狼来了效应，宁可少告不可乱告

**② 演（15min）**

我演示：
```yaml
# prometheus/rules.yml
groups:
  - name: maxkb
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
            / sum(rate(http_requests_total[5m])) > 0.05
        for: 2m
        labels: { severity: critical }
        annotations:
          summary: "5xx 错误率超过 5% 持续 2 分钟"

      - alert: HighP99Latency
        expr: |
          histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le)) > 2
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "P99 延迟超过 2s"

      - alert: ServiceDown
        expr: up{job="maxkb"} == 0
        for: 1m
        labels: { severity: critical }
```

**③ 练（60min）**

你做：
1. 写 3 条告警规则：错误率 > 5% / P99 > 2s / 服务 down
2. docker-compose 加 alertmanager，配邮件或 webhook 通知
3. 演练一：写个临时端点狂返 500 → 2 分钟后收到告警
4. 演练二：停掉 app 容器 → ServiceDown 告警
5. 恢复后验证告警自动 resolved
6. 分支 `feat/alerting`，commit：`feat: add alertmanager rules for red signals`

**④ 审（15min）**

我检查：
- 每条规则是否有 `for`（无 for 的毛刺告警打回）
- severity 分级是否合理
- 告警消息是否含上下文（哪个服务、什么指标、阈值多少）
- 是否真的演练触发了（不是只写了规则）

**⑤ 验（15min）**

验收标准：
- [ ] 错误率 > 5% 触发通知（真实收到）
- [ ] 服务恢复后告警 resolved
- [ ] 三条规则全部演练过
- [ ] 你口头回答：`for: 2m` 的代价是什么？告警太多怎么治理？

---

### D5：日志聚合（Loki）+ 链路追踪

**① 讲（15min）**

我讲：
- 单机 `docker logs` 的问题：多容器/多实例/重启丢失 → 需要聚合
- Loki 理念：只索引标签不索引全文（便宜），LogQL 按标签过滤 + 正则搜内容
- 日志规范回顾：JSON 格式 + request_id（W1 做的，现在发挥价值）
- 链路追踪：一个 request_id 串起 Nginx → API → Celery 三层日志
- Grafana 里日志和指标联动：从错误率面板跳到对应日志

**② 演（15min）**

我演示：
```yaml
# docker-compose 加 loki + promtail
  loki:
    image: grafana/loki:3.0
    ports: ["3100:3100"]
  promtail:
    image: grafana/promtail:3.0
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - ./promtail.yml:/etc/promtail/config.yml
```

```yaml
# promtail.yml — 抓 docker 容器日志
scrape_configs:
  - job_name: docker
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 15s
    relabel_configs:
      - source_labels: ["__meta_docker_container_name"]
        target_label: container
```

```logql
# 按 request_id 串链路
{container=~".*maxkb.*"} |= "a1b2c3d4" | json | level="error"
# 统计 5 分钟内错误数
sum(count_over_time({container=~".*maxkb.*"} |= "error" [5m]))
```

**③ 练（60min）**

你做：
1. docker-compose 加 loki + promtail
2. Grafana 加 Loki 数据源，配 Explore 查询
3. 确保 Nginx 访问日志也带 request_id（`$request_id` 透传）
4. 演练：一次失败请求，用 request_id 在 Loki 里串出 Nginx + API 至少 3 条日志
5. 建日志面板：错误日志 Top 列表
6. 分支 `feat/logging`，commit：`feat: add loki log aggregation with request tracing`

**④ 审（15min）**

我检查：
- request_id 是否从 Nginx 生成并透传到后端（header 串联）
- 日志是否 JSON 可解析（Loki 的 `| json` 能用）
- Celery worker 日志是否也被采集（别只采 API）
- 敏感信息是否脱敏（密码/token 不能进日志）

**⑤ 验（15min）**

验收标准：
- [ ] request_id 串联 3 条以上跨层日志
- [ ] LogQL 能按 level/关键词过滤
- [ ] 日志中无敏感信息
- [ ] 你口头回答：Loki 和 ELK 的取舍？日志量太大怎么采样？

---

### D6：Locust 压测

**① 讲（15min）**

我讲：
- 压测目的：找瓶颈 + 验证容量，不是"跑个数字"
- 指标：QPS、P50/P95/P99、错误率、资源水位（CPU/内存/连接数）
- 压测场景设计：按真实流量配比（80% 问答 + 15% 列表 + 5% 上传）
- 压测纪律：压测试环境或专用时段，别把生产打挂；LLM 用 Mock 避免烧钱
- 瓶颈定位路径：应用 CPU → DB 连接池 → Redis → 外部依赖

**② 演（15min）**

我演示：
```python
# tests/load/locustfile.py
from locust import HttpUser, task, between

class User(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        r = self.client.post("/api/v1/auth/login", json={"email": "load@test.com", "password": "..."})
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    @task(8)
    def chat(self):
        with self.client.post("/api/v1/chat", json={"kb_id": 1, "question": "保修期多久？"},
                              stream=True, catch_response=True) as r:
            for _ in r.iter_lines():
                pass
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")

    @task(2)
    def list_kbs(self):
        self.client.get("/api/v1/knowledge-bases")
```

```bash
locust -f tests/load/locustfile.py --host=https://kb.example.com \
  --users 100 --spawn-rate 10 --run-time 5m --headless --html report.html
```

**③ 练（60min）**

你做：
1. 写 locustfile（按流量配比加权 task）
2. 准备压测数据：知识库 + 100 个文档 + 测试账号
3. 阶梯加压：10 → 50 → 100 用户，各跑 5 分钟
4. 记录每档的 QPS/P99/错误率 + 服务器资源水位
5. 找出第一个瓶颈（大概率是 LLM Mock 之外的 DB 或 rerank）
6. 输出 `docs/load_test_report.md`
7. 分支 `feat/load-test`，commit：`test: add locust load test with report`

**④ 审（15min）**

我检查：
- 压测是否打了生产（打了立刻停 + 复盘）
- 场景配比是否有依据（不是全打一个接口）
- 报告是否含资源水位（只有 QPS 数字的报告不完整）
- SSE 接口的压测是否正确消费了流（不读 body 会假成功）

**⑤ 验（15min）**

验收标准：
- [ ] 100 并发下 P99 < 2s（或给出差距分析和优化计划）
- [ ] 报告含 QPS/延迟/错误率/资源水位四要素
- [ ] 明确指出第一个瓶颈在哪
- [ ] 你口头回答：P99 和平均值的区别？压测时 CPU 没满但 QPS 上不去，可能是什么原因？

---

### D7：周复盘

**教学内容：**

1. **监控体系陈述**（你讲，我挑刺）：
   - 指标（RED）→ 告警（分级）→ 日志（链路）→ 压测（容量），讲清四者如何联动排障

2. **排障演练**（我出题，你实操）：
   - 我制造一个故障（如某接口延迟飙升），你用 Grafana + Loki 在 10 分钟内定位到根因

3. **产出物检查**：
   - 监控看板截图 + 告警触发记录 + 压测报告，归档到 `docs/ops/`

4. **自测**（我问，你答）：
   - 部署失败怎么回滚？回滚后数据库怎么办？
   - 监控指标怎么选？为什么不监控 CPU 而优先监控 RED？
   - 告警疲劳怎么解决？
   - 压测发现的瓶颈你打算怎么优化（引出 W8-D1）？

---

## W8：优化 + 收尾 + 面试

### 教学目标

学完本周你能：
- 用数据驱动性能优化：缓存/索引/连接池，P99 下降 > 30%
- 完成零停机发布 + 故障演练
- 输出生产级 README + 架构文档
- 用 5 分钟讲清整个项目，扛住 10 个追问
- 打 tag v1.0.0，完成全栈能力闭环

---

### D1：性能优化（缓存/索引/连接池）

**① 讲（15min）**

我讲：
- 优化三问：瓶颈在哪（数据）？优化收益多大（排序）？有没有副作用（权衡）？
- 用 W7 压测报告定位的瓶颈逐项开刀
- 缓存：热点 query 的检索结果缓存（Redis，TTL + 失效策略：文档更新时清）
- 索引：慢查询日志（`pg_stat_statements`）找全表扫描
- 连接池：SQLAlchemy pool_size/max_overflow，为什么连接不是越多越好（PG 进程模型）

**② 演（15min）**

我演示：
```python
# backend/app/rag/cache.py — 检索结果缓存
import hashlib, json
from dataclasses import asdict

async def cached_retrieve(db, redis, kb_id: int, query: str, top_k: int):
    key = f"retrieve:{kb_id}:{hashlib.sha256(query.encode()).hexdigest()}:{top_k}"
    if hit := await redis.get(key):
        return json.loads(hit)
    hits = await full_retrieve(db, query, top_k=top_k)
    await redis.set(key, json.dumps([asdict(h) for h in hits]), ex=300)  # ChunkHit 是 dataclass
    return hits

# 文档更新时失效
async def invalidate_kb_cache(redis, kb_id: int):
    async for key in redis.scan_iter(f"retrieve:{kb_id}:*"):
        await redis.delete(key)
```

```python
# 连接池调优
engine = create_async_engine(
    settings.database_url,
    pool_size=10,          # 常驻连接
    max_overflow=20,       # 峰值借用
    pool_pre_ping=True,    # 防 PG 断连
)
```

```sql
-- 找慢查询
CREATE EXTENSION pg_stat_statements;
SELECT query, calls, mean_exec_time FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 10;
```

**③ 练（60min）**

你用：
1. 跑基线压测，记录优化前 P50/P99
2. 实现检索结果缓存（含文档更新失效逻辑）
3. 用 `pg_stat_statements` 找最慢 3 条查询，逐个优化（加索引/改写）
4. 调连接池参数，压测对比
5. 复跑压测，对比优化前后，写 `docs/perf_optimization.md`
6. 分支 `feat/perf`，commit：`perf: add retrieve cache and tune db pool`

**④ 审（15min）**

我检查：
- 是否有 before/after 数据（没有数据的"优化"不算数）
- 缓存失效是否覆盖所有写路径（上传/删除/重建都要清）
- 缓存 key 是否含 kb_id 和 top_k（否则串数据）
- 是否过度优化（花 3 小时优化只占 1% 耗时的环节 = 浪费）

**⑤ 验（15min）**

验收标准：
- [ ] P99 下降 > 30%（压测报告证明）
- [ ] 文档更新后缓存正确失效（测试证明）
- [ ] 优化报告含数据对比
- [ ] 你口头回答：缓存穿透/击穿/雪崩分别是什么？连接池太大为什么反而慢？

---

### D2：零停机发布演练

**① 讲（15min）**

我讲：
- 为什么 `docker compose up -d --build` 会停机：旧容器先停 → 端口空窗
- 方案对比：双实例 + Nginx 上游切换（蓝绿）vs 滚动更新（多副本）vs 优雅停机（单实例最小代价）
- 优雅停机：SIGTERM → 停止接新请求 → 处理完存量 → 退出（uvicorn `--timeout-graceful-shutdown`）
- 健康检查门禁：新实例 healthy 后才切流量
- 本项目方案：双实例蓝绿（app-blue/app-green）+ Nginx upstream 切换

**② 演（15min）**

我演示：
```bash
#!/usr/bin/env bash
# scripts/zero_downtime_deploy.sh
set -euo pipefail
declare -A PORTS=( [blue]=8001 [green]=8002 )      # 实例 → 端口映射（别用字符串替换拼端口）

ACTIVE=$(cat /opt/maxkb/ACTIVE)                    # blue 或 green
INACTIVE=$([ "$ACTIVE" = blue ] && echo green || echo blue)
PORT=${PORTS[$INACTIVE]}

docker compose build "app-$INACTIVE"
docker compose up -d "app-$INACTIVE"

HEALTHY=0
for i in $(seq 1 15); do                           # 等新实例健康
  if curl -sf "http://localhost:$PORT/health"; then
    HEALTHY=1
    break
  fi
  sleep 2
done
if [ "$HEALTHY" != 1 ]; then
  echo "新实例健康检查失败，中止发布（流量仍在旧实例）"
  docker compose stop "app-$INACTIVE"
  exit 1                                           # 失败必须中止，绝不切流量
fi

sed -i "s/server app-$ACTIVE/server app-$INACTIVE/" /etc/nginx/conf.d/upstream.conf
nginx -s reload                                    # Nginx 热重载，连接不断
sleep 5
docker compose stop "app-$ACTIVE"                  # 旧实例处理完存量后下线
echo "$INACTIVE" > /opt/maxkb/ACTIVE
```

```python
# FastAPI 优雅停机：处理完存量请求
# uvicorn app.main:app --timeout-graceful-shutdown 30
```

**③ 练（60min）**

你做：
1. docker-compose 拆双实例 app-blue/app-green
2. Nginx upstream 配置 + 切换脚本
3. uvicorn 配优雅停机（graceful shutdown）
4. 演练：发布期间 `while true; do curl -s -o /dev/null -w "%{http_code}\n" https://kb.example.com/api/health; sleep 0.2; done` 持续打流量
5. 断言：整个发布过程零 5xx
6. 分支 `feat/zero-downtime`，commit：`feat: add blue-green zero downtime deployment`

**④ 审（15min）**

我检查：
- 新实例健康检查失败时是否会切流量（必须不切 + 中止发布）
- 旧实例是否等存量请求处理完再停（不是直接 kill）
- ACTIVE 文件和 Nginx 配置是否一致（状态漂移是事故源）
- 演练是否有真实流量证据（curl 日志）

**⑤ 验（15min）**

验收标准：
- [ ] 发布期间 curl 无 5xx（日志为证）
- [ ] 新实例故障时发布中止，流量仍在旧实例
- [ ] 优雅停机：存量请求正常完成
- [ ] 你口头回答：蓝绿和滚动更新的区别？有状态服务（如 Celery worker）零停机要注意什么？

---

### D3：故障演练

**① 讲（15min）**

我讲：
- 混沌工程思想：故障必然发生，与其等线上爆不如主动演练
- 演练清单：进程挂、DB 挂、Redis 挂、依赖（LLM）超时、磁盘满
- 每个演练三问：多久发现（告警）？多久恢复（自愈/人工）？数据丢没丢？
- 自愈机制：restart=always、healthcheck、Celery 重试、熔断降级
- 降级策略：LLM 挂了返回"服务繁忙"，不能让整个 API 跟着挂

**② 演（15min）**

我演示演练脚本和预期：
```bash
# 演练 1：杀 API 进程
docker compose kill app-blue
# 预期：restart=always 10s 内拉起；ServiceDown 告警触发

# 演练 2：杀 Redis
docker compose stop redis
# 预期：/health 变红（依赖检查），服务降级但不 panic

# 演练 3：LLM 超时
# 配置 LLM_TIMEOUT=1s 模拟，预期：/chat 返回降级文案，不 500
```

```python
# LLM 调用降级
try:
    async with asyncio.timeout(settings.llm_timeout):
        return await llm.complete(prompt)
except (TimeoutError, LLMError):
    logger.warning("llm degraded")
    raise BizError("SERVICE_DEGRADED", "AI 服务暂时繁忙，请稍后重试", status=503)
```

**③ 练（60min）**

你做：
1. 逐项执行 5 个故障演练，每个记录：发现时间/恢复时间/数据影响
2. 修复演练暴露的问题（大概率有：某个依赖挂了导致 API 全挂）
3. 实现 LLM 超时降级（不能让问答拖垮整个服务）
4. 写 `docs/chaos_drill_report.md`（表格：故障/发现/恢复/改进项）
5. 复演：修复后再跑一遍，验证恢复时间达标
6. 分支 `feat/chaos-drill`，commit：`feat: add fault drills and llm degradation`

**④ 审（15min）**

我检查：
- 演练报告是否有真实时间数据（不是"大概几秒"）
- 发现的问题是否真的修了（有对应 commit）
- 降级是否覆盖所有 LLM 调用点（rewrite/rerank 用的 LLM 也要）
- 告警是否如预期触发（没触发 = 告警规则有洞）

**⑤ 验（15min）**

验收标准：
- [ ] 杀进程 → 自动恢复（restart 生效）
- [ ] 每个故障有发现/恢复时间记录
- [ ] LLM 降级生效，不影响其他接口
- [ ] 你口头回答：Redis 挂了你的服务哪些功能受影响？为什么是降级而不是直接报错？

---

### D4：README + 架构文档

**① 讲（15min）**

我讲：
- README 的读者是"5 分钟后的陌生人"：项目是什么 → 长什么样 → 怎么跑 → 怎么测
- 架构文档的读者是"接手的人"：组件图 + 数据流 + 关键决策（ADR 思想）
- 关键决策要写"为什么"：为什么 pgvector 不选 Milvus、为什么 SSE 不选 WebSocket
- 文档即代码：过时的文档比没有文档更糟，放进 CI 检查（链接/命令可执行）

**② 演（15min）**

我演示 README 骨架：
```markdown
# MaxKB Replica

一句话：基于 RAG 的多租户知识库问答平台（MaxKB 教学复刻版）。

## 功能特性
- 文档入库：PDF/MD/TXT 解析 → 切片 → 向量化（Celery 异步）
- 混合检索：pgvector + BM25 → RRF → Cross-Encoder 精排
- 流式问答：SSE + 引用标注 + 多轮上下文
- 多租户：workspace 隔离 + RBAC + token 配额

## 快速开始
git clone ... && cd maxkb-replica
cp .env.example .env
make up          # 启动全部服务
make migrate     # 执行迁移
# 访问 http://localhost:5173

## 架构
![architecture](docs/assets/architecture.png)
（组件职责 + 数据流说明）

## 开发
make test / make lint / make e2e
```

**③ 练（60min）**

你做：
1. 重写 README（按上面骨架，所有命令必须真实可执行）
2. 画最终架构图（含监控组件：Prometheus/Grafana/Loki）
3. 写 `docs/architecture.md`：组件图 + 核心数据流（入库/问答两条）+ 5 个关键技术决策及理由
4. 写 `docs/deploy.md`：从零部署到生产的完整步骤
5. 找一个没参与的同学按 README 从零跑一遍，记录卡点并修复
6. 分支 `docs/final`，commit：`docs: add readme and architecture documentation`

**④ 审（15min）**

我检查：
- 新人 5 分钟能否跑起来（找真人验证，不是自己觉得）
- 架构图是否和代码现状一致（别是 W3 时候画的旧图）
- 技术决策是否写了"为什么"和"备选方案"
- 部署文档是否包含踩过的坑（证书续期、SSH 配置）

**⑤ 验（15min）**

验收标准：
- [ ] 新人 5 分钟能跑起来（真人实测）
- [ ] 架构图覆盖全部组件
- [ ] 5 个技术决策有理由有备选
- [ ] 你口头回答：文档和代码不一致时你信谁？怎么机制化防过时？

---

### D5：面试话术（5 分钟版）

**① 讲（15min）**

我讲：
- 项目陈述结构：一句话定位 → 技术栈 → 核心链路 → 难点与决策 → 量化成果
- STAR 讲难点：情境 → 任务 → 行动 → 结果（必须有数字）
- 每个决策准备"为什么选 A 不选 B"
- 量化素材整理：P99 优化 30%、覆盖率 80%+、100 并发、发布零停机
- 防守策略：不熟的领域主动划边界（"这块我了解到 X 层面"），不硬编

**② 演（15min）**

我演示一个标准开场（然后拆解为什么这么讲）：
> "这是一个多租户 RAG 知识库平台，我独立完成全栈开发。后端 FastAPI + PostgreSQL/pgvector，前端 React + TS。核心链路是文档异步入库和两级检索问答：双路召回（pgvector + BM25）经 RRF 融合后用 Cross-Encoder 精排，SSE 流式输出带引用。
> 我重点做了三件事：一是检索质量，混合检索比单路召回率提升明显；二是性能，通过检索缓存和连接池调优把 P99 从 X 降到 Y；三是工程化，蓝绿发布零停机、Prometheus 监控告警、Locust 压测 100 并发。"

拆解：30 秒讲完"是什么 + 怎么做 + 亮点"，每个亮点都留了追问钩子。

**③ 练（60min）**

你做：
1. 写 5 分钟陈述稿（结构：定位 30s → 链路 90s → 三个亮点 150s → 成果 30s）
2. 整理 10 个"为什么"问答卡（技术选型/设计决策）
3. 整理量化成果表（每项有数据来源）
4. 对着计时器练 3 遍，录音回听
5. 分支 `docs/interview`，commit：`docs: add interview talking points`

**④ 审（15min）**

我检查：
- 是否 5 分钟内讲完（超时 = 没提炼）
- 每个亮点是否有数字支撑
- 是否留了追问钩子（引导面试官问你准备好的领域）
- 有没有夸大（"精通""完全"这类词逐个审）

**⑤ 验（15min）**

验收标准：
- [ ] 5 分钟陈述流畅无卡顿
- [ ] 每个亮点有量化数据
- [ ] 10 个问答卡全部能答
- [ ] 你口头回答：如果面试官问"你遇到最大的困难"，你讲哪个？为什么？

---

### D6：模拟面试

**① 讲（15min）**

我讲规则：
- 全程 45 分钟，我扮演面试官，全程不打断不提示
- 结构：项目陈述 5min → 技术深挖 30min → 开放设计题 10min
- 评分维度：准确性、深度、表达、诚实度（不知道就说不知道，加分）

**② 演（15min）**

不适用 —— 本日直接开始模拟。我先演示一道深挖题的标准答法框架：
> 问："为什么用 RRF 不用加权求和？"
> 答法框架：结论先行（"因为两路分数量纲不可比"）→ 展开（余弦相似度有界 vs ts_rank 无上界，加权需要先归一化而归一化本身不稳定）→ 延伸（RRF 只看排名，天然免调参，且可扩展到三路）→ 收尾（"当然 RRF 也丢了分数强度信息，所以我们在后面加了 rerank 补精度"）

**③ 练（60min）**

模拟面试进行中，我至少问：
1. 讲一下你的 RAG 全链路，每步延迟多少？
2. 为什么 pgvector 不用 Milvus？什么情况下你会换？
3. HNSW 的 m 和 ef_search 分别影响什么？你怎么调的参？
4. 多租户隔离怎么做的？一条 SQL 漏了 workspace_id 怎么办？
5. JWT 被偷了怎么办？你的系统里怎么缓解？
6. Celery 挂了任务会丢吗？你怎么保证入库最终成功？
7. 你的 P99 优化了 30%，具体做了什么，怎么定位的瓶颈？
8. 零停机发布怎么做的？新实例有问题怎么办？
9. （设计题）如果知识库涨到 1000 万条切片，你的检索架构要怎么改？
10. （设计题）如果要支持多模态（图片问答），你会怎么扩展？

**④ 审（15min）**

我逐题点评：
- 每题打分（1-5）+ 指出具体问题（结论不清晰/没有数据/答非所问/过度夸大）
- 标出"致命伤"：原则性错误（如说错 RRF 公式、混淆认证授权）
- 给出每题的改进版答法

**⑤ 验（15min）**

验收标准：
- [ ] 10 个追问不卡壳（每题 2 分钟内有结构化作答）
- [ ] 无原则性错误
- [ ] 设计题能给出分层方案（而不是"加机器"）
- [ ] 你口头回答：哪道题答得最不满意？回去补什么？

---

### D7：总复盘 + tag v1.0.0

**教学内容：**

1. **八周全景复盘**（你讲，我补）：
   - 每周一个里程碑：骨架 → 入库 → 检索 → 对话 → 前端 → 上线 → 监控 → 优化
   - `git log --oneline --graph --all` 看全部历史，数 commit、数分支、数 tag
   - `cloc .` 数代码行数，`pytest --cov` 出最终覆盖率

2. **最终架构图 + 能力清单**（你画/写）：
   - 一张图涵盖：前端/Nginx/API/Celery/PG/Redis/监控全家桶
   - 能力清单对照招聘 JD：每条能力对应项目里的哪个模块

3. **打 v1.0.0 tag**：
   ```bash
   git tag -a v1.0.0 -m "release: v1.0.0 全栈功能闭环，生产可用"
   git push origin v1.0.0
   ```

4. **终极自测**（我问，你答，随机抽 5 题）：
   - 从附录 B 八周追问题库随机抽题
   - 要求：不看笔记、结论先行、有数据支撑

5. **下一步规划**（你写）：
   - 项目还能做什么（评测集/多模态/Agent）
   - 简历怎么写这个项目，投递节奏

---

## 附录 A：每日教学模板

```markdown
## W{n} D{m}：{主题}

### ① 讲（15min）
- 概念 1：xxx
- 概念 2：xxx
- 读源码：MaxKB 的 xxx 文件

### ② 演（15min）
- 我演示：{具体代码/命令}
- 你观察：{重点关注什么}

### ③ 练（60min）
- 任务 1：xxx
- 任务 2：xxx
- 任务 3：xxx
- 分支：feat/xxx
- Commit：type: description

### ④ 审（15min）
- 我检查：{具体检查点}
- 常见问题：{初学者容易犯的错}

### ⑤ 验（15min）
- [ ] 验收标准 1
- [ ] 验收标准 2
- [ ] 口头回答：{追问问题}
```

---

## 附录 B：面试追问题库（按周）

| 周 | 高频追问 |
|----|----------|
| W1 | JWT 被偷了怎么办？为什么不用 Session？Docker 和 VM 区别？ |
| W2 | 100MB 文件怎么处理？Celery 挂了任务丢吗？切片策略怎么选？ |
| W3 | 为什么用混合检索？Rerank 延迟高怎么办？流式输出原理？ |
| W4 | 多轮对话 token 爆了怎么办？API 版本怎么管理？ |
| W5 | React 状态管理怎么选？流式渲染性能问题？ |
| W6 | 多租户怎么隔离？数据泄露怎么防？ |
| W7 | 部署失败怎么回滚？监控指标怎么选？ |
| W8 | 性能瓶颈在哪？怎么定位的？优化了多少？ |

---

*计划版本：v2.0 | 创建日期：2026-08-04 | 教学方法：讲→演→练→审→验*
