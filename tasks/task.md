<!-- Phase: Phase 6 - Task Split -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 任务总览看板

## 里程碑映射

| 里程碑 | PRD 定义 | 对应 Phase | 预计时间 |
|--------|----------|------------|----------|
| M1 | 基础设施 + Resume Parser | phase-1 + phase-2(T-009~T-015) + T-036(M1门控) | 第 1 周 |
| M2 | 检索与推荐核心 | phase-2(T-016~T-023) | 第 2 周 |
| M3 | 多轮对话 + 候选人操作 | phase-2(T-024~T-029) | 第 3 周 |
| M4 | API + 安全 + 联调 | phase-2(T-030~T-035) + phase-3(T-037~T-039) + phase-4 | 第 4 周 |

---

## Phase 1：跨模块基础设施（M1，第 1 周前半）

| # | 任务 | 对应 Spec | 对应 AC | 依赖 | 状态 |
|---|------|-----------|---------|------|------|
| T-001 | 容器化环境定义（Dockerfile + docker-compose.yml） | tech-decision.md 决策项12 | - | 无 | ✅ |
| T-002 | 项目骨架搭建（Python 包结构 + pyproject.toml） | tech-decision.md 依赖清单 | - | T-001 | ✅ |
| T-003 | 统一配置管理（config.py + .env） | tech-decision.md 决策项7/11 | - | T-002 | ✅ |
| T-004 | 统一错误码体系 | api-layer 04-business-rules RULE-008 | - | T-002 | ✅ |
| T-005 | 日志规范（structured JSON logging） | tech-decision.md 决策项14 | - | T-002 | ✅ |
| T-006 | 认证中间件（JWT + RBAC） | api-layer 04-business-rules RULE-001~004 | - | T-002, T-004 | ✅ |
| T-007 | MongoDB 连接 + ResumeStore 基础 CRUD | resume-store 00-overview | AC-001~003 | T-001, T-002 | ✅ |
| T-008 | Milvus 连接 + VectorIndex Collection 创建 | vector-index 00-overview | AC-001 | T-001, T-002 | ✅ |

---

## Phase 2：核心功能模块（M1~M4）

### M1：Resume Parser（第 1 周后半）

| # | 任务 | 对应 Spec | 对应 AC | 依赖 | 状态 |
|---|------|-----------|---------|------|------|
| T-009 | Resume Parser — PDF/DOCX 文本提取 | resume-parser 01 REQ-001/002 | AC-001~003 | T-002, T-003 | ✅ |
| T-010 | Resume Parser — DeepSeek-OCR 图片解析 | resume-parser 01 REQ-003 | AC-004 | T-009 | ✅ |
| T-011 | Resume Parser — LLM 结构化提取 | resume-parser 01 REQ-005 | AC-006 | T-009, T-003 | ✅ |
| T-012 | Resume Parser — 语义段落切分 + Skill 标准化 | resume-parser 01 REQ-006/007 | AC-007~008 | T-011 | ✅ |
| T-013 | Resume Parser — 解析失败降级 + PII 加密 | resume-parser 01 REQ-008, 04 RULE-004/007 | AC-009~010 | T-011, T-007 | ✅ |
| T-014 | Resume Store — 简历写入 + 查询 + 脱敏 | resume-store 00-overview | AC-001~007 | T-007, T-013 | ✅ |
| T-015 | Vector Index — Embedding 生成 + 向量写入 | vector-index 00-overview | AC-001~003 | T-008, T-012 | ✅ |

### M2：检索与推荐（第 2 周）

