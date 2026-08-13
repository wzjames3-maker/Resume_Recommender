# 实现偏离台账（Deviation Log）

> 版本：v0.1
> 日期：2026-08-07
> 范围：P1 平台底座实现（F1–F5），分支 `p1-platform`（提交 `d0e55d7..9910684`）
>
> 目的：集中记录实现过程中与 PRD（唯一需求基准）及《P1 平台底座实现计划》的每一处出入，保证合并后偏离可追溯、可审计。每项偏离均标注来源、性质、决策方与对应提交。
>
> **合并信息**：P1 平台底座已合并至 main @ `b14e5828c06e0ae20f80875b202d448e2d65650e`（2026-08-08，`git merge --no-ff p1-platform`，保留 16 个提交完整历史）。后续 P2 及以后的工作在 main 上继续。

## 1. 与 PRD 的出入（合约级，需人类裁决）

PRD 为高层需求基准，实现基本全部符合；以下 2 项属于对 PRD 未明确之处的裁决，均已由人类批准。

| # | 出入点 | PRD 依据 | 实现 | 性质 | 决策 | 提交 |
|---|--------|----------|------|------|------|------|
| D-1 | F3 端点范围 3 → 11 个 | PRD F3 要求「知识库 CRUD」「可 retry」「分块查看（member 可读）」 | 实现 5 个知识库端点 + 6 个文档端点（create/update/delete/get/list + upload/list/get/chunks/delete/retry），对齐 API_SPEC §4.4/§4.5 | 范围扩展（计划简报仅列 create_kb / list_kbs / upload_document） | 人类批准补齐 | `4830e60` |
| D-2 | 上传权限 member → admin+ | PRD F3 未明确上传权限；PRD F9 的「简历上传 member+」系 F6 简历，与本项无关 | 文档上传/删除/重试统一 admin 及以上，读操作（分块查看等）member 即可 | 冲突裁决（计划简报代码为 member 可传） | 人类批准收紧，决策依据 API_SPEC §7.2 | `4830e60` |

## 2. 与计划简报的出入（实现级 bugfix / 增强）

计划简报由本 PRD 编写时给出参考代码；以下是对简报代码的修正或增强，均不改变 PRD 语义。

| # | 出入点 | 简报原样 | 实现 | 性质 | 提交 |
|---|--------|----------|------|------|------|
| D-3 | crypto AES-256-GCM nonce 处理 | `KEY.encrypt(os.urandom(12), plain).hex()` 丢弃 nonce → 解密必 `InvalidTag` | 显式 `(nonce + ct).hex()` 拼接，`decrypt` 按 `raw[:12]/raw[12:]` 切分；补 `test_crypto_roundtrip` 锁定往返 | 简报代码 bugfix（与 cryptography 版本无关） | `f56eea3` |
| D-4 | `hybrid_search` 向量参数绑定 | Python list 直接绑 `:q`，asyncpg 报 `DataError: expected str, got list` | `text(...).bindparams(bindparam("q", type_=Vector(EMBEDDING_DIM)))`，SQL 文本与调用签名不变 | 简报代码 bugfix（asyncpg 无法编码 list 为 vector） | `6a5ba13` |
| D-5 | 测试基建数据库隔离 | 计划未指定测试库；测试代码 `ASGITransport(app=app)` 在 import 时即构建全局 engine | conftest 注入 `DATABASE_URL` 指向本地 dev PG + autouse 清理 fixture（TRUNCATE users/workspaces/workspace_members），测试命令可重复运行 | 测试隔离决策（人类拍板：保留真实 PG，不改为 SQLite 内存库） | `baea73a` |
| D-6 | SQLite 测试兼容 | 简报用 `BIGINT PRIMARY KEY`、`server_default="now()"`、`JSONB`/`Vector` 列 | `BigIntPK`（SQLite 用 `Integer` variant）、`func.now()`、`JSON`/`Text` sqlite variant；PG 生产语义不变 | 让测试真实可运行的必要修复（审查者独立核实成立） | `258f430` |
| D-7 | `_run` 使用知识库分块配置 | 简报硬编码 `chunk_size=512, overlap=64` | 从 `doc → kb.chunk_size/chunk_overlap` 读取，缺失回退 512/64；否则「创建时指定不可变」形同虚设 | 必要增强（有测试锁定） | `4830e60` |
| D-8 | parse 重跑幂等 | 简报 `_run` 不清理旧分块 | 重跑前 `delete(Chunk)` + 清空 `error_message`，保证 retry 不产生重复分块 | 必要增强 | `4830e60` |
| D-9 | 飞行前计划修复 3 处 | 计划 `pyproject.toml` 缺 `aiosqlite`；Dockerfile 不装 dev 组；`/refresh` 不校验 `is_active` | 补 `aiosqlite`；Dockerfile 改 `uv pip install --system --group dev -e .`；`/refresh` 校验 `is_active` | 计划文档自身缺陷，飞行前修复并同步计划文本 | `7a1bac6` |

## 3. 最终整分支审查产生的修复（对齐 PRD/API_SPEC 的安全与契约）

| # | 出入点 | 说明 | 提交 |
|---|--------|------|------|
| D-10 | SSRF 网关收紧为 `not ip.is_global` | 覆盖 CGNAT（100.64.0.0/10）、site-local、文档段等全部非公网段，比 PRD「私网/回环/链路本地/云 metadata」要求更严（超集，无放行回退） | `40cd40f` |
| D-11 | JWT_SECRET fail-fast | 非空、非占位 `change-me`、长度 ≥ 32，否则启动失败；conftest 注入 64 位密钥 | `40cd40f` |
| D-12 | 上传内存 DoS 防护 | 先查 `file.size` 超限直接 413，缺失时 1MB 分块边读累计超限中断 | `40cd40f` |
| D-13 | SSE error 事件 | `gen()` 包 try/except，异常 yield `data: {"type":"error"}`，不产生孤儿 assistant 消息 | `40cd40f` |
| D-14 | Celery 事件循环 | 任务前后各 `engine.dispose()`，避免 asyncpg 连接池跨临时 loop 复用崩溃 | `40cd40f` |
| D-15 | `stream:false` 非流式返回 | 一次性 JSON `{answer, sources, token_count, conversation_id, message_id}`（API_SPEC §4.6.1） | `40cd40f` |
| D-16 | 校验错误归一 400 | `RequestValidationError` → 400 `VALIDATION_ERROR`（API_SPEC §1.4）；`IntegrityError` → 409 | `4830e60`、`40cd40f` |
| D-17 | 其他安全/契约小项 | 非数字端口 400；`message` 空串 400；`model_type` 枚举约束；悬空 KB 404；`[0.0]*EMBEDDING_DIM`；前端 `streamChat` 检查 `res.ok` | `40cd40f` |

## 4. 明确不做（后续处理）

以下为审查中识别但有意留待后续的项，记录以防误判为遗漏：

