# T-028: recruitment.refine 端到端

## 基本信息
- 对应 Spec: specs/conversation-memory/01-requirements.md（Refine 流程集成）
- 对应 AC: 端到端集成验证
- 依赖: T-026, T-027
- 预计工时: 2 天

## 输入
- `src/pipeline/search_pipeline.py` — 搜索流水线（T-027 产出）
- `src/intent_router/router.py` — 意图路由（T-017 产出）
- `src/conversation_memory/slot_manager.py` — Slot 合并（T-025 产出）
- `src/conversation_memory/scope_decider.py` — 范围决策（T-026 产出）
- `src/conversation_memory/candidate_ref.py` — 候选人引用（T-026 产出）

## 输出
- `src/pipeline/refine_pipeline.py` — Refine 端到端流水线
- `tests/e2e/test_refine_pipeline.py` — Refine 端到端测试

## 实现要求
1. Refine 流程：用户在已有搜索结果基础上修改条件重新搜索
2. 完整流程：用户输入 → 意图识别（`recruitment.refine`）→ Slot 提取 → 增量 Slot 合并 → 检索范围决策 → 重新检索 → 结果对比 → 格式化输出
3. 结果对比：返回新增候选人、移除候选人、排序变化，标记 `is_new=True` / `is_removed=True`
4. Refine 前后的 Slot 变化可视化：展示哪些条件被修改了
5. 支持连续 Refine：多次 Refine 的 Slot 持续累加
6. Refine 超时降级：复用 T-023 的降级策略
7. Refine 业务逻辑：接收 session_id（必填）+ query，返回 Refine 结果。**API 入口由 T-030 统一实现（POST /api/v1/chat，Intent Router 自动分发到 refine_pipeline）**，本任务只输出 Pipeline 模块
8. 关键设计决策：Refine 不是创建新搜索，而是在已有 Slot 基础上增量更新后重新检索
9. 禁止事项：禁止 Refine 时丢失历史 Slot（必须增量合并）；禁止忽略结果对比直接返回全量结果

## 验收检查点

### 前置确认
- [ ] T-026（范围决策 + 候选人引用）已完成
- [ ] T-027（搜索端到端）已完成
- [ ] 容器环境已启动

### AC 验收
- [ ] 端到端：先搜索"Java开发"，再 Refine"3年经验的"，Slot 正确合并，结果更新
- [ ] 结果对比：新增和移除的候选人正确标记
- [ ] Slot 变化可视化：正确展示修改的字段
- [ ] 连续 Refine：三次连续 Refine 后 Slot 累积正确
- [ ] **AC-SELF-01**: Pipeline 模块可通过 `python -m pytest tests/e2e/test_refine_pipeline.py` 独立运行，无需启动 FastAPI 服务
- [ ] **AC-SELF-02**: Refine 前后的 Slot diff 可通过 assert 直接验证，不依赖网络请求

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] 结果对比逻辑有单元测试
- [ ] 连续 Refine 场景有端到端测试
- [ ] 降级逻辑正确复用
- [ ] 类型标注完整

### Spec 一致性
- [ ] Refine 流程与 conversation-memory spec 一致
- [ ] Slot 增量合并与 REQ-004~REQ-006 一致
- [ ] API 接口与 `03-api-contract.md` 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