| # | 任务 | 对应 Spec | 对应 AC | 依赖 | 状态 |
|---|------|-----------|---------|------|------|
| T-016 | Intent Router — Intent 识别（LLM Function Calling） | intent-router 01 REQ-001/002 | AC-001~004 | T-002, T-003 | ✅ |
| T-017 | Intent Router — Slot 提取 + 意图路由分发 | intent-router 01 REQ-003/004 | AC-005~007 | T-016 | ✅ |
| T-018 | Intent Router — Fallback + Audit Log | intent-router 01 REQ-005/006 | AC-008~009 | T-016, T-005 | ✅ |
| T-019 | Recommendation Engine — Hybrid Retrieval | recommendation-engine 01 REQ-001~003 | AC-001~003 | T-015, T-016 | ✅ |
| T-020 | Recommendation Engine — Metadata Filter + Soft Match | recommendation-engine 01 REQ-004/005 | AC-004~005 | T-019 | ✅ |
| T-021 | Recommendation Engine — Rerank + 权重排序 | recommendation-engine 01 REQ-006/007 | AC-006~007 | T-020 | ✅ |
| T-022 | Recommendation Engine — 推荐理由生成 + Score Breakdown | recommendation-engine 01 REQ-008/009 | AC-008~009 | T-021 | ✅ |
| T-023 | Recommendation Engine — 降级策略 + 去重 | recommendation-engine 01 REQ-010~012 | AC-010~012 | T-022 | ✅ |

### M3：多轮对话 + 候选人操作（第 3 周）

| # | 任务 | 对应 Spec | 对应 AC | 依赖 | 状态 |
|---|------|-----------|---------|------|------|
| T-024 | Conversation Memory — 会话创建/查询/删除 | conversation-memory 01 REQ-001/002/010/011 | AC-001~004, AC-012~013 | T-007 | ✅ |
| T-025 | Conversation Memory — Slot 合并（增量/覆盖/重置） | conversation-memory 01 REQ-004~007 | AC-006~009 | T-024 | ✅ |
| T-026 | Conversation Memory — 检索范围决策 + 候选人引用 | conversation-memory 01 REQ-008/012 | AC-010, AC-014~015 | T-025, T-014 | ✅ |
| T-027 | recruitment.search 端到端流程 | intent-router + recommendation-engine | AC 全覆盖 | T-018, T-023 | ✅ |
| T-028 | recruitment.refine 端到端流程 | conversation-memory + recommendation-engine | AC 全覆盖 | T-026, T-027 | ✅ |
| T-029 | candidate.lookup + recruitment.compare | conversation-memory + resume-store | AC-014~015 | T-026, T-014 | ✅ |

### M4：API + 安全 + 前端（第 4 周前半）

| # | 任务 | 对应 Spec | 对应 AC | 依赖 | 状态 |
|---|------|-----------|---------|------|------|
| T-030 | FastAPI — /api/v1/chat（Streaming SSE） | api-layer 01 REQ-001 | AC-001~002 | T-027, T-006 | ✅ |
| T-031 | FastAPI — /api/v1/resumes/upload | api-layer 01 REQ-002 | AC-003~004 | T-014, T-006 | ✅ |
| T-032 | FastAPI — /api/v1/auth/login | api-layer 01 REQ-006 | AC-004~005 | T-006 | ✅ |
| T-033 | FastAPI — 对话管理 API + Audit Log 中间件 | api-layer 01 REQ-003~005/009 | AC-005~006 | T-024, T-005 | ✅ |
| T-034 | Streamlit — 登录页 + 聊天主界面 | frontend 00-overview | AC-001~006 | T-030, T-032 | ✅ |
| T-035 | Streamlit — 候选人卡片 + 侧边栏 + 上传 | frontend 00-overview | AC-003~006 | T-034 | ✅ |

---

## Phase 3：集成测试与端到端验证（M2~M4 末尾，左移执行）

| # | 任务 | 对应 Spec | 依赖 | 状态 |
|---|------|-----------|------|------|
| T-036 | **【M1 门控，已左移】** 集成测试 — Resume Parser → Store → Vector 全链路 | resume-parser + resume-store + vector-index | T-015, T-014 | ✅ |
| T-037 | 集成测试 — recruitment.search 端到端 | intent-router + recommendation-engine | T-027 | ✅ |
| T-038 | 集成测试 — recruitment.refine 多轮对话 | conversation-memory + recommendation-engine | T-028 | ⬜ |
| T-039 | 端到端测试 — 用户完整流程 | 全部模块 | T-035 | ⬜ |