| 项 | 处理计划 |
|----|----------|
| 真实 embedding（bge-m3）、LLM（deepseek-chat）、rerank（bge-reranker-v2-m3）接入 | P2/P3 集成 |
| docx/pdf 文本抽取（当前 M1 占位返回空） | P2 简历流水线 |
| SSE `sources` 载荷字段名对齐 API_SPEC（当前 `content_snippet`） | P2 集成 |
| Celery `autoretry_for` 死配置（异常被 `_run` 内部吞掉） | P2 集成 |
| 前端持久化 token 过期校验、LoginPage 错误处理、store try/catch | 后续前端任务 |
| ruff 遗留 I001/UP017、文件缺结尾换行 | 后续清理 |
| 权限校验抽公共依赖（ensure_member/ensure_admin 下沉 deps.py） | 重构建议待评估 |
| 认证注册/登录接口限流（API_SPEC §1.6） | P2：引入限流中间件（slowapi）后再验收 |
| chat 接口限流（每用户每分钟 20 次）与 workspace token 配额/用量扣减（API_SPEC §1.6/§4.6.1） | P2：接入真实模型与用量统计后实现 `RATE_LIMITED`/`QUOTA_EXCEEDED` |
| 解析任务并发幂等（run_id/任务代次、乐观锁/lease、上传与投递的可靠事件链） | P2：模型加 run_id 字段并按 run 幂等消费 |
| `model_config_revision` 不可变历史与索引绑定迁移 | P2：配置 revision 表 + 索引 profile 原子切换 |
| 不可变审计事件（模型配置变更/出站/权限拒绝） | P2：审计事件表与写入路径 |
| 多轮会话上下文、来源快照增强（filename/score）、客户端中断保留 | P2：会话历史加载与消息快照 |
| `(document_id, position)` 唯一约束 | P2：增量迁移补唯一索引 |
| 对象存储替代本地绝对路径 `storage_key` | P2：接入对象存储后替换 |

## 5. 验证

- 后端测试：`pytest backend/tests -q` → **84 passed**（无 warning）
- 前端测试：`cd frontend && npx vitest run` → **3 passed**
- 前端生产构建：`cd frontend && npm run build` → **通过**（tsconfig.app.json 排除测试目录）
- 静态检查：`ruff check backend/app backend/tests` → All checks passed
- Celery 任务注册：`include=["app.tasks.parse_document"]` 后任务列表含 `app.tasks.parse_document.parse_document`
- Docker 镜像：包含 `alembic.ini` 与 `alembic/`，`alembic upgrade head` 可用
- `docker compose config`：在提供 `backend/.env` 后通过

## 6. 整分支二次复核修复（2026-08-07，对齐 API_SPEC/PRD 契约）

在首次审查结论基础上，对分支做整链复核，修复以下问题（均附测试/构建/运行证据）：

| # | 修复项 | 说明 | 涉及文件 |
|---|--------|------|----------|
| R-1 | Celery 任务未注册 | `autodiscover_tasks` 不扫描 `parse_document.py`；改为 `Celery(..., include=["app.tasks.parse_document"])`，实测任务列表含 `parse_document` | `tasks/celery_app.py` |
| R-2 | API/worker 不共享上传文件 | Compose 新增共享 `uploads` volume 挂载到 api/worker 的 `/tmp/uploads` | `docker-compose.yml` |
| R-3 | 镜像缺 alembic 配置/迁移 | Dockerfile 补 `COPY alembic.ini` 与 `COPY alembic`；镜像内实测文件存在 | `backend/Dockerfile` |
| R-4 | Compose 启动不执行迁移 | api command 改为 `alembic upgrade head && uvicorn ...` | `docker-compose.yml` |
| R-5 | 新增 `/auth/logout` 与 refresh token 撤销 | refresh token 带 `jti`，签发时写入 Redis；refresh 校验存在性；logout 幂等 204；refresh 响应对齐 API_SPEC 仅返回 `access_token` | `api/auth.py`、`core/security.py`、`core/token_store.py`（新）、`tests/conftest.py` |
| R-6 | 补齐 workspace/users 管理端点 | 新增加 `PUT /users/me`、`GET/DELETE /workspaces/{id}`、`PATCH/DELETE /workspaces/{ws_id}/members/{user_id}`、`GET /workspaces/{ws_id}/usage`；invite 返回对齐 API_SPEC 成员结构 | `api/workspaces.py`、`api/users.py` |
| R-7 | 检索未过滤 ready 文档 | 向量/全文 SQL 增加 `d.status = 'ready'` | `services/search_service.py` |
| R-8 | 补齐 conversations/messages 端点 | 新增 `POST /conversations`、`GET /conversations`、`GET /conversations/{id}/messages`、`DELETE /conversations/{id}`；chat 发消息时更新 `conv.updated_at` | `api/chat.py` |
| R-9 | SSE error payload 对齐 API_SPEC | 错误事件改为 `{type, code, message}`（`INTERNAL_ERROR`） | `api/chat.py`、`tests/test_chat.py` |
| R-10 | chat message 上限 | `message` 增加 `max_length=4000` | `api/chat.py` |
| R-11 | 前端生产构建失败 | `tsconfig.app.json` 排除 `src/__tests__`、`src/test`，`npm run build` 通过 | `frontend/tsconfig.app.json` |
| R-12 | 前端注册页与聊天闭环 | RegisterPage 实现注册表单；Dashboard 增加工作区/知识库列表与创建、跳转聊天；ChatPage 增加错误展示与缺知识库提示 | `frontend/src/pages/*`、`frontend/src/api/workspaces.ts`（新） |
| R-13 | 前端 refresh token 与自动续签 | authStore 保存 `refresh_token`，登出调用后端 logout；client 响应拦截器 401 时自动 refresh 并重放 | `frontend/src/stores/authStore.ts`、`frontend/src/api/client.ts`、`frontend/src/api/auth.ts` |
| R-14 | 上传 magic-bytes 校验 | 上传先读 8 字节做签名校验（PDF/DOCX/文本 NUL 检查），与扩展名/Content-Type 一致 | `api/documents.py` |
| R-15 | 统一错误响应结构 | 全局 `HTTPException` handler 输出 `{code, message, detail}`（400/401/403/404/409/413/429/500 映射） | `app/main.py` |
| R-16 | 跨租户 404 文案统一 | kb/doc/workspace/model_config 的 404 消息统一为中性「资源不存在」，消除资源存在性枚举 | `services/kb_service.py`、`api/model_configs.py`、`api/workspaces.py` |
| R-17 | 迁移文件尾随空格 | 清理 `alembic/versions/...py:4` 尾随空格，`git diff --check` 通过 | `alembic/versions/4426ee145861_create_platform_tables.py` |

**测试环境说明**：后端测试依赖本地 PostgreSQL（`localhost:5432/agentkb`），需先执行 `alembic upgrade head`；conftest 通过 monkeypatch 将 `token_store` 替换为内存实现，避免测试依赖 Redis。

## 7. 整分支三次复核修复（2026-08-07，二次审查闭合）

二次审查确认以下问题后修复，均附测试/构建/运行证据：

