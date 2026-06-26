# T-027: recruitment.search 端到端

## 基本信息
- 对应 Spec: specs/conversation-memory/01-requirements.md（搜索流程集成）
- 对应 AC: 端到端集成验证
- 依赖: T-018, T-023
- 预计工时: 2 天
- **🔴 关键路径节点**: 本任务阻断 T-028→T-030→T-034→T-035→T-039→T-042（共 8 个下游任务）。搜索 Pipeline 是所有 API 端点的基础。

## 输入
- `src/intent_router/classifier.py` — 意图分类器（T-016 产出）
- `src/intent_router/slot_extractor.py` — Slot 提取（T-017 产出）
- `src/intent_router/router.py` — 意图路由（T-017 产出）
- `src/intent_router/fallback_handler.py` — Fallback（T-018 产出）
- `src/recommendation_engine/hybrid_retriever.py` — 混合检索（T-019 产出）
- `src/recommendation_engine/metadata_filter.py` — 过滤（T-020 产出）
- `src/recommendation_engine/reranker.py` — Rerank（T-021 产出）
- `src/recommendation_engine/reason_generator.py` — 推荐理由（T-022 产出）
- `src/recommendation_engine/degradation_handler.py` — 降级（T-023 产出）
- `src/conversation_memory/session_manager.py` — 会话管理（T-024 产出）
- `src/conversation_memory/slot_manager.py` — Slot 合并（T-025 产出）

## 输出
- `src/pipeline/search_pipeline.py` — 搜索端到端流水线
- `tests/e2e/test_search_pipeline.py` — 搜索端到端测试
- `tests/e2e/conftest.py` — E2E 测试配置

## 实现要求
1. 完整搜索流程串联：用户输入 → 意图识别 → Slot 提取 → Slot 合并 → 范围决策 → 混合检索 → 过滤 → Rerank → 推荐理由 → 格式化输出
2. 搜索业务逻辑：接收 query + session_id（可选），返回推荐候选人列表。**API 入口由 T-030 统一实现（POST /api/v1/chat，Intent Router 自动分发到 search_pipeline）**，本任务只输出 Pipeline 模块
3. 无 `session_id` 时自动创建新会话，有 `session_id` 时追加到已有会话
4. 流水线每个阶段有独立的超时控制，整体超时 10s
5. 结果格式化：统一输出 `SearchResponse`（`candidates`、`total`、`session_id`、`degradation_level`、`latency_ms`）
6. 端到端测试覆盖：正常路径、Fallback 路径、降级路径、空结果路径
7. 关键设计决策：Pipeline 使用编排模式而非链式调用，便于后续添加并行步骤和条件分支
8. 禁止事项：禁止在 Pipeline 中直接调用数据库（必须通过各模块的接口）；禁止跳过意图识别直接执行检索

## 验收检查点

### 前置确认
- [ ] T-018（Fallback）已完成
- [ ] T-023（降级 + 去重）已完成
- [ ] 容器环境已启动
- [ ] 所有依赖模块的单元测试均通过

### AC 验收
- [ ] 端到端：输入"找3年Java经验在北京的候选人"，返回推荐候选人列表，包含推荐理由
- [ ] Fallback：输入模糊查询，返回引导性回复
- [ ] 降级：Rerank 服务不可用时，自动降级返回结果
- [ ] 空结果：查询条件过于严格时，返回 Soft Fallback 结果或提示放宽条件
- [ ] **AC-SELF-01**: Pipeline 模块可通过 `python -m pytest tests/e2e/test_search_pipeline.py` 独立运行，无需启动 FastAPI 服务
- [ ] **AC-SELF-02**: 使用 mock 的 Intent Router + Milvus Client 验证 Pipeline 编排逻辑，不依赖真实外部服务
- [ ] **AC-SELF-03**: Pipeline 直接调用返回 `SearchResponse` 对象，可通过 assert 验证结构完整性（candidates/session_id/latency_ms）

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] Pipeline 各阶段超时可配置
- [ ] 整体超时有降级处理
- [ ] 日志覆盖全流程关键节点
- [ ] 类型标注完整

### Spec 一致性
- [ ] 搜索流程与各模块 spec 中定义的完整流程一致
- [ ] `SearchResponse` 结构与 API 契约一致
- [ ] 会话管理行为与 conversation-memory spec 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