---

## Phase 4：交付收尾

| # | 任务 | 依赖 | 状态 |
|---|------|------|------|
| T-040 | README.md + 部署文档 | T-039 | ✅ |
| T-041 | Docker Compose 生产配置 + 健康检查 | T-001, T-039 | ⬜ |
| T-042 | CHANGELOG.md + 版本标记 | T-041 | ✅ |

---

## 统计

| Phase | 任务数 | 预计时间 |
|-------|--------|----------|
| Phase 1（跨模块基础） | 8 | 2 天 |
| Phase 2 M1（Parser + M1门控） | 8（含 T-036 左移） | 3.5 天 |
| Phase 2 M2（检索推荐） | 8 | 3 天 |
| Phase 2 M3（多轮对话） | 6 | 3 天 |
| Phase 2 M4（API+前端） | 6 | 2 天 |
| Phase 3（测试联调） | 3（T-037~T-039，T-036 已左移至 M1） | 1 天 |
| Phase 4（交付） | 3 | 0.5 天 |
| **合计** | **42** | **~14.5 天** |

---

## 变更记录

### 2026-06-23: Spec-Task 对齐修复（Tier M 遗留）

**修复原因**: Phase 5 Review 发现 4 个 Task 文件与 Tier M 迭代后的 Spec 不一致，可能导致 Phase 7 执行时生成错误代码。

**修复范围**:

| 任务 | 问题 | 修复内容 | 严重度 |
|------|------|----------|--------|
| T-008 (	asks/phase-1/07-milvus.md) | Schema 仅有 mbedding (FLOAT_VECTOR)，无 Sparse 字段；维度示例为 1536 | 全面重写：Collection 改为 
esume_chunks；Schema 对齐 Spec 含 dense_vector (FLOAT_VECTOR 1024) + sparse_vector (SPARSE_FLOAT_VECTOR) + chunk_id/chunk_level/parent_chunk_id/section_type/content；索引改为 HNSW + SPARSE_INVERTED_INDEX | 🔴 P0 |
| T-019 (	asks/phase-2/11-rec-hybrid.md) | "分区检索"术语歧义（Milvus Partition vs 标量过滤）；无空查询防御 | 术语修正为"标量过滤（chunk_level）"；检索粒度改为 Small Chunk 级别；新增 AC-016（空查询守卫 EMPTY_QUERY）和 AC-017（标量过滤确认） | 🟡 P1 |
| Spec: specs/recommendation-engine/04-business-rules.md | RULE-001 uild_query_text() 无空查询守卫 | 新增 InvalidQueryError 抛出逻辑 + "空查询防御"规则段 | 🟡 P1 |

**未修改的文件**:
- T-015 (	asks/phase-2/07-vector-index.md): 已与 Spec 一致，无需修改
- 其余 38 个 Task 文件: 不涉及本次修复的 4 个问题

**遗留项**:
- 42 个任务文件中仍有部分未完全反映 Tier M 迭代（如 T-012 段落切分的 Chunk 三层输出、T-014 Resume Store 的 chunk_ids 回写等），但这些属于实现细节，Phase 7 执行时以 Spec 为准即可

### 2026-06-23: 新增文件 MD5 去重功能（Tier M 级增强）

**变更原因**: 企业场景中同一简历文件可能被多人多次上传，导致重复解析消耗 LLM Token、重复写入 Milvus 向量，浪费资源且污染推荐结果。

**变更范围**:

