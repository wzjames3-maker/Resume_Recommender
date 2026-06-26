# T-018: Fallback + Audit Log

## 基本信息
- 对应 Spec: specs/intent-router/01-requirements.md REQ-005, REQ-006
- 对应 AC: AC-008, AC-009, AC-013, AC-015
- 依赖: T-016, T-005
- 预计工时: 1.5 天

## 输入
- `specs/intent-router/01-requirements.md` — Fallback 与审计日志需求
- `specs/intent-router/04-business-rules.md` — 业务规则
- `src/intent_router/classifier.py` — 意图分类器（T-016 产出）
- `src/common/logger.py` — 结构化日志（T-005 产出）

## 输出
- `src/intent_router/fallback_handler.py` — Fallback 处理模块
- `src/intent_router/audit_logger.py` — 意图审计日志模块
- `tests/intent_router/test_fallback_handler.py` — Fallback 测试
- `tests/intent_router/test_audit_logger.py` — 审计日志测试

## 实现要求
1. Fallback 触发条件：confidence < 0.7 / LLM 调用失败 / 返回未知意图类型
2. Fallback 响应策略：
   - confidence 在 0.4~0.7 之间 → 返回"您是想搜索候选人吗？"引导性回复 + 候选意图列表
   - confidence < 0.4 或 LLM 失败 → 返回通用兜底回复"抱歉，我无法理解您的需求"
3. `out_of_scope` 意图直接返回礼貌拒绝回复，不做重试
4. 审计日志记录每次意图识别的完整链路：`query`、`detected_intent`、`confidence`、`slots`、`handler`、`response_type`、`latency_ms`、`fallback_triggered`
5. 审计日志写入 `intent_audit_log` 表，支持按时间范围和意图类型查询
6. Fallback 触发时额外记录 `fallback_reason` 字段
7. 关键设计决策：Fallback 不是静默失败，而是积极引导用户补充信息
8. 禁止事项：禁止在 Fallback 中猜测意图并静默执行；禁止审计日志包含用户查询的 PII 明文（需脱敏）

## 验收检查点

### 前置确认
- [ ] T-016（意图识别）已完成
- [ ] T-005（结构化日志）已完成
- [ ] 容器环境已启动

### AC 验收
- [ ] AC-008: 意图不明确时返回引导性回复，包含候选项列表
- [ ] AC-009: 每次意图识别均有审计日志，字段完整（query脱敏、intent、confidence、latency_ms、fallback_triggered）

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] Fallback 策略可配置（阈值和回复模板）
- [ ] 审计日志异步写入，不阻塞主流程
- [ ] 日志中 query 字段已脱敏
- [ ] 类型标注完整


- [ ] AC-013: 无上文（新会话）收到 refine 类输入时，返回"请先描述您的招聘需求"引导提示
- [ ] AC-015: LLM 整体不可用时，降级到关键词规则引擎（基于正则匹配 intent + slot），保证系统可用

### Spec 一致性
- [ ] Fallback 触发条件与 REQ-005 一致
- [ ] 审计日志字段与 REQ-006 一致
- [ ] 回复模板与 spec 中定义的文案一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