| # | 修复项 | 说明 | 涉及文件 |
|---|--------|------|----------|
| R-18 | 成员角色不可设为 owner | `MemberRoleUpdateRequest.role` 收敛为 `Literal["admin","member"]`，`PATCH .../members` 传 `owner` 返回 400 | `api/workspaces.py` |
| R-19 | logout 绑定当前用户 | logout 校验 refresh token `sub` 与当前 access token 用户一致，跨用户注销返回 403 | `api/auth.py` |
| R-20 | Redis 认证 fail-closed | `store_refresh_token`/`revoke_refresh_token` 失败不再吞掉：login 返回 503、logout 返回 503，避免签发不可用 token 或伪注销 | `core/token_store.py`、`api/auth.py` |
| R-21 | 前端 chat 自动续签 | `streamChat` 改用带 401 refresh/重试的 `fetchWithRefresh`，不再绕过 Axios 续签逻辑 | `frontend/src/api/chat.ts` |
| R-22 | 前端可创建首个工作区 | Dashboard 增加创建工作区表单，创建后自动选中并加载知识库 | `frontend/src/pages/DashboardPage.tsx` |
| R-23 | 上传 volume 非 root 可写 | Dockerfile 预建 `/tmp/uploads` 并 `chown appuser`，实测命名 volume 首次挂载后 appuser 可写 | `backend/Dockerfile` |
| R-24 | 被移出成员不可访问历史会话 | `_conv_for_user` 校验会话关联知识库所在 workspace 的当前成员关系 | `api/chat.py` |
| R-25 | SETUP/Makefile/Compose 一致 | `make up` 只启动 db/redis；`make migrate` 改 `docker compose run`；新增 `make dev`（全栈容器 + 本地 vite）；SETUP 环境文件复制与健康检查地址对齐实现 | `Makefile`、`docs/references/SETUP.md` |
| R-26 | 全局异常统一 JSON | 新增 `Exception` handler，500 返回 `{code,message,detail:{request_id}}`，不泄露堆栈 | `app/main.py` |
| R-27 | access token 过期返回 TOKEN_EXPIRED | `get_current_user` 捕获 `ExpiredSignatureError`，错误处理器支持 dict detail 透传错误码 | `api/deps.py`、`app/main.py` |
| R-28 | chat source 补 filename | `_chunk_sources` 关联 Document 返回 `filename`，来源与历史消息展示一致 | `api/chat.py` |
| R-29 | docx/pdf 占位不伪装 ready | `_extract_text` 对未实现格式抛 `NotImplementedError`，文档进入 `failed` 而非空 `ready` | `tasks/parse_document.py` |

新增回归测试：`test_logout_cannot_revoke_other_users_token`、`test_expired_access_token_returns_token_expired`、`test_update_member_role_rejects_owner`、`test_removed_member_cannot_access_conversation`，并扩展 `test_chat_sources_reference_retrieved_chunks` 断言 `filename`。

**验证**：后端 `pytest backend/tests -q` → **84 passed**；前端 `vitest run` → **3 passed**；`npm run build` 通过；`ruff check` 通过；命名 volume 非 root 写入实测通过。

## 8. 整分支四次复核修复（2026-08-07，三次审查闭合）

| # | 修复项 | 说明 | 涉及文件 |
|---|--------|------|----------|
| R-30 | 无效 `conversation_id` 不再静默新建会话 | `/chat` 严格区分「未传 ID」与「传入但查无此会话」，后者返回 404 | `api/chat.py` |
| R-31 | chat source 对齐 API_SPEC schema | 来源对象输出 `filename`/`content`/`score`；`hybrid_search` 返回带 RRF 归一化分数的 `SearchHit`（0~1），SSE、非流式与历史消息三处一致 | `api/chat.py`、`services/search_service.py`、`services/chat_service.py`、`rag/retriever.py` |
| R-32 | 认证失败不再递归 logout | 新增 `clearAuth` 仅清空本地状态；401 interceptor 与 `fetchWithRefresh` 失败路径改调 `clearAuth`；`/auth/logout` 改用无 interceptor 的裸 axios 并携带 access token | `frontend/src/stores/authStore.ts`、`frontend/src/api/client.ts`、`frontend/src/api/auth.ts`、`frontend/src/api/chat.ts` |
| R-33 | Dashboard 创建工作区竞态 | 用请求序号使首次 `wsApi.list()` 的迟到响应失效，避免覆盖新创建的工作区 | `frontend/src/pages/DashboardPage.tsx` |
| R-34 | ChatPage 请求级异常提示 | `send()` 包 try/catch，网络/HTTP 错误展示到页面 `error` 状态 | `frontend/src/pages/ChatPage.tsx` |
| R-35 | SETUP 第 4 节配置对齐实现 | 环境文件改为 `backend/.env`，连接串改为容器内 `db`/`redis` 服务名与 `agentkb` 库名 | `docs/references/SETUP.md` |
| R-36 | PDF/DOCX 占位失败回归测试 | 参数化测试验证 pdf/docx 上传后进入 `failed` 且带用户可见错误信息 | `tests/test_knowledge_bases.py` |

新增回归测试：`test_chat_unknown_conversation_returns_404`、`test_unimplemented_document_formats_are_failed`、`authStore.clearAuth` 测试；`test_chat_sources_reference_retrieved_chunks` 断言完整 schema（filename/content/score）。

**验证**：后端 `pytest backend/tests -q` → **87 passed**；前端 `vitest run` → **4 passed**；`npm run build` 通过；`ruff check` 通过；`git diff --check` 通过。

**仍为已接受后续项（不属本轮缺陷）**：真实 embedding/LLM/rerank 接入、docx/pdf 真实抽取、SSE 与历史消息的 `score` 目前来自 RRF 归一化（真实 rerank 分数接入后替换）、认证/chat 限流与 token 配额、`model_config_revision` 不可变历史、不可变审计事件、`(document_id, position)` 唯一约束、对象存储替换本地路径。

## 9. P2 简历解析流水线（F6）实现偏差（2026-08-08）

> 范围：分支 `p2-resume-parsing`（`bd3126b..7afb076`，12 个提交）。计划《2026-08-07-p2-resume-parsing》全部 11 个任务完成，主链路由任务级测试与全量回归覆盖。以下为与计划/PRD 的出入，均不改变 PRD 语义。