| 文件 | 修改类型 | 修改内容 |
|------|----------|----------|
| specs/resume-parser/02-data-model.md | 增量 | ParseStatus 增加 SKIPPED；ResumeMetadata 增加 file_md5 字段 |
| specs/resume-parser/03-api-contract.md | 增量 | ParseResult 增加 file_md5 字段；parse_resume 处理流程增加 MD5 计算 + find_by_md5 去重检查 |
| specs/resume-parser/04-business-rules.md | 增量 | 新增 RULE-010（文件 MD5 去重规则） |
| specs/resume-parser/05-edge-cases.md | 增量 | 新增 EC-015（文件内容重复上传） |
| specs/resume-parser/06-acceptance.md | 增量 | 新增 AC-021（MD5 去重命中）、AC-022（不同文件正常入库） |
| specs/resume-store/00-overview.md | 增量 | 新增 REQ-011（file_md5 去重）；Schema 增加 file_md5 字段；索引增加 idx_file_md5 UNIQUE sparse；API 增加 find_by_md5；RULE-007、EC-006、AC-008/AC-009 |
| 	asks/phase-2/06-resume-store-crud.md（T-014） | 增量 | 实现要求增加 find_by_md5 + file_md5 索引；AC 增加 AC-008~AC-010 |
| 	asks/phase-2/23-api-upload.md（T-031） | 增量 | 文件处理流程增加 MD5 去重步骤；AC 增加 AC-005/AC-006 |

**数据流**:
`
用户上传文件
    │
    ▼
读取文件内容 → 计算 file_md5 = md5(file_bytes)
    │
    ▼
resume-store.find_by_md5(file_md5)
    │
    ├─ 已存在 (status=active) → 返回 ParseResult(status=skipped, resume_id=existing)
    │                            不重新解析、不重新入库、不重新向量化
    │
    └─ 不存在 → 正常解析流程 → 入库时写入 file_md5 字段
`

**MongoDB 索引**: idx_file_md5 — UNIQUE sparse 索引（file_md5 为 None 时不参与唯一约束）

**新增错误码**: 无（skipped 通过 status 字段传递，非 HTTP 错误码）
### 2026-06-23: 引入 Redis + ARQ 异步任务队列（Tier L 级变更）

**变更原因**: 
1. 简历解析是 I/O 密集型长任务（OCR+LLM+Embedding，10~30s），同步处理阻塞 API 网关
2. 会话 TTL 需要精确的滑动窗口管理（MongoDB TTL 仅 60s 轮询）
3. 意图识别/推荐理由/Embedding 结果需要分布式缓存降低 LLM API 成本

**技术选型**: Redis 7 (Docker) + ARQ (原生 asyncio 任务队列)

**变更范围**:

| 文件 | 修改内容 |
|------|----------|
| docs/tech-decision.md | 决策项 11 改为 Redis+cachetools 双层缓存；决策项 13 改为 ARQ；新增决策项 15（异步任务队列选型）；依赖清单新增 redis/arq |
| 	asks/phase-1/00-container-env.md（T-001） | docker-compose 增加 redis:7-alpine 服务 |
| 	asks/phase-1/02-config.md（T-003） | config 增加 RedisSettings + QueueSettings |
| specs/conversation-memory/00-overview.md | 技术栈增加 Redis；做什么增加 Redis 会话 TTL；关键约束增加 Redis 优先 |
| specs/conversation-memory/02-data-model.md | 增加 Redis 存储结构和读写路径对照表 |
| specs/conversation-memory/04-business-rules.md | 新增 RULE-010（Redis 滑动窗口 TTL） |
| specs/vector-index/00-overview.md | 缓存升级为 L1 cachetools + L2 Redis 双层；RULE-002 升级 |
| specs/intent-router/00-overview.md | 技术栈增加 Redis；关键约束增加意图缓存规则 |
| specs/recommendation-engine/00-overview.md | 技术栈增加 Redis |
| specs/recommendation-engine/04-business-rules.md | 新增 RULE-012（推荐理由缓存） |
| 	asks/phase-2/23-api-upload.md（T-031） | 同步解析→异步队列：API 返回 202 + task_id，ARQ Worker 后台执行 |
| 	asks/phase-2/16-conv-crud.md（T-024） | TTL 从 MongoDB 迁移到 Redis EXPIRE 滑动窗口 |

**新增组件**:
- Redis 7 (Docker): 会话缓存 + 任务队列 + 分布式缓存
- ARQ Worker: 后台简历解析任务消费
- /api/v1/tasks/{task_id}: 任务进度查询端点

