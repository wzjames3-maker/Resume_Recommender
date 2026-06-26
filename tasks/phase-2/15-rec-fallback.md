# T-023: 降级策略 + 去重

## 基本信息
- 对应 Spec: specs/recommendation-engine/01-requirements.md REQ-010~REQ-012
- 对应 AC: AC-010~AC-012, AC-014
- 依赖: T-022
- 预计工时: 1.5 天

## 输入
- `specs/recommendation-engine/01-requirements.md` — 降级与去重需求
- `specs/recommendation-engine/04-business-rules.md` — 业务规则
- `src/recommendation_engine/reason_generator.py` — 推荐理由（T-022 产出）
- `src/recommendation_engine/score_breakdown.py` — Score Breakdown（T-022 产出）

## 输出
- `src/recommendation_engine/degradation_handler.py` — 降级策略模块
- `src/recommendation_engine/deduplicator.py` — 去重模块
- `tests/recommendation_engine/test_degradation_handler.py` — 降级策略测试
- `tests/recommendation_engine/test_deduplicator.py` — 去重测试

## 实现要求
1. 降级策略四级流水线：
   - L1: 完整流程（Hybrid + Filter + Rerank + Reason）
   - L2: 跳过 Rerank（Hybrid + Filter + 原始排序 + Reason）
   - L3: 跳过 Filter（Hybrid + 原始排序，无 Reason）
   - L4: 仅文本搜索（关键词匹配兜底）
2. 降级触发条件：L1 超时（3s）→ L2，L2 超时（2s）→ L3，L3 失败 → L4
3. 每级降级记录降级日志，包含 `degradation_level`、`trigger_reason`、`latency`
4. 去重策略（T-019 已按 resume_id 分组去重，本模块专注跨版本模糊去重）：
   - **模糊去重（核心）**：基于姓名 + 手机号 hash 判断同一人不同版本的简历
5. 去重后保留最新版本简历，旧版本标记为 `is_duplicate=True`（仅针对模糊去重的跨版本简历）
6. 去重结果记录 `dedup_log`：原始数量、去重后数量、去重原因
7. 关键设计决策：降级是逐级递减而非直接失败，保证在任何异常情况下都有结果返回
8. 禁止事项：禁止在 L4 降级时返回空结果（关键词匹配必须兜底）；禁止去重时删除原始数据（只标记）

## 验收检查点

### 前置确认
- [ ] T-022（推荐理由）已完成
- [ ] 容器环境已启动

### AC 验收
- [ ] AC-010: Rerank 服务不可用时自动降级到 L2，返回结果正常（无 Rerank 分数），降级日志记录完整
- [ ] AC-011: 同一候选人多份简历去重后只保留一份，保留最新版本，`is_duplicate` 标记正确
- [ ] AC-012: 去重统计信息正确：原始数量、去重后数量、去重原因

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] 降级超时阈值可配置
- [ ] 去重规则可扩展（支持新增去重维度）
- [ ] 降级日志结构化，便于监控
- [ ] 类型标注完整


- [ ] AC-014: 请求 count=10 但实际匹配仅 3 人时，返回 3 人 + 提示"仅找到 N 位符合条件的候选人"

### Spec 一致性
- [ ] 降级级别和触发条件与 REQ-010 一致
- [ ] 去重策略与 REQ-011 一致
- [ ] 降级日志字段与 REQ-012 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
