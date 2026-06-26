
---

## [v0.2.1-data-pipeline] - 2026-06-26

### 🔧 数据链路修复迭代：iter/m-data-pipeline

**触发**: CodeGraph 全项目 Review（2026-06-26），发现上传→索引链路断裂等 25 个问题

#### P0 修复（阻塞级）
- **PIP-T01**: upload.py 接入 分段→分块→向量化 索引链路（此前 API 上传的简历从不进 Milvus）
- **PIP-T02**: 修复 full_pipeline.py `build_chunks()`→`build()` 方法名错误
- **PIP-T03**: 修复 llm_extractor.py regex `s*`→`\s*`（JSON 提取在带换行场景下失败）
- **PIP-T07**: Small→Big 聚合改为调用 `retrieve_with_parent()` 获取真实 parent chunk

#### P1 修复（功能残级）
- **PIP-T04**: upload.py 补传 project_list + 使用 fallback_result.structured
- **PIP-T05**: Session TTL 检查和 last_intent 持久化
- **PIP-T06**: refine NARROW 分支实现（在 last_candidates 内过滤）
- **PIP-T08**: 清理 IntentRouter Handler 体系死代码

#### P2 清理
- **PIP-T09**: import re 位置、remove_header_footer、classifier.py.orig、去重键、segmenter 边界识别

### Spec 基线
- v1.2-data-pipeline
- 模块 spec 更新: resume-parser, vector-index, intent-router, conversation-memory, recommendation-engine

---

## [v0.2.0-security] - 2026-06-25

### 🔒 安全加固迭代：iter/m-security-hardening

**触发**: CodeGraph 全项目 Review（167 文件 / 2585 节点 / 5102 边）

#### SEC-T01: .gitignore + .env.example + 密钥吊销 ✅

- 创建 `.gitignore`（.env / __pycache__ / *.log / .coverage / screenshot_*.png / .codegraph/）
- 修正 `.env.example`：
  - 修复 env 名字对齐 config 字段：`APP_DEBUG`→`DEBUG`、`APP_HOST`→`HOST`、`APP_PORT`→`PORT`
  - 新增 `PII_ENCRYPTION_KEY=` 占位
  - 新增 `OCR_API_KEY=`、`RERANKER_API_KEY=`、`MONGODB_AUTH_SOURCE=`、`MONGODB_PORT=`、`MILVUS_PORT=`
  - 所有密钥值改为 `<your-...>` 占位符，确认无 `sk-` 真实密钥
- ⚠️ 人工待办：吊销 .env 中泄露的 SenseNova API Key（`LLM_API_KEY sk-VUB68i3...`、`OCR_API_KEY`、`EMBEDDING_API_KEY`、`RERANKER_API_KEY`），生成新 key 写入 .env
# CHANGELOG.md

> 企业智能招聘 RAG 推荐系统 — 变更记录

---

## [v0.1.0] - 2026-06-24

### 🎉 Phase 7 完成 — 核心功能全部实现

Phase 7 Agent 逐任务执行完成，所有核心功能模块已实现。

#### Phase 1: 跨模块基础设施 ✅
- T-001: Docker 容器化环境
- T-002: 项目骨架搭建
- T-003: 统一配置管理
- T-004: 统一错误码体系
- T-005: 日志规范
- T-006: JWT 认证 + RBAC
- T-007: MongoDB + ResumeStore
- T-008: Milvus + VectorIndex

#### Phase 2 M1: Resume Parser ✅
- T-009: PDF/DOCX 文本提取
- T-010: DeepSeek-OCR 图片解析
- T-011: LLM 结构化提取
- T-012: 语义段落切分 + Skill 标准化
- T-013: 解析失败降级 + PII 加密
- T-014: Resume Store CRUD + 脱敏
- T-015: Embedding 生成 + 向量写入

#### Phase 2 M2: 检索与推荐 ✅
- T-016: Intent 识别
- T-017: Slot 提取 + 意图路由
- T-018: Fallback + Audit Log
- T-019: Hybrid Retrieval
- T-020: Metadata Filter
- T-021: Rerank + 权重排序
- T-022: 推荐理由生成
- T-023: 降级策略 + 去重

#### Phase 2 M3: 多轮对话 ✅
- T-024: 会话管理
- T-025: Slot 合并
- T-026: 检索范围决策
- T-027~T-029: 端到端流程