**降级策略**:
- Redis 不可用 → 会话降级到 MongoDB 直读；简历上传降级为同步解析；缓存失效但功能可用
### 2026-06-23: 推荐理由 Batch 合并 + Lazy Load（Tier M 级变更）

**变更原因**: 
1. 原 T-022 对 Top-5 候选人并行发起 5 次独立 LLM 调用，多用户并发时 RPM 暴涨触发 429 限流
2. 用户可能只看前 2 人，系统却强制生成 5 人理由，浪费 Token 账单
3. 缺少按需加载机制，前端无法延迟非必要 LLM 调用

**变更范围**:

| 文件 | 修改内容 |
|------|----------|
| specs/recommendation-engine/01-requirements.md | REQ-008 重写为 Batch+Lazy Load 策略；新增 REQ-015（Lazy Load 按需生成） |
| specs/recommendation-engine/04-business-rules.md | RULE-006 新增 Batch 合并约束段 |
| 	asks/phase-2/14-rec-reason.md（T-022） | 实现要求从并行N次→Batch合并；缓存→Redis；新增Lazy Load+RPM保护；AC新增AC-010~012 |
| 	asks/phase-2/27-frontend-cards.md（T-035） | 卡片展开→Lazy Load触发理由生成；默认折叠只展示Score Breakdown；AC新增AC-007~009 |

**核心策略**:
- **Batch 合并**: Top-N（≤5）理由打包单个 Prompt，一次 LLM 调用返回全部，RPM 降低 80%
- **Lazy Load**: 前端卡片默认折叠（只展示 Score Breakdown），展开时按需触发单个理由生成
- **Redis 缓存**: Batch/Single 结果均缓存（TTL 24h），其他 HR 搜同样条件直接命中
- **降级**: LLM 不可用→模板化理由（Score Breakdown 自动生成）
### 2026-06-23: 全局路径重命名 + Multi-Level Chunk + API 路由清理 + 去重逻辑修正（Tier M 级修复）

**变更原因**: Review 发现 5 个问题：P0 全局包目录名错位（T-002 定义 vs 后续任务实现不一致）、P1 Multi-Level Chunk 逻辑断层（T-012/T-015 未提及三层 Chunk）、P1 API 路由散落各处（T-014/T-024 含 routes.py、T-027~T-029 含端点定义但无输出文件）、P2 T-023 冗余精确去重（T-019 已按 resume_id 分组）。

**变更范围**:

| 问题 | 严重度 | 影响文件 | 修复内容 |
|------|--------|----------|----------|
| P0 全局路径错位 | 🔴 | 21 个任务文件 | src/parser/→src/resume_parser/，src/intent/→src/intent_router/，src/retrieval/→src/recommendation_engine/，src/conversation/→src/conversation_memory/，src/indexing/→src/vector_index/，tests/ 同步修正 |
| P0 Collection 名称不一致 | 🔴 | T-015 | resume_vectors→resume_chunks（对齐 T-008 Schema） |
| P1 T-012 Chunk 逻辑缺失 | 🟡 | T-012 | 新增 Multi-Level Chunk 构建（Small/Parent/Full 三层）+ chunk_builder.py 输出 + ChunkSchema 定义 + AC-NEW-01~04 |
| P1 T-015 Chunk 写入缺失 | 🟡 | T-015 | Segment→ChunkSchema 列表；写入字段增加 chunk_level/parent_chunk_id/section_type；输入改为 chunk_builder.py；Spec 一致性增加 Chunk 相关检查 |
| P1 API 路由散落 | 🟡 | T-014, T-024, T-027, T-028, T-029, T-030 | T-014/T-024 移除 routes.py 输出；T-027~T-029 明确"API 路由由 T-030 统一实现"；T-030 新增 search/refine/candidate 路由文件输出 |
| P2 T-023 冗余去重 | 🔵 | T-023 | 移除"同一 resume_id 精确去重"（T-019 已做），保留跨版本模糊去重 |