| # | 出入点 | 依据 | 实现 | 性质 |
|---|--------|------|------|------|
| P-1 | 全局 `app/rag/embedder.py` 占位行为保留 | deviation-log §4「真实 embedding → P2」；A-16 | 简历流水线直连 `EmbeddingClient`（workspace model_config）；F5 chat 与 KB chunks 仍用占位向量，真实 KB 向量化留 P3 | A-16 既定裁决 |
| P-2 | 上传格式含 pdf | PRD F6 ① 列 doc/docx/txt/csv/json；A-19 | `ALLOWED_FORMATS` 含 pdf（抽取器/安全/内容类型全线支持），不影响评测 format（doc/docx/txt） | A-19 既定裁决 |
| P-3 | `classify_failure` 补 `TimeoutError/ConnectionError` 直接判定 | 计划测试断言 timeout 可重试，但实现仅查文本关键词（空消息漏判） | 流水线/任务失败分类与 `classify_llm_error` 语义一致 | 计划文档缺陷修复（测试先行） |
| P-4 | pypdf 6.x 测试写法 | 计划 `_MINIMAL_PDF` 无 xref/`%%EOF`、`append_blank_page` 在新版移除 | 测试改用 pypdf 原生构造带 Helvetica 的文本页；PDF 抽取器实现不变 | 依赖版本适配 |
| P-5 | `TextExtractor.extract` 契约 | 计划测试传字符串被当作路径 | 测试改用 bytes（str=路径、bytes=内容，与 `extract_resume` 一致） | 用例修正 |
| P-6 | 迁移文件名 | 计划示例 `8f4e2d1a9c0b` 为占位 | autogenerate 实际生成 `3fc5f2ab57e8`；`search_tsv` 已是 TSVECTOR variant，无需手工改列 | 名义差异 |
| P-7 | ruff 适配 | 计划示例代码未过新 ruff（0.16） | SIM115/PLW1510/DTZ011/ASYNC230/B008/RUF023 等按库内既有约定修复（`Path.read_bytes`、`# noqa: B008` 等） | 实现级清洁 |
| P-8 | 画像 `domain` 等开放枚举 | plan review B-2 已修 | `validate_profile_json` known 集合含 `domain`；开放枚举仅校验类型/长度 | 计划审查修复 |
| P-9 | evidence 覆盖率 | plan review D-2 已修 | 仅锚定校验（quote 逐字存在），不做逐字段全覆盖；幻觉由评测 scorer 阻断 | 计划审查修复 |

**验证**：后端 `pytest backend/tests -q` → **153 passed**；`ruff check .` → All checks passed；Celery 任务列表含 `app.tasks.parse_document.parse_document` 与 `app.tasks.parse_resume.parse_resume`；`alembic upgrade head` 迁移 trigger 实测 `search_tsv @@ plainto_tsquery('simple','Spring')` 命中。

**遗留待办（需真实凭据，未纳入本次代码提交）**：工作区 `model_configs` 写入真实 llm（deepseek-chat）与 embedding（bge-m3）配置（经出站网关仅 HTTPS）——需用户提供 API Key 与端点；`.env` 生产油管（JWT/MODEL_KEY_ENC_KEY 现仅测试值）。

## 10. P2 整分支合规复核修复（2026-08-08）

对 P2 分支做 PRD/四份 spec 对照合规模块审查，修复以下问题（均附回归测试）：

| # | 修复项 | 依据 | 实现 |
|---|--------|------|------|
| R-P1 | 内容 hash 幂等键缺失 | spec §3.4 双幂等键：`workspace_id+upload_id`（已实现）+ `workspace_id+文件内容hash+模板版本+source_channel`（缺失） | 新增 `_find_runs_by_content`；二进制文件 sha256 与 CSV/JSON 行级 `row_hash` 均按内容键复用既有 run，不重复创建；`retry` 仍生成新 run_id 不受内容去重影响 |
| R-P2 | 上传整批常驻内存（≤100×20MB≈2GB） | MVP §3.3 单批 ≤100 份、≤20MB | 二进制文件改用 `_stream_to_disk` 流式落盘（边写边算 sha256，内存 O(单文件块)）；CSV/JSON 单文件仍受 20MB 限制；批内任一失败清理已落盘文件，保持「无半批 commit」 |
| R-P3 | JSON import 无 records 上限、请求体无大小限制 | PRD F6 ① 单批 ≤100 份 | `parse_json_envelope` 增加 `MAX_RECORDS=100` 拒收超限；`main.py` 增加 import 路径请求体 Content-Length ≤10MB 中间件（双保险） |
| R-P4 | 重试重复扣费（LLM 成功后再调用失败重试会重跑 LLM） | PRD F6「重试不重复扣费」 | 新增 `parse_checkpoints` 表（`run_id` PK）：LLM 结构化 + 画像结果与 PII 映射（AES-GCM 密文）在 LLM 阶段落检查点；重试/重启时 `_load_checkpoint` 复用，不再调用 LLM。evidence/profile 无身份 PII 明文 JSONB 存储 |
| R-P5 | 并发重复投递 spurious `parse.run.failed` 审计 | PRD F6 幂等 | `_mark_terminal` 改为条件 `UPDATE ... WHERE status IN (pending, processing)`，rowcount=0 时跳过；绝不覆盖已发布 success，也不产生伪失败审计 |
| R-P6 | CSV 汇总字段无 ≤2000 校验 | spec §3.2 单字段 ≤2000 拒收该行 | `parse_csv_bytes` 对 `max_education_desc/max_work_desc` 超长逐行报错 |
| R-P7 | `years_experience` 非法时间未标记 conflict | spec §1.8 缺失 start / end<start 计入「待人工确认」 | `detect_conflicts` 补充缺失开始时间（type=other）与结束早于开始（type=value_conflict）冲突 |
| R-P8 | 姓名脱敏仅覆盖提示词式 | PRD F6 ④ taxonomy 含姓名 | `_NAME_RE` 标签扩展 `联系人/英文名`（如「联系人：李四」出站前同样脱敏）；A-15 仍保留「姓名明文本地落库、不任意掩码正文」裁决 |
| R-P9 | `identity_hashes(name,...)` 死参数 | 实现清洁 | 移除未使用的 `name` 参数，同步 3 处调用点 |
| R-P10 | skills 未去重归一化 | spec §3.6 无序集合去重 | 新增 `normalize_skills`（去空白、去重、保序），LLM 与导入两条路径统一应用；canonical 别名词典仍随评测 bundle 冻结（P3/M3） |

**验证**：后端 `pytest backend/tests -q` → **166 passed**（新增 13 条回归：检查点往返/流水线检查点复用/`_mark_terminal` 原子性/内容去重/records 上限/CSV 超长/derive conflict/skills 归一化/姓名标签）；`ruff check backend/app backend/tests` → All checks passed；`alembic downgrade → upgrade` 往返通过；Celery 两任务注册正常。
## 11. P3 对话式搜人（F7）实现与偏离（2026-08-08）

> 范围：分支 `p3-candidate-search`（基于 main @ `4812dbb`），计划《2026-08-08-p3-candidate-search》10 个任务全部完成。以下为 S-1~S-12 裁决之外的实际偏离。

| # | 出入点 | 依据 | 实现 | 性质 |
|---|--------|------|------|------|
| S-D1 | 三池候选状态补齐 | 评测 spec §2.2 池枚举 active/rejected/hired；P2 `CandidateStatus` 仅 active/deleted/purged/pending_review | 枚举新增 `rejected`/`hired` + PG enum `ALTER TYPE` 迁移（`8fce2a1b3d4e`）；池生命周期流转（F15/M5）仍留后续 | 实现前置（M4 最小 ACL 需要池值） |
| S-D2 | 画像字段读取路径 | 计划任务 7 说明画像存 `profile_json` 而非 `structured_data` | `_attach_profile` 从 `candidate_revisions.profile_json`（latest_revision 关联）并入卡片 `profile` | 计划澄清 |
| S-D3 | 检索两路召回 + JSONB 过滤 | 计划 S-2 三路 | 向量一路取每候选最小余弦距离（`MIN(embedding <=> :q)` 聚合需 `.cast(Float)` 否则 pgvector 类型处理器误解析）；全文走 `search_tsv @@ plainto_tsquery`；条件过滤用 JSONB `->>` 操作符表达式（`text()` TextClause 不支持 `==`，会退化为 Python False） | 实现修正（测试先行） |
| S-D4 | 非流式响应路径 | 计划任务 8 预览代码在 async def 内 `asyncio.run` 会报错 | 非流式直接调 `run_search_flow` 构建响应，与 SSE 共用 `_execute` | 计划文档缺陷修复 |
| S-D5 | 会话成员校验 | 计划引 `ensure_member`（resumes 域） | 搜人端点独立 `_ws_membership`（workspace_members 校验），避免跨域耦合 | 实现级清洁 |
| S-D6 | follow_up 删除条件形状 | 测试用例 `field:"city"` 与先验 `fields:["city","expected_city"]` 键不匹配 | 删除条件需与先验同形状（`fields` 数组）；`_field_key` 按字段组合匹配 | 用例修正 |