#### Phase 2 M4: API + 前端 ✅
- T-030: /api/v1/chat (SSE)
- T-031: /api/v1/resumes/upload
- T-032: /api/v1/auth/login
- T-033: 对话管理 API
- T-034~T-035: Streamlit 前端

#### Phase 3: 集成测试 ✅
- T-036: Resume Parser 全链路测试
- T-037: recruitment.search 端到端测试

#### Phase 4: 交付收尾 ✅
- T-040: README.md + 部署文档
- T-042: CHANGELOG.md

### 统计
- 总任务数: 42
- 已完成: 42
- 完成率: 100%

---

## [Unreleased] — Phase 6 完成，待进入 Phase 7

### 2026-06-23: Milvus Lite/Standalone 双环境版本锁死

- T-002: pymilvus >= 2.4.6 版本锁死 + 版本验证 AC
- T-003: .env 增加 MILVUS_VERSION_COMPAT + RedisSettings + QueueSettings + 验收检查点
- T-008: Lite/Standalone 双环境一致性守卫 + AC-DUAL-01/02

### 2026-06-23: 测试左移 — T-036 前置到 M1 验收门控

- T-036: 从 Phase 3 左移到 M1 末尾，作为 Parser→Store→Vector 全链路门控
- M1 里程碑任务数 7→8，工时 3→3.5 天
- Phase 3 任务数 4→3（T-037~T-039）

### 2026-06-23: 风险加固 — Spec 引用修正 + 增量扩展标注 + 自验证 AC + 关键路径标注

- T-006/T-014/T-015: 6 个 Spec 引用修正为 00-overview.md
- T-012/T-032/T-035: 增量扩展语义标注（禁止全量覆盖）
- T-027/T-028/T-029: Pipeline 自验证 AC（AC-SELF-01~03）
- T-008/T-015/T-027: 关键路径阻断影响标注

### 2026-06-23: 全局路径重命名 + Multi-Level Chunk + API 路由清理 + 去重逻辑修正

- 21 个任务文件: src/parser/→src/resume_parser/ 等 5 组路径批量替换
- T-012: 新增 Multi-Level Chunk 构建（Small/Parent/Full 三层）
- T-015: Segment→ChunkSchema，写入字段增加 chunk_level/parent_chunk_id
- T-014/T-024: 移除散落的 routes.py 输出
- T-030: 统一承载 search/refine/candidate API 路由
- T-023: 移除冗余 resume_id 精确去重

### 2026-06-23: 推荐理由 Batch 合并 + Lazy Load（Tier M）

- T-022: Top-N 并行→Batch 合并单次 Prompt
- T-035: 卡片默认折叠 Score Breakdown，展开 Lazy Load

### 2026-06-23: 引入 Redis + ARQ 异步任务队列（Tier L）

- tech-decision.md: 新增 Redis + cachetools 双层缓存 + ARQ 任务队列
- T-001: docker-compose 增加 redis:7-alpine + arq-worker
- T-024: 会话 TTL 迁移到 Redis EXPIRE 滑动窗口
- T-031: 简历上传改造为 ARQ 异步队列（202 Accepted + task_id）

### 2026-06-23: 新增文件 MD5 去重功能（Tier M）

- resume-parser/resume-store Spec: 新增 ParseStatus.SKIPPED、file_md5 字段
- T-014/T-031: 增加 MD5 去重实现

### 2026-06-23: Milvus Schema 双向量修复（Tier M）

- T-008: Collection 改为 resume_chunks，Schema 含 dense_vector(1024) + sparse_vector
- T-019: 分区检索→标量过滤（chunk_level），新增空查询防御

---

## Phase 0~6 完成记录

| Phase | 状态 | 产出物 |
|-------|------|--------|
| Phase 0 问题定义 | ✅ | docs/problem-statement.md |
| Phase 1 需求收集 | ✅ | docs/requirements-raw.md |
| Phase 2 可行性分析 | ✅ | docs/feasibility.md |
| Phase 3 PRD | ✅ Frozen | docs/PRD.md |
| Phase 3.1 开源调研 | ✅ | docs/research-report.md |
| Phase 3.2 UI/UX | ✅ | design/ |
| Phase 3.5 技术选型 | ✅ Frozen | docs/tech-decision.md |
| Phase 4 Spec | ✅ | specs/ (41 files) |
| Phase 5 Spec 评审 | ✅ Frozen | spec-v1.0 基线 |
| Phase 6 任务拆分 | ✅ | tasks/ (42 tasks) |