**验证结果**:
- 21 个任务文件旧路径清零 ✅
- T-012 Chunk 三层输出 + T-015 Chunk 写入字段对齐 Spec ✅
- API 路由统一归属 T-030 ✅
- T-023 去重逻辑与 T-019 无重叠 ✅
### 2026-06-23: 风险加固 — Spec 引用修正 + 增量扩展标注 + 自验证 AC + 关键路径标注

**变更原因**: SDD Final Review 发现 4 类 WARN 级风险，虽不阻断 Phase 7 但可能导致 Agent 执行时产生认知歧义或代码覆盖。

**变更范围**:

| 修复项 | 影响文件 | 修复内容 |
|--------|----------|----------|
| Spec 引用修正 | T-006, T-014, T-015 | 6 个指向不存在文件的引用改为指向 `00-overview.md` 具体章节 |
| 增量扩展标注 | T-012, T-032, T-035 | schemas.py/config.py/chat.py 输出增加 ⚠️ 增量扩展警告，禁止全量覆盖 |
| Pipeline 自验证 AC | T-027, T-028, T-029 | 新增 AC-SELF-01~03，确保 Pipeline 模块可独立测试（不依赖 T-030 API 入口） |
| 关键路径标注 | T-008, T-015, T-027 | 新增 🔴 关键路径节点警告，标注阻断的下游任务数量和影响范围 |
| 笔误修正 | T-034 | app.py 输出列表确认非重复（L21 为启动说明，非输出声明） |

**验证结果**:
- Spec 引用路径全部指向存在的文件 ✅
- 增量扩展语义显式标注 ✅
- Pipeline 模块具备独立自验证能力 ✅
- 关键路径节点已标注阻断影响 ✅

### 2026-06-23: 测试左移 — T-036 从 Phase 3 前置到 M1 验收门控

**变更原因**: 集成测试过度后置导致"重构雪崩"风险。RAG 系统最大痛点是数据流动时的格式不匹配（如 Parser 输出的 Chunk Schema 与 Milvus 接收的 Metadata 差一个字段）。若到第 4 周才发现底层 Chunk 切分粒度不合理，将导致 T-016~T-035 全部需要重构。

**变更策略**: 测试左移（Shift-Left Testing）

`
原方案：
  M1(T-001~T-015) → M2 → M3 → M4 → Phase3(T-036~T-039)

新方案：
  M1(T-001~T-015) → T-036(M1门控) → M2 → M3 → M4 → Phase3(T-037~T-039)
                        ↑
                   发现数据流问题立即修复，不影响后续
`

**变更范围**:

| 文件 | 修改内容 |
|------|----------|
| T-036 任务文件 | 标题增加【M1 验收门控】；新增左移策略说明；优先级升级为"M1 门控——不通过则阻断 M2/M3/M4" |
| task.md 里程碑 | M1 增加 T-036；M4 的 phase-3 明确为 T-037~T-039 |
| task.md 统计 | M1 任务数 7→8，工时 3天→3.5天；Phase 3 任务数 4→3 |

**收益**:
- Parser→Store→Vector 数据流问题在第 1 周末发现并修复
- 避免第 4 周大规模重构（修复成本降低 5~10 倍）
- M2/M3/M4 建立在已验证的地基上，开发信心更高
### 2026-06-23: Milvus Lite/Standalone 双环境版本锁死

**变更原因**: T-008 采用 Milvus Lite（单测）+ Milvus Standalone（开发/生产）双环境。但 BGE-M3 的 SPARSE_FLOAT_VECTOR + SPARSE_INVERTED_INDEX 在 pymilvus 不同版本间存在行为差异，可能导致本地单测全绿但 Docker 环境报索引创建失败。

**变更范围**:

| 文件 | 修改内容 |
|------|----------|
| T-002 | pymilvus 版本锁死 >= 2.4.6；新增版本验证 AC + Sparse Index 兼容性 AC |
| T-008 | Lite/Standalone 双环境一致性守卫说明；新增 AC-DUAL-01（双环境结果一致）+ AC-DUAL-02（版本对齐） |
| T-003 | .env 增加 MILVUS_VERSION_COMPAT 配置项 |

