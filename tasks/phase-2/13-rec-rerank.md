# T-021: Rerank + 权重排序

## 基本信息
- 对应 Spec: specs/recommendation-engine/01-requirements.md REQ-006, REQ-007
- 对应 AC: AC-006, AC-007
- 依赖: T-020
- 预计工时: 2 天

## 输入
- `specs/recommendation-engine/01-requirements.md` — Rerank 与权重排序需求
- `specs/recommendation-engine/02-data-model.md` — 排序结果数据模型
- `src/recommendation_engine/metadata_filter.py` — 过滤器（T-020 产出）
- `src/recommendation_engine/soft_match.py` — 软匹配（T-020 产出）

## 输出
- `src/recommendation_engine/reranker.py` — Rerank 模块
- `src/recommendation_engine/weight_scorer.py` — 权重排序模块
- `src/recommendation_engine/weight_config.py` — 权重配置定义
- `tests/recommendation_engine/test_reranker.py` — Rerank 测试
- `tests/recommendation_engine/test_weight_scorer.py` — 权重排序测试

## 实现要求
1. 使用 BGE Reranker（bge-reranker-v2-m3）对检索结果进行精排，输入 (query, document) 对，输出相关性分数
2. Rerank 对象为 Top-50（从过滤后的结果中取前 50 条），减少计算量
3. 权重排序：将多个分数加权求和为最终分数
   - `final_score = w1 * retrieval_score + w2 * rerank_score + w3 * filter_score + w4 * freshness`
   - 权重通过 `WeightConfig` 配置，支持运行时调整
4. `freshness` 分数：根据简历最后更新时间计算，30天内更新的加分
5. Rerank 支持批量处理，每批不超过 20 条，减少 API 调用次数
6. 排序结果输出 `RankedCandidate`：`resume_id`、`final_score`、`score_breakdown`（各维度分数明细）
7. 关键设计决策：Rerank 精排结合权重排序，Rerank 保证语义相关性，权重排序保证业务规则
8. 禁止事项：禁止将 Rerank 应用于全部结果（仅 Top-50）；禁止忽略 Rerank 异常直接返回原始排序

## 验收检查点

### 前置确认
- [ ] T-020（过滤 + 软匹配）已完成
- [ ] 容器环境已启动
- [ ] BGE Reranker 模型已部署或 API 可访问

### AC 验收
- [ ] AC-006: Rerank 后语义相关性高的候选人排序提升，`rerank_score` 正确写入
- [ ] AC-007: 权重排序输出 `final_score` 和 `score_breakdown`，各维度分数可追溯

### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] Rerank 批量大小可配置
- [ ] WeightConfig 支持运行时热更新
- [ ] Rerank 异常时有降级策略（返回原始排序 + 警告日志）
- [ ] 类型标注完整

### Spec 一致性
- [ ] Rerank 模型选择与 REQ-006 一致
- [ ] 权重公式与 REQ-007 一致
- [ ] `RankedCandidate` 结构与 `02-data-model.md` 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