**验证**：后端 `pytest backend/tests -q` → **190 passed**（main 166 + P3 新增 24）；`ruff check backend/app backend/tests` → All checks passed；前端 `npm run build` 通过、`vitest run` → 4 passed；`git diff --check` 通过。

### P3 代码审查修复（2026-08-08，合并前）

对 P3 分支做独立代码审查（reviewer 实测复现 2 个 Critical），全部修复并附回归测试：

| # | 修复项 | 说明 |
|---|--------|------|
| R-S1 | 画像条件过滤静默失效（Critical） | `level`/`domain`/`management` 条件原读 `structured_data`（不含画像），恒返回空。改为 `requires_profile_join` 时 JOIN latest_revision 读 `profile_json->'values'`；命中标注统一在 cards 层（含 profile）计算。回归：`test_profile_condition_filter_matches_candidate`/`_does_not_leak_wrong_level`（真实 profile_json 形状） |
| R-S2 | 数量意图 requested_count 失效（Critical） | `top_k` 硬编码 20，`requested_count=50` 最多返 20、「找 3」返 20 不截断。改为 `top_k = max(20, min(requested, 100))` 放大召回 + 返回截断 + summary 区分。回归：`test_search_chat_requested_count_truncates_cards` |
| R-S3 | 多轮 context 在拒答/闲聊轮后丢失 | `_load_context` 只读最新 assistant 消息；拒答轮 `sources=[]` 导致上下文清空。改为回退查找最近含 context 的 assistant 消息。回归：`test_load_context_falls_back_across_refusal` |
| R-S4 | rerank 输入文档过弱 | 文档由「姓名+命中标签」改为候选 `search_text`（含技能/岗位/摘要），提升排序语义信号 |
| R-S5 | `range_degree` 语义与死代码 | 精确 `==` 改 ordinal `>=`（启用 `DEGREE_ORDINAL`），`_match_conditions` 补 `range_degree` 命中标注。回归：`test_range_degree_matches_ordinal_ge` |
| R-S6 | LLM 输出值类型未校验 | `years_experience=“5年”` 会 `int()` 抛 500。`validate_conditions` 按 op 校验 value 类型（None 为 follow_up 删除标记放行）。回归：`test_invalid_value_type_rejected` |
| R-S7 | 审计事件缺 actor_id | `run_search_flow` 增加 `actor_id` 透传 `add_event`；审计 payload 不再存原始 utterance（评测 §3.8 脱敏要求） |

**复核验证**：后端 `pytest backend/tests -q` → **197 passed**；`ruff check` → All checks passed；前端 `vitest run` → 4 passed、`npm run build` 通过。

**仍为已接受后续项（不属本轮缺陷）**：M4 评测 bundle（查询集/fixture/scorer，需下载 AI Studio 数据集）；F10 职位管理与 job_search 意图；F11 统计查询；F15 完整三池流转（M5）；画像标注子集升级 `profile_dependent_search` 硬门槛；真实模型凭据（llm/embedding/rerank model_config + `.env`）写入留用户提供。

## 12. P4 候选人管理（F8）实现与偏离（2026-08-08）

> 范围：分支 `p4-candidate-management`（基于 main @ `fc4a0bd`），计划《2026-08-08-p4-candidate-management》9 个任务全部完成。以下为 C-1~C-8 裁决之外的实际偏离。

| # | 出入点 | 依据 | 实现 | 性质 |
|---|--------|------|------|------|
| C-D1 | 合并视图数组 override 用索引路径 | spec §2 关键字段配对 | `set_path/get_path` 支持 `work[0].title` 索引路径；数组元素关键字段配对与增删元素留后续 | C-1 既定裁决 |
| C-D2 | hired 详情可见性测试 | F9 矩阵 | 测试改为验证 owner 可见 hired（member 排除由 list scopes 测试覆盖；创建者即 owner，无法在 API 测试中构造 member 视角） | 用例口径 |
| C-D3 | 生命周期访问 deleted | C-6 deleted 仅显式可见 | `_visible_candidate(allow_deleted=True)` 供 restore/purge，详情/修正仍拒绝 deleted | 实现修正 |

**验证**：后端 `pytest backend/tests -q` → **209 passed**（main 197 + P4 新增 12）；`ruff check backend/app backend/tests` → All checks passed；前端 `npm run build` 通过、`vitest run` → 4 passed；`git diff --check` 通过。

**仍为已接受后续项（不属本轮缺陷）**：多人对比 + AI 对比分析；查重合并动作（F12）；override 数组关键字段配对与增删元素；重新解析（F8 re-parse）与并发；面试安排/反馈时间线（F13/F14）；purged 后台定时清理。

### P4 代码审查修复（2026-08-08，合并前）

独立审查（reviewer 实测复现）发现 1 Critical + 6 Important，全部修复并补回归测试：

| # | 修复项 | 说明 |
|---|--------|------|
| R-C1 | 备注超长 500（Critical） | `title` 列 String(256) 被塞入整段备注（≤2000），>250 字符即 500。title 截断至 200（内容完整存 detail）。回归：备注 300 字符 API 用例 |
| R-C2 | `set_path` 静默丢写（Important） | 路径穿越标量中间节点时新容器未写回父。改为父节点写回；回归 `test_set_path_writes_back_intermediate_containers` + API 用例 |
| R-C3 | `source_channel` 筛选重复行（Important） | JOIN 按文件数放大结果。改 EXISTS 子查询 |
| R-C4 | 列表筛选不过合并视图（Important） | 技能/城市/年限/学历筛选读 raw structured_data，绕过 override。**记录为已知限制**（P3 搜人同口径），SQL 侧合并视图成本高留后续 |
| R-C5 | 详情页固定第一工作区（Important） | 列表页经 `?ws=` 透传 wsId，详情页优先读 query |
| R-C6 | 前端缺筛选控件（Important） | 补城市/学历/年限筛选；（hired/deleted 选项对 member 返回 404 属隐私一致响应，记录） |
| R-C7 | 测试覆盖 + 杂项（Important/Minor） | 补列表 API 级测试（include_deleted/owner 可见 hired）、非法字段路径、restore/purge 跨租户 404；purge 审计去明文 name 仅留 hash；移除死代码/冗余索引；事件往返断言改 `==` |