**版本矩阵**:
| 组件 | 最低版本 | 推荐版本 | 锁定原因 |
|------|----------|----------|----------|
| pymilvus | >= 2.4.6 | 2.4.x | SPARSE_FLOAT_VECTOR + SPARSE_INVERTED_INDEX 完整支持 |
| milvusdb/milvus | 2.4.x | 2.4.x | 与 pymilvus 大版本对齐 |
### 2026-06-23: 地址一致性修复 — 版本锁死 + API 端点统一 + 镜像版本锁定

**变更原因**: 全量文档地址审计发现 pymilvus 版本冲突（tech-decision >=2.5 vs T-002 >=2.4.6）、Milvus 镜像用 :latest 未锁定、API 端点设计矛盾（独立路由 vs 统一 /api/v1/chat）。

**变更范围**:

| 文件 | 修复内容 |
|------|----------|
| docs/tech-decision.md | pymilvus>=2.5 → pymilvus>=2.4.6（与 T-002/T-008 版本锁对齐） |
| T-001 | milvusdb/milvus:latest → milvusdb/milvus:v2.4.6（锁定版本） |
| T-008 | 移除重复的 AC-DUAL-02 |
| T-030 | 移除独立路由文件输出（search.py/refine.py/candidate.py），明确统一走 /api/v1/chat |
| T-027/T-028/T-029 | 端点引用改为"通过 Intent Router 分发到 Pipeline"，移除独立 API 端点声明 |
---

## 迭代记录：iter/m-security-hardening（2026-06-25）

**迭代类型**: Tier M（模块增强）
**分支**: `iter/m-security-hardening`
**触发**: CodeGraph 全项目 Review 发现 P0/P1 安全缺陷
**Spec 基线**: v1.1-security（specs/security-hardening/）
**预计工时**: 3 天

### 变更原因
CodeGraph 对 167 文件、2585 节点全项目 Review 后发现：
- RBAC 权限校验定义但未启用（垂直越权）
- 对话/简历接口未校验资源归属（IDOR 水平越权）
- PII 加密密钥复用 JWT 密钥且有弱默认值
- `.env` 含真实 API Key 且无 .gitignore
- CORS allow_origins=["*"] + credentials、debug 硬编码 True
- 文件上传无类型/大小校验
- 密码明文硬编码、无登录限流

### 任务列表

| # | 任务 | 对应 Spec | 优先级 | 依赖 | 状态 |
|---|------|-----------|--------|------|------|
| SEC-T01 | .gitignore + .env.example + 密钥吊销 | SEC-REQ-004 | P0 | 无 | ⬜ |
| SEC-T02 | 密钥分离（PII_ENCRYPTION_KEY）+ fail-fast | SEC-REQ-003 | P0 | SEC-T01 | ⬜ |
| SEC-T03 | RBAC 权限强制挂载 | SEC-REQ-001 | P0 | SEC-T02 | ⬜ |
| SEC-T04 | IDOR 资源归属校验 | SEC-REQ-002 | P0 | SEC-T03 | ⬜ |
| SEC-T05 | CORS 白名单 + debug 配置化 + 异常最小化 | SEC-REQ-006 | P0 | SEC-T04 | ⬜ |
| SEC-T06 | 文件上传安全校验 | SEC-REQ-007 | P1 | SEC-T05 | ⬜ |
| SEC-T07 | 密码哈希 + 用户表迁移 | SEC-REQ-005 | P1 | SEC-T06 | ⬜ |
| SEC-T08 | 登录限流 | SEC-REQ-008 | P1 | SEC-T07 | ⬜ |
| SEC-T09 | 安全测试用例 + 回归 | AC-SEC-001~008 | P0 | T01~T08 | ⬜ |
| SEC-T10 | 集成验收 + spec 冻结 | 06-acceptance.md | P0 | SEC-T09 | ⬜ |

详细任务文件见 `tasks/iter-m-security/`。
