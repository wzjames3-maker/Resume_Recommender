# T-020: Metadata Filter + Soft Match

## 基本信息
- 对应 Spec: specs/recommendation-engine/01-requirements.md REQ-004, REQ-005
- 对应 AC: AC-004, AC-005, AC-013
- 依赖: T-019
- 预计工时: 1.5 天

## 输入
- `specs/recommendation-engine/01-requirements.md` — 过滤与软匹配需求
- `specs/recommendation-engine/04-business-rules.md` — 过滤规则
- `src/recommendation_engine/hybrid_retriever.py` — 混合检索模块（T-019 产出）

## 输出
- `src/recommendation_engine/metadata_filter.py` — 元数据过滤器
- `src/recommendation_engine/soft_match.py` — 软匹配模块
- `tests/recommendation_engine/test_metadata_filter.py` — 过滤器测试
- `tests/recommendation_engine/test_soft_match.py` — 软匹配测试

## 实现要求
1. 硬过滤（Must）：从 Slot 中提取的硬性条件必须满足，不满足的直接剔除
   - 工作地点匹配（`location` 精确或城市级匹配）
   - 学历最低要求（`education_min`）
   - 工作年限范围（`experience_min` / `experience_max`）
2. 软匹配（Should）：不满足则降分但不剔除
   - 技能匹配度（`skills` 交集 / 并集比值）
   - 行业匹配度（`industry` 相似度）
   - 薪资范围匹配（`salary_range` 重叠度）
3. 软匹配使用可配置权重，默认：技能 0.4 / 行业 0.3 / 薪资 0.3
4. 过滤后的结果添加 `filter_scores: dict`，记录每个维度的得分
5. 空结果时触发 Soft Fallback：逐步放宽硬过滤条件，优先放宽地点 → 学历 → 年限
6. 关键设计决策：硬过滤和软匹配分离，硬过滤保证结果质量，软匹配优化排序
7. 禁止事项：禁止在过滤层修改检索分数（只添加 filter_scores，不覆盖原始 score）

## 验收检查点

### 前置确认
- [ ] T-019（混合检索）已完成
- [ ] 容器环境已启动
- [ ] 测试数据中包含不同地点/学历/技能的简历

### AC 验收
- [ ] AC-004: 硬过滤正确执行，不符合地点/学历/年限要求的候选人被剔除
- [ ] AC-005: 软匹配正确评分，技能匹配度高的候选人排序靠前，`filter_scores` 字段完整

### 代码质量
- [ ] lint pass（ruff + mymy）
- [ ] 硬过滤条件可配置
- [ ] 软匹配权重可配置
- [ ] Soft Fallback 逻辑有完整测试
- [ ] 类型标注完整


- [ ] AC-013: 所有候选人均不满足硬约束时，自动放宽约束重试（如去掉最低经验要求），返回放宽后的结果 + 提示

### Spec 一致性
- [ ] 硬过滤条件与 REQ-004 一致
- [ ] 软匹配维度和权重与 REQ-005 一致
- [ ] Soft Fallback 策略与 `04-business-rules.md` 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