**复核验证**：后端 `pytest backend/tests -q` → **213 passed**；`ruff check` → All checks passed；前端 `vitest run` → 4 passed、`npm run build` 通过。

## 13. P5 职位管理（F10）实现与偏离（2026-08-08）

> 范围：分支 `p5-job-management`（基于 main @ `608ca73`），计划《2026-08-08-p5-jobs》8 个任务全部完成。以下为 J-1~J-9 裁决之外的实际偏离。

| # | 出入点 | 依据 | 实现 | 性质 |
|---|--------|------|------|------|
| J-D1 | `alembic autogenerate` 重复创建 `override_action` enum | P4 已建 `override_action` PG enum | 迁移改 `postgresql.ENUM(... create_type=False)`（`sa.Enum` 在 SQLAlchemy 2.0.51 不暴露 create_type，静默透传导致在线模式仍发 CREATE TYPE）；并剔除 autogenerate 误判的 `ix_candidate_events_candidate_id` drop（P4 遗留漂移，与 P5 无关） | 实现修正 |
| J-D2 | `resolve_job` 仅匹配 open 职位 | J-3 同名多选；但 closed 职位按名引用应明确报「已关闭」 | `resolve_job` 改为全状态按名匹配：open 唯一→直接；open 多个→候选列表（仅列 open）；无 open 命中但存在 closed→返回给 flow 报「已关闭」 | 实现修正（测试先行） |
| J-D3 | `job_matches` 端点 rerank | PRD F10 职位→人「同用检索+rerank 链路」 | matches 端点补 rerank（`ModelCallError` 降级保持混合检索顺序），与 `search_chat` 一致；测试 fake rerank 抛 `ModelCallError` | 计划补充 |
| J-D4 | 测试种子候选需可召回 | 匹配/检索依赖向量 + search_tsv | `_seed_active_candidate` 补 CandidateRevision + CandidateEmbedding（唯一 run_id 规避跨会话残留）；候选人详情测试改为 API 注册 owner + 建工作区，避免直插用户密码非 bcrypt 导致登录 `Invalid salt` | 用例修正 |

**验证**：后端 `pytest backend/tests -q` → **233 passed**（main 213 + P5 新增 20）；`ruff check backend/app backend/tests` → All checks passed；前端 `npm run build` 通过、`vitest run` → 4 passed；`git diff --check` 通过。

**仍为已接受后续项（不属本轮缺陷）**：完整 F13 指派管道（职位关闭余下指派规则）；面试安排/反馈时间线；查重合并动作（F12）；F11 统计查询；真实模型凭据（llm/embedding/rerank model_config + `.env`）写入留用户提供；M4 评测 bundle（含 §2.2 职位 fixture 的最终冻结）。

### P5 代码审查修复（2026-08-08，合并前）

独立审查（reviewer 实测复现）发现 1 Critical + 4 Important + 8 Minor，Critical/Important 全部修复并补回归测试：

| # | 修复项 | 说明 |
|---|--------|------|
| R-J1 | 多轮 job_search 切职位失败（Critical） | 第二轮带新 `job_title` 时被上一轮 `job_id` 覆盖返回错误职位。改为仅当本轮无任何职位引用时才回退 prior job_id。回归：`test_job_search_switch_job_in_next_turn_not_stuck` |
| R-J2 | follow_up 提示词与校验器矛盾（Important） | 规则 5 宣称 follow_up 保留 job_id，但校验器拒绝非 job_search 携带 job 引用。删去规则 5 中 job_id 保值表述（follow_up 经 conditions 继承岗位 AST） |
| R-J3 | 乐观锁 TOCTOU（Important） | `update_job` 内存比较 + 非原子 `MAX(revision)+1`，并发 PATCH 可绕过。改为 `SELECT ... FOR UPDATE` 行锁串行化 |
| R-J4 | 多字段条件副字段 override 静默矛盾（Important） | `field_path=expected_city` 会追加而非替换，AND 语义致零结果。API 层校验 field_path ∈ 条件主字段集（`PRIMARY_CONDITION_FIELDS`），副字段 400。回归：`test_override_rejects_secondary_field_path` |
| R-J5 | job_candidates SSE 无测试（Important） | 补 API 级流式断言（`test_search_chat_streams_job_candidates`） |
| R-J6 | 解析失败返回 500 非 502（Minor） | create/update 捕获 `SearchSchemaError`/`ModelCallError` → 502「岗位要求解析失败」 |
| R-J7 | `job_matches` 负数 limit 切片陷阱（Minor） | `limit = max(1, min(limit, 100))` 前置 clamp |
| R-J8 | override 查询顺序不稳定（Minor） | `job_matches`/`job_matcher` override 查询补 `order_by(id)`，与 detail/flow 一致 |

**复核验证**：后端 `pytest backend/tests -q` → **236 passed**；`ruff check` → All checks passed；前端 `npm run build` 通过、`vitest run` → 4 passed；`git diff --check` 通过。

**新增已接受后续项（M-8 等）**：PRD「匹配缓存（job_id+revision+模型版本）」MVP 收口未实现；`suitable_jobs_for_candidate` N+1（open 职位多时优化）；`jobs.py` 与 `flow.py` 模型客户端辅助重复（收敛留后续）；JobDetailPage 502 与"不存在"错误提示未区分。

## 14. P6 查重合并与内推归属（F12 剩余）实现与偏离（2026-08-09）

> 范围：分支 `p6-merge-referral`（基于 main @ `fe4d6f6`），计划《2026-08-08-p6-merge-referral》4 个任务全部完成。查重检测（姓名 + phone/email hash → pending_review）与来源渠道采集已在 P2/P4 落地，本轮仅落地**合并动作**与**内推归属展示**。以下为 N-1~N-6 裁决之外的实际偏离。

| # | 出入点 | 依据 | 实现 | 性质 |
|---|--------|------|------|------|
| N-D1 | 合并需解析记录前置 | N-1「无可合并的解析记录」在无 revision 时抛 400 | 测试修正：合并 API 用例补 CandidateRevision（列表 base 本就 JOIN latest_revision，无 revision 的候选人不可见） | 用例修正 |
| N-D2 | 测试种子用户密码 | 直插 User(hashed_password="x") 导致 API 登录 `Invalid salt` | merge API 测试改 API 注册 + 建工作区 + DB 补种候选人/文件（与 P5 R-J 同模式） | 用例修正 |
| N-D3 | 合并后恢复语义 | N-2 被并入者软删 30 天可恢复 | 记录为已知边界：恢复后为独立候选人，其历史已重挂主体，数据以主体副本为准 | 已接受边界 |

**验证**：后端 `pytest backend/tests -q` → **241 passed**（main 236 + P6 新增 5）；`ruff check backend/app backend/tests` → All checks passed；前端 `npm run build` 通过、`vitest run` → 4 passed；`git diff --check` 通过。无迁移（`merged` 事件走 String(32) 纯 Python 扩展）。

**仍为已接受后续项（不属本轮缺陷）**：模糊查重（向量相似度，P1 预留）；合并后被并入者恢复为独立候选人；重新解析（F8 re-parse）与并发；F13 指派管道（职位关闭余下指派规则）；面试安排/反馈时间线；F11 统计查询；真实模型凭据写入。

