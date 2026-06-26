# T-029: candidate.lookup + compare

## 基本信息
- 对应 Spec: specs/intent-router/01-requirements.md（candidate.lookup / candidate.compare 意图）
- 对应 AC: 端到端集成验证
- 依赖: T-026, T-014
- 预计工时: 2 天

## 输入
- `src/intent_router/router.py` — 意图路由（T-017 产出）
- `src/conversation_memory/candidate_ref.py` — 候选人引用（T-026 产出）
- `src/resume_store/repository.py` — Resume 数据仓库（T-014 产出）
- `src/resume_store/desensitizer.py` — 数据脱敏（T-014 产出）
- `src/resume_parser/pii_handler.py` — PII 处理（T-013 产出）

## 输出
- `src/pipeline/lookup_pipeline.py` — 候选人详情查询流水线
- `src/pipeline/compare_pipeline.py` — 候选人对比流水线
- `tests/e2e/test_lookup_pipeline.py` — Lookup 端到端测试
- `tests/e2e/test_compare_pipeline.py` — Compare 端到端测试

## 实现要求
1. **candidate.lookup 流程**：
   - 用户输入 → 意图识别（`candidate.lookup`）→ 引用解析 → 查询 Resume 详情 → PII 按需解密 → 脱敏展示 → 格式化输出
   - 支持按姓名、序号、`resume_id` 三种方式查询
   - 详情展示包含：基本信息、教育经历、工作经历、项目经历、技能列表、简历解析状态
2. **candidate.compare 流程**：
   - 用户输入 → 意图识别（`candidate.compare`）→ 引用解析（多个候选人）→ 批量查询 → 并排对比 → 格式化输出
   - 对比维度：工作年限、技能匹配度、教育背景、项目经验
   - 对比结果以表格形式展示，高亮差异项
3. Lookup 和 Compare 的业务逻辑由 Pipeline 模块实现。**API 入口由 T-030 统一实现（POST /api/v1/chat，Intent Router 自动分发到 lookup/compare_pipeline）**，本任务只输出 Pipeline 模块
   - Lookup：通过 Intent Router 分发到 lookup_pipeline（内部调用，非独立 API 端点）
   - Compare：通过 Intent Router 分发到 compare_pipeline（内部调用，非独立 API 端点）
4. PII 审计：Lookup 和 Compare 均记录 `pii_access_log`
5. 关键设计决策：Lookup 和 Compare 共享引用解析和查询逻辑，通过不同的 Pipeline 组装
6. 禁止事项：禁止 Lookup 时返回完整 PII 明文（必须脱敏 + 审计）；禁止 Compare 时忽略候选人不存在的情况

## 验收检查点

### 前置确认
- [ ] T-026（范围决策 + 候选人引用）已完成
- [ ] T-014（Resume Store CRUD）已完成
- [ ] 容器环境已启动
- [ ] 测试数据中有多个候选人

### AC 验收
- [ ] Lookup 端到端：输入"张三的简历详情"，返回完整的候选人信息（脱敏）
- [ ] Lookup 引用：输入"第2个候选人"，正确解析为对应 `resume_id` 并返回详情
- [ ] Compare 端到端：输入"对比张三和李四"，返回并排对比结果
- [ ] Compare 维度：工作年限、技能、教育背景、项目经验均有对比展示
- [ ] PII 审计：Lookup 和 Compare 操作均记录到 `pii_access_log`
- [ ] 异常处理：候选人不存在时返回友好提示
- [ ] **AC-SELF-01**: Lookup 和 Compare Pipeline 可通过 `python -m pytest tests/e2e/` 独立运行，无需启动 FastAPI 服务
- [ ] **AC-SELF-02**: 使用 mock 的 Resume Store 验证引用解析→查询→脱敏全流程
- [ ] **AC-SELF-03**: PII 审计日志通过 assert 验证记录存在，不依赖外部日志系统

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] Lookup 和 Compare 共享查询逻辑，无重复代码
- [ ] PII 解密 + 脱敏流程完整
- [ ] 审计日志记录正确
- [ ] 类型标注完整

### Spec 一致性
- [ ] Lookup 输出结构与 intent-router spec 中 `candidate.lookup` 定义一致
- [ ] Compare 对比维度与 intent-router spec 中 `candidate.compare` 定义一致
- [ ] 脱敏规则与 resume-store spec 一致
- [ ] PII 审计规则与 RULE-007 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
