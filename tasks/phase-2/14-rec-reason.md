# T-022: 推荐理由生成 + Score Breakdown

## 基本信息
- 对应 Spec: specs/recommendation-engine/01-requirements.md REQ-008, REQ-009
- 对应 AC: AC-008, AC-009
- 依赖: T-021
- 预计工时: 1.5 天

## 输入
- `specs/recommendation-engine/01-requirements.md` — 推荐理由生成需求
- `specs/recommendation-engine/02-data-model.md` — 推荐理由数据模型
- `src/recommendation_engine/reranker.py` — Rerank 模块（T-021 产出）
- `src/recommendation_engine/weight_scorer.py` — 权重排序（T-021 产出）

## 输出
- `src/recommendation_engine/reason_generator.py` — 推荐理由生成模块
- `src/recommendation_engine/score_breakdown.py` — Score Breakdown 展示模块
- `tests/recommendation_engine/test_reason_generator.py` — 推荐理由测试
- `tests/recommendation_engine/test_score_breakdown.py` — Score Breakdown 测试

## 实现要求
1. 推荐理由使用 LLM 生成，基于 `score_breakdown` 和候选人简历摘要，生成 1-3 句自然语言推荐理由
2. 推荐理由模板化 + LLM 润色：先用模板生成骨架，再用 LLM 润色为自然语言
3. Score Breakdown 展示：将 `final_score` 拆解为各维度可视化数据
   - 向量相似度得分、Rerank 精排得分、技能匹配度、经验匹配度、地点匹配度、简历新鲜度
4. 推荐理由必须基于真实得分数据，禁止编造不存在的优势
5. Batch 合并生成：Top-N 候选人的推荐理由打包到单个 Prompt 中，LLM 一次调用返回全部理由（默认 Top-5），严禁 N 次独立调用
6. 推荐理由缓存：Batch 和 Single 结果均缓存到 Redis（key=MD5(resume_id+query_hash)，TTL=24h）
7. 关键设计决策：Batch 合并 Prompt（单次 LLM 调用生成 Top-N 全部理由）+ 模板降级，RPM 降低 80%
8. Lazy Load 按需生成：前端展开详情时触发单个理由生成，先查 Redis 缓存，未命中再调 LLM single 模式
9. RPM 保护：Batch 模式下一次调用替代 N 次，结合 Redis 令牌桶限流器控制全局 LLM RPM
10. 禁止事项：禁止在推荐理由中泄露候选人 PII；禁止编造简历中不存在的技能或经历

## 验收检查点

### 前置确认
- [ ] T-021（Rerank + 权重排序）已完成
- [ ] 容器环境已启动
- [ ] LLM API 可访问

### AC 验收
- [ ] AC-008: Top-5 候选人均有推荐理由，理由内容与候选人简历信息一致，无编造
- [ ] AC-009: Score Breakdown 正确展示各维度分数，分数总和与 `final_score` 一致

- [ ] AC-010: Batch 模式下一次 LLM 调用返回 Top-5 全部理由（验证 API 调用次数 = 1）
- [ ] AC-011: Single/Lazy 模式下按需生成单个理由，Redis 缓存命中时不再调用 LLM
- [ ] AC-012: Batch 中部分候选人理由缺失时，对缺失候选人单独重试 1 次
### 代码质量
- [ ] lint pass（ruff + mypy）
- [ ] 推荐理由模板可配置
- [ ] Batch 生成有部分失败容错（缺失候选人单独重试）
- [ ] 缓存逻辑正确
- [ ] 类型标注完整

### Spec 一致性
- [ ] 推荐理由格式与 REQ-008 一致
- [ ] Score Breakdown 维度与 REQ-009 一致
- [ ] 输出结构与 `02-data-model.md` 一致

### 通过判定
全部 ✅ → Done | retry < 3 → 修复 | retry = 3 → BLOCKED