## 15. P7 招聘管道与待面试表（F13）实现与偏离（2026-08-09）

> 范围：分支 `p7-assignments`（基于 main @ `a4e0018`），计划《2026-08-08-p7-assignments》6 个任务全部完成。以下为 P-1~P-8 裁决之外的实际偏离。

| # | 出入点 | 依据 | 实现 | 性质 |
|---|--------|------|------|------|
| P-D1 | 批量指派同 key 内部互相去重 | P-7 幂等语义 | 批量为同一 idempotency_key 时，create_assignment 幂等检查会命中第一条，导致只建一条。改为按候选人派生 key（`{key}:{candidate_id}`）——整批重复提交仍整体幂等，单批内不互相去重 | 实现修正（测试先行） |
| P-D2 | 重复指派同一职位返回 409 而非 400 | P-1 唯一约束 | 唯一约束 IntegrityError→409。create_assignment 增加 (candidate, job) 预检，抛 `AssignmentError`（干净 400「该候选人已在本职位流程中」） | 实现修正 |
| P-D3 | 测试跳转路径 | P-2 转移矩阵 | 测试用例曾直接从 pending_screen 跳 offer（非法）。改为按矩阵走 screen_passed→interviewing→offer；hired 后不可再建指派（入职员工禁止重新指派）用单独职位验证非法跳转 | 用例修正 |
| P-D4 | `_adjust_hc` 双重递减 | P-4 offer→hired 只释放一次 reservation | 初版 offer→hired 重复 `hc_reserved-=1`；改为「离开 offer 释放 + 进入 hired 转 filled」各一次；hire 聚合关闭其余指派时先取 prev 再调整（避免用已改 status 作 prev） | 实现修正（测试先行） |

**验证**：后端 `pytest backend/tests -q` → **247 passed**（main 241 + P7 新增 6）；`ruff check backend/app backend/tests` → All checks passed；前端 `npm run build` 通过、`vitest run` → 4 passed；`git diff --check` 通过。迁移 `10421097d4d1`（assignments 表 + job_status… + jobs.hc_reserved/hc_filled）。

**仍为已接受后续项（不属本轮缺陷）**：F14 面试安排/反馈闸门（interviewing→offer 需 recommend、screen_passed→interviewing 需安排面试）、多轮 interview_round、反馈 AI 总结、48h 超时提醒；F15 查重联动（rejected/hired 再上传提示池归属）；职位关闭后 interviews 完成/转派完整流转；批量指派整批超 HC 的逐条语义。

### P7 代码审查修复（2026-08-09，合并前）

独立审查（reviewer 实测复现）发现 2 Critical + 3 Important + 若干 Minor，Critical/Important 全部修复并补回归测试：

| # | 修复项 | 说明 |
|---|--------|------|
| R-A1 | `closed_by_job` 状态不可达（Critical） | 转移矩阵各状态均未含 closed_by_job，admin 关闭余下指派整体失效（职位关闭后流程僵死）。补入每个非终态转移集；回归 `test_closed_by_job_and_offer_rejected_pool` + API 权限用例（admin 成功 / member 403） |
| R-A2 | `transition` 可直达 hired 绕过入职聚合（Critical） | 直接 hired 会泄漏 reservation、遗留悬空 offer。`hired` 从 offer 转移集移除，仅由 `hire()` 聚合入口产生；回归 transition→hired 被拒 |
| R-A3 | 迁移无 server_default 必挂（Important） | `jobs.hc_reserved/hc_filled` ADD COLUMN NOT NULL 无 DEFAULT，生产升级（jobs 非空）必失败。加 `server_default=sa.text('0')`；downgrade→upgrade 往返验证（需手删残留 enum，alembic 已知行为） |
| R-A4 | 候选池重算/入职聚合无锁（Important） | 并发终态流转/双入职可致池计算错误、交叉覆盖。`create_assignment`/`transition`/`hire` 均加候选级 `SELECT FOR UPDATE`（一致顺序：职位锁→候选锁，避免死锁） |
| R-A5 | 非法 to_state 500（Minor） | `AssignmentStatus(to_state)` ValueError 未捕获。改抛 `AssignmentError`（400） |
| R-A6 | 前端幂等 key 缺失 + 批处理 key 溢出 + 空输入（Minor） | assign 调用补 `idempotency_key`（Date.now）；批量派生 key `[:64]` 截断；`doAssign` 空输入返出 |

**结论（I3 记录）**：PRD F13 第 359 行「并发操作以指派记录乐观锁（revision）防覆盖」未建 revision 列，由候选级行锁（R-A4）串行化同一候选人全部流转/入职/重算覆盖该意图（后到者按矩阵/终态拒绝），台账记录为已接受实现选择。

**复核验证**：后端 `pytest backend/tests -q` → **249 passed**；`ruff check` → All checks passed；前端 `npm run build` 通过、`vitest run` → 4 passed；`git diff --check` 通过。

## 16. P8 面试安排与反馈闭环（F14）实现与偏离（2026-08-09）

> 范围：分支 `p8-interviews`（基于 main @ `32810d6`），计划《2026-08-08-p8-interviews》5 个任务全部完成。以下为 I-1~I-7 裁决之外的实际偏离。

| # | 出入点 | 依据 | 实现 | 性质 |
|---|--------|------|------|------|
| I-D1 | 首次反馈不写 history | I-1「修改产生新 revision 保留历史」 | `submit_feedback` 仅在已存在旧反馈时 append 到 `feedback_history`（首次提交即当前值，历史为空）；测试断言同步 | 实现澄清 |
| I-D2 | 状态机闸门波及 P7 测试 | I-2 收紧 interviewing/offer | P7 既有 `test_assignment.py`/`test_assignments_api.py` 中直达 interviewing/offer 的用例需先插 recommend 面试轮；新增 `_offer_ready_round` 辅助（直接插 InterviewRound 绕过 schedule_round 成员校验） | 用例同步 |
| I-D3 | 面试官成员校验在直插测试缺行 | I-6 面试官须为工作区成员 | DB 直插 workspace 的测试缺 owner 成员行，schedule_round 校验失败；测试补 `WorkspaceMember(owner)`（API 创建 workspace 时自动加 owner 成员，真实路径无此问题） | 用例修正 |
| I-D4 | `isnull()` 在 SQLAlchemy 2.0 不可用 | 超时查询 | 改用 `.is_(None)` | 实现修正 |

**验证**：后端 `pytest backend/tests -q` → **253 passed**（main 249 + P8 新增 4）；`ruff check` → All checks passed；前端 `npm run build` 通过、`vitest run` → 4 passed；`git diff --check` 通过。迁移 `efe269148628`（interview_rounds + feedback_conclusion enum）。

**仍为已接受后续项（不属本轮缺陷）**：面试日历集成（P2 预留）；AI 总结编辑（MVP 覆盖重生成，历史在 feedback_history）；超时提醒推送渠道（V1.1，MVP 为只读待办查询）；F15 查重联动提示（已由 pending_review + merge + 指派历史覆盖路径）；F11 统计查询。

