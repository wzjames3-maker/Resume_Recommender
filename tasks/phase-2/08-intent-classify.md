# T-016: Intent 识别（LLM Function Calling）

## 基本信息
- 对应 Spec: specs/intent-router/01-requirements.md REQ-001, REQ-002
- 对应 AC: AC-001~AC-004, AC-011, AC-014
- 依赖: T-002, T-003
- 预计工时: 2 天

## 输入
- `specs/intent-router/01-requirements.md` — 意图识别需求
- `specs/intent-router/02-data-model.md` — Intent / Slot 数据模型
- `src/common/config.py` — 全局配置（T-002 产出）
- `src/common/exceptions.py` — 自定义异常（T-003 产出）

## 输出
- `src/intent_router/classifier.py` — 意图分类器
- `src/intent_router/schemas.py` — Intent / Slot Pydantic Schema
- `tests/intent_router/test_classifier.py` — 意图分类器测试

## 实现要求
1. 使用 LLM Function Calling 实现意图识别，定义意图枚举：`recruitment.search`、`recruitment.refine`、`candidate.lookup`、`candidate.compare`、`general.chat`、`out_of_scope`
2. 每个意图携带 `confidence: float`，低于阈值（默认 0.7）触发 Fallback
3. 使用 Function Calling 模式强制 LLM 输出结构化 `IntentResult`（含 `intent`、`confidence`、`raw_query`）
4. 支持上下文感知：传入最近 3 轮对话历史，提升多轮场景下的意图识别准确率
5. Prompt 模板外置于 `src/intent_router/prompts/` 目录，支持 A/B 测试不同 prompt
6. 意图分类器需有缓存：相同 query + 相同 context hash 的请求返回缓存结果（TTL 5min）
7. 关键设计决策：使用 Function Calling 而非文本分类模型，因为意图集可扩展且需要结构化输出
8. 禁止事项：禁止在分类器中直接执行业务逻辑（分类器只输出意图，不执行动作）；禁止忽略 confidence score

## 验收检查点

### 前置确认
- [ ] T-002（全局配置）已完成
- [ ] T-003（异常体系）已完成
- [ ] 容器环境已启动
- [ ] LLM API 可访问

### AC 验收
- [ ] AC-001: 输入"帮我找3年经验的Java开发"，正确识别为 `recruitment.search`，confidence ≥ 0.8
- [ ] AC-002: 输入"把这些结果按薪资排序"，正确识别为 `recruitment.refine`
- [ ] AC-003: 输入"张三的简历详情"，正确识别为 `candidate.lookup`
- [ ] AC-004: 输入无关问题"今天天气怎么样"，正确识别为 `out_of_scope`

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] 意图枚举可扩展（新增意图只需修改配置）
- [ ] 缓存逻辑正确，TTL 可配置
- [ ] Prompt 模板外置，无硬编码
- [ ] 类型标注完整


- [ ] AC-011: 意图模糊时（如"找人"无法区分 search/lookup），返回 disambiguation 提示让用户选择
- [ ] AC-014: LLM 返回非法 Intent 值时，自动降级到 keyword 规则匹配 + 记录告警日志

### Spec 一致性
- [ ] 意图枚举与 `specs/intent-router/02-data-model.md` 一致
- [ ] IntentResult 结构与 spec 定义一致
- [ ] 置信度阈值与 REQ-002 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