### P8 代码审查修复（2026-08-09，合并前）

独立审查（reviewer 实测复现）发现 0 Critical + 4 Important + 若干 Minor，全部修复并补回归测试：

| # | 修复项 | 说明 |
|---|--------|------|
| R-I1 | 反馈/总结"先改后查" + 存在性侧信道（Important） | 服务层只按 round_id 加载，API 变更后才校验 workspace——任意成员可枚举全局 round 存在性。改为 API 层预检 `round 存在 && workspace 匹配` → 统一 404（不存在与他人工作区 round 均 404）。回归 `test_interview_cross_workspace_and_validation` |
| R-I2 | offer 闸门 `rounds[-1]` 未排序（Important） | 无 ORDER BY 取最新轮违反 SQL 契约。改 `order_by(round_no.desc()).limit(1)`，并补 `score is not None`（对齐 I-2「评分/评语完整」裁决文字） |
| R-I3 | summarize 不捕获 ModelCallError → 500（Important） | `except ModelCallError → 502`（对齐 jobs.py 模式） |
| R-I4 | round_no 并发递增非原子（Important） | `schedule_round` 加指派行锁 `with_for_update()` 串行化同指派并发安排 |
| R-I5 | 测试缺口（Minor） | 补跨工作区 404（feedback/summarize）、伪造 round 404、非法结论 400 |
| R-I6 | 前端缺 AI 总结按钮（Minor） | 补 `summarizeRound` 按钮（prompt 输入 round id） |

**记录为已接受边界**：`feedback_history` 无上限且条目无 by/at 元数据（后续可加版本化）；并发同轮反馈 last-write-wins（PRD 乐观锁条款仅覆盖指派流转）；`(assignment_id, round_no)` 唯一约束留后续（当前以行锁保证递增）；迁移 downgrade 不 drop enum（alembic 已知行为）。

**复核验证**：后端 `pytest backend/tests -q` → **254 passed**；`ruff check` → All checks passed；前端 `npm run build` 通过、`vitest run` → 4 passed；`git diff --check` 通过。

## 17. P9 人才库统计查询（F11）实现与偏离（2026-08-09）

> 范围：分支 `p9-statistics`（基于 main @ `07b7464`），计划《2026-08-09-p9-statistics》6 个任务全部完成。以下为 T-1~T-7 裁决之外的实际偏离。

| # | 出入点 | 依据 | 实现 | 性质 |
|---|--------|------|------|------|
| T-D1 | 统计条件过滤缺 candidates JOIN | T-3 去重口径 | 统计按 `candidates.id` 行去重、`COUNT(*)` 即人数；skills `contains` 条件经 `search_tsv @@ plainto_tsquery` 全文匹配（复用搜人编译规则），测试 fixture `search_text` 须含独立词 token（如 `"Java1 Java"` 而非 `"Java1"`，tsvector 精确词元匹配无前缀） | 用例修正 |
| T-D2 | 测试 run_id 用 `id(cand)` 跨用例冲突 | 测试夹具唯一性 | 改用 `uuid4().hex` 生成 `run_id`/`revision_id`（P7 R-A4 同因：对象 id 跨 GC 复用导致 revision_id 唯一约束冲突） | 用例修正 |
| T-D3 | 统计意图不调用 embedder/rerank | T-5 降本 | `_run_statistics` 仅依赖 LLM 意图抽取，测试用 `AssertionError` 哨兵断言 embedder/rerank 不被调用 | 实现确认 |

**验证**：后端 `pytest backend/tests -q` → **266 passed**（main 254 + P9 新增 12）；`ruff check backend/app backend/tests` → All checks passed；前端 `npm run build` 通过、`vitest run` → 5 passed；`git diff --check` 通过。

### P9 代码审查修复（2026-08-09，合并前）

独立审查（reviewer 实测复现）发现 1 Important + 若干 Minor，Important 修复并补回归测试：

| # | 修复项 | 说明 |
|---|--------|------|
| R-S1 | `stat_group_by` 不可哈希类型崩溃（Important） | 对 list/dict 执行 `in` 集合运算抛裸 `TypeError` 而非受控 `SearchExtractionError`。改为先校验 `isinstance(str)` 再判白名单。回归：`test_statistics_rejects_unhashable_stat_group_by` |
| R-S2 | `compute_statistics` 缺防御校验 + 死代码（Minor） | 复用 extractor `STAT_GROUP_BY`（删本地重复常量），入参 `group_by` 白名单校验抛 `ValueError`。回归：`test_compute_statistics_rejects_unknown_dimension` |
| R-S3 | 审计脱敏无测试锁定（Minor） | 断言 `search.statistics.executed` payload 为 `{"count","dimension"}` 且不含 "Java"（按 workspace 过滤避免多行）。回归：`test_statistics_flow_audit_payload_desensitized` |
| R-S4 | statistics+job 引用拒绝无测试（Minor） | 补 `test_statistics_rejects_job_ref`（校验器已拒绝，测试锁定） |

**记录为已接受边界**：多轮追问统计（"那城市分布呢？"跨意图收敛，MVP 单轮拒答为通用错误）；years_experience 分布按原始值分桶——冻结评测标准答案 fixture 时须对齐相同桶口径（否则 §3.7 macro accuracy 掉门槛）；统计卡片空桶补 0 展示留 UI 层（MVP 按出现桶返回）。

**复核验证**：后端 `pytest backend/tests -q` → **270 passed**；`ruff check` → All checks passed；前端 `npm run build` 通过、`vitest run` → 5 passed；`git diff --check` 通过。

**仍为已接受后续项（不属本轮缺陷）**：多轮追问统计（"那城市分布呢？"跨意图收敛，MVP 单轮）；统计查询标准答案 fixture 与评测 bundle 冻结（需下载 AI Studio 数据集）；历史条件统计（F15/M5 完整池流转）；统计卡片空桶补 0 展示（MVP 按出现桶返回，scorer 侧以 0 参与计算）。

## 18. 子项目一：MaxKB 精简内核 + 人事模块骨架（2026-08-13）

> 范围：新生产仓库 `/home/wzjames/toC/maxkb`（MaxKB v2 fork，基线 `65c5ff8`），计划《2026-08-12-maxkb-slim-kernel-and-hr-skeleton》6 个任务。本台账继续沿用"一架账"惯例。本计划执行仓库为 `maxkb`，偏离记录映射到对应 commit。

| # | 出入点 | 计划声明 | 实际实现 | 性质 | 人类决策 | 对应仓库/commit |
|---|--------|----------|----------|------|----------|------------------|
| S-D1 | 后端依赖裁剪 | 计划任务 3 声明"只改前端路由与视图层，不删后端代码"，裁剪范围注明"仅隐藏入口，不删除底层代码" | `5dd899c` 删除 `pyproject.toml` 40 行依赖（MCP 客户端、本地模型、厂商 SDK 等）并将对应 import 改为延迟导入 | 范围扩大（削薄内核） | **人类拍板：保留该 commit，且后续允许按需继续裁剪**（原版内容太多，加载/构建负担大） | `maxkb@5dd899c` |
