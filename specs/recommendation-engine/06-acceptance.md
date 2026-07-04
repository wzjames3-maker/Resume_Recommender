<!-- Module: recommendation-engine -->
<!-- Spec Layer: 06 - Acceptance Criteria -->
<!-- ⚠️ 部分更新: Embedding 引用已修正，AC 流程仍为旧架构，待 Tier L 全文重构 -->

# 验收标准：Recommendation Engine

## 验收标准总览

| ID | 验收项 | 覆盖需求 | 覆盖规则 | 覆盖边界 |
|----|--------|----------|----------|----------|
| AC-001 | Dense Retrieval 正常返回 | REQ-001 | - | - |
| AC-002 | Sparse Retrieval 正常返回 | REQ-002 | - | - |
| AC-003 | Hybrid Merge RRF 合并正确 | REQ-003 | RULE-001 | - |
| AC-004 | Metadata Filter 硬约束过滤正确 | REQ-004 | RULE-002 | - |
| AC-005 | Soft Match 近似匹配正确 | REQ-005 | RULE-003 | - |
| AC-006 | LLM Rerank 正常排序 | REQ-006 | - | - |
| AC-007 | 多维度加权排序分数正确 | REQ-007 | RULE-004 | EC-007 |
| AC-008 | 推荐理由完整性与 Faithfulness | REQ-008 | RULE-005, RULE-006 | EC-003 |
| AC-009 | Score Breakdown 五维度完整 | REQ-009 | RULE-005 | - |
| AC-010 | 去重正确 | REQ-010 | RULE-007 | EC-008 |
| AC-011 | 可配置权重生效 | REQ-011 | RULE-004 | EC-007 |
| AC-012 | Reranker 降级正常 | REQ-012 | RULE-009 | EC-002 |
| AC-013 | 全部候选人不满足约束时放宽重试 | - | - | EC-001 |
| AC-014 | 候选人数量不足 count 返回实际数量 | - | RULE-008 | EC-004 |
| AC-015 | Milvus 超时返回正确错误码 | - | - | EC-006 |

---

## AC-001: Dense Retrieval 正常返回

**覆盖**: REQ-001
**类型**: 功能

### Given-When-Then

```gherkin
Feature: Dense Retrieval

  Scenario: 正常查询返回 Dense 检索结果
    Given Milvus 中已有 100 条候选人向量数据
    And FlagEmbedding 本地推理 可用
    When 调用 hybrid_retrieve(query="Java工程师 5年", slots={...}, top_k=50)
    Then 返回的 candidates 列表长度 > 0
    And 每个 RetrievalResult 包含 dense_score（0~1 之间的浮点数）
    And 每个 RetrievalResult 包含 resume_id（非空字符串）
    And dense_score 按降序排列

  Scenario: Embedding 缓存命中
    Given 相同查询 "Java工程师 5年" 已在 10 分钟内执行过
    When 再次执行 hybrid_retrieve(query="Java工程师 5年", ...)
    Then FlagEmbedding 本地推理 不被调用（使用缓存）
    And 返回结果与首次一致
```

### 验证方法

1. 单元测试：Mock FlagEmbedding 本地推理 + Mock Milvus，验证返回结构
2. 集成测试：真实 Milvus + 真实 FlagEmbedding 本地推理，验证端到端

---

## AC-002: Sparse Retrieval 正常返回

**覆盖**: REQ-002
**类型**: 功能

### Given-When-Then

```gherkin
Feature: Sparse Retrieval

  Scenario: 正常查询返回 Sparse 检索结果
    Given Milvus 中已有 100 条候选人 Sparse 向量数据
    And FlagEmbedding 本地推理 可用
    When 调用 hybrid_retrieve(query="Spring Boot 微服务", slots={...}, top_k=50)
    Then 返回的 candidates 列表长度 > 0
    And 每个 RetrievalResult 包含 sparse_score（>= 0 的浮点数）
    And 包含关键词 "Spring Boot" 的候选人排名靠前
```

### 验证方法

1. 单元测试：Mock FlagEmbedding 本地推理 + Mock Milvus
2. 集成测试：真实 Milvus + 真实 FlagEmbedding 本地推理

---

## AC-003: Hybrid Merge RRF 合并正确

**覆盖**: REQ-003, RULE-001
**类型**: 功能

### Given-When-Then

```gherkin
Feature: Hybrid Merge

  Scenario: Dense 和 Sparse 结果通过 RRF 合并
    Given Dense 结果: [A(rank=1), B(rank=2), C(rank=3)]
    And Sparse 结果: [B(rank=1), C(rank=2), D(rank=3)]
    When 执行 hybrid_merge(dense_results, sparse_results, rrf_k=60)
    Then B 的 hybrid_score 最高（Dense rank=2 + Sparse rank=1）
    And C 的 hybrid_score 次高（Dense rank=3 + Sparse rank=2）
    And A 和 D 的 hybrid_score 较低（仅在一个检索器中有排名）
    And 结果按 hybrid_score 降序排列

  Scenario: RRF 分数计算正确
    Given candidate X: Dense rank=1, Sparse rank=1
    When RRF k=60
    Then hybrid_score = 1/(60+1) + 1/(60+1) = 2/61 ≈ 0.0328
```

### 验证方法

1. 单元测试：构造已知排名的输入，验证 RRF 公式计算结果

---

## AC-004: Metadata Filter 硬约束过滤正确

**覆盖**: REQ-004, RULE-002
**类型**: 功能

### Given-When-Then

```gherkin
Feature: Metadata Filter

  Scenario: 城市精确匹配
    Given 候选人列表: [张三(city=杭州), 李四(city=北京), 王五(city=杭州)]
    And filters: {city: "杭州"}
    When 执行 apply_filters(candidates, filters)
    Then 返回 [张三, 王五]
    And removed_count = 1

  Scenario: 学历向上兼容
    Given 候选人列表: [张三(edu=硕士), 李四(edu=本科), 王五(edu=博士)]
    And filters: {education: "硕士"}
    When 执行 apply_filters(candidates, filters)
    Then 返回 [张三, 王五]（硕士和博士通过，本科不通过）

  Scenario: 年限比较（>= 浮动）
    Given 候选人列表: [张三(exp=6), 李四(exp=3.5), 王五(exp=5)]
    And filters: {experience: 5, experience_op: ">="}
    And tolerance = 0.20
    When 执行 apply_filters(candidates, filters)
    Then 返回 [张三, 王五]（6年和5年通过）
    And 李四 不在结果中（3.5 < 5*0.8=4.0）

  Scenario: 排除列表
    Given 候选人列表: [张三(job_type=全职), 李四(job_type=外包)]
    And filters: {exclude_job_type: ["外包"]}
    When 执行 apply_filters(candidates, filters)
    Then 返回 [张三]
```

### 验证方法

1. 单元测试：覆盖每个过滤字段的各种匹配场景

---

## AC-005: Soft Match 近似匹配正确

**覆盖**: REQ-005, RULE-003
**类型**: 功能

### Given-When-Then

```gherkin
Feature: Soft Match

  Scenario: 技能近义词匹配
    Given 候选人张三有技能 ["Spring Boot", "MySQL", "Redis"]
    And filters: {skills: ["Java"]}
    And skill_synonyms: {"Java": ["Java", "Kotlin", "Spring Boot"]}
    When 执行 apply_filters with Soft Match
    Then 张三通过过滤（Spring Boot 近义词匹配 Java）
    And matched_skills 标注 match_type="synonym"

  Scenario: 年限浮动
    Given 候选人张三有 4 年经验
    And filters: {experience: 5, experience_op: ">="}
    And tolerance = 0.20
    When 执行 apply_filters
    Then 张三通过过滤（4年 >= 5*(1-0.2) = 4.0）

  Scenario: 学历不可降级
    Given 候选人张三是本科
    And filters: {education: "硕士"}
    When 执行 apply_filters
    Then 张三不通过（本科 < 硕士，不可降级）

  Scenario: 城市精确匹配
    Given 候选人张三期望城市 "上海"
    And filters: {city: "杭州"}
    When 执行 apply_filters
    Then 张三不通过（城市不匹配，不允许 Soft Match）
```

### 验证方法

1. 单元测试：覆盖技能近义词、年限浮动、学历不可降级、城市精确匹配

---

## AC-006: LLM Rerank 正常排序

**覆盖**: REQ-006
**类型**: 功能

### Given-When-Then

```gherkin
Feature: LLM Rerank

  Scenario: Reranker 正常排序
    Given 过滤后候选: [A(hybrid=0.9), B(hybrid=0.8), C(hybrid=0.85)]
    And query = "5年Java工程师"
    And BGE Reranker API 可用
    When 执行 rerank(candidates, query, slots)
    Then 每个 RetrievalResult 的 metadata.rerank_score 被填充（0~1）
    And 结果按 rerank_score 降序排列
    And latency_ms < 3000
```

### 验证方法

1. 集成测试：真实 Reranker API，验证排序结果

---

## AC-007: 多维度加权排序分数正确

**覆盖**: REQ-007, RULE-004, EC-007
**类型**: 功能

### Given-When-Then

```gherkin
Feature: 多维度加权排序

  Scenario: 默认权重计算正确
    Given 候选人张三的 score_breakdown:
      | skill_match | experience_match | project_relevance | industry_match | education_match |
      | 95          | 90               | 88                | 85             | 95              |
    And weight_config = 默认（0.40, 0.25, 0.20, 0.10, 0.05）
    When 计算 final_score
    Then final_score = 95*0.40 + 90*0.25 + 88*0.20 + 85*0.10 + 95*0.05
    And final_score = 38.0 + 22.5 + 17.6 + 8.5 + 4.75 = 91.35
    And final_score ≈ 91.4（保留1位小数）

  Scenario: 权重归一化
    Given weight_config = {skill: 0.5, experience: 0.3, project: 0.3, industry: 0.1, education: 0.1}
    And 权重总和 = 1.3
    When 创建 WeightConfig
    Then 自动归一化为:
      | skill | experience | project | industry | education |
      | 0.385 | 0.231      | 0.231   | 0.077    | 0.077     |
    And 归一化后权重总和 = 1.0
```

### 验证方法

1. 单元测试：构造已知 score_breakdown 和 weight_config，验证计算结果

---

## AC-008: 推荐理由完整性与 Faithfulness

**覆盖**: REQ-008, RULE-005, RULE-006, EC-003
**类型**: 功能

### Given-When-Then

```gherkin
Feature: 推荐理由生成

  Scenario: 正常生成推荐理由
    Given 候选人张三的简历包含: "6年Java开发经验，阿里巴巴高级工程师"
    And query = "5年Java工程师"
    And LLM API 可用
    When 执行 generate_reason(candidate, query, slots, score_breakdown)
    Then reason 列表长度 >= 2
    And 每条理由引用简历中的具体信息
    And matched_skills 中的每个技能在张三简历中存在
    And missing_skills 中的每个技能在 Slots 中要求但张三简历中不存在

  Scenario: LLM 幻觉处理
    Given LLM 生成了理由 "精通机器学习算法"，但张三简历中无 ML 相关内容
    When 后置校验
    Then 该条理由被移除
    And 用模板化理由补充

  Scenario: LLM 不可用降级
    Given LLM API 超时
    When 执行 generate_reason
    Then 返回模板化理由
    And degradation = "llm_fallback"
    And reason 列表长度 >= 2
```

### 验证方法

1. 单元测试：Mock LLM API，验证输出结构和校验逻辑
2. 集成测试：真实 LLM API，验证理由质量

---

## AC-009: Score Breakdown 五维度完整

**覆盖**: REQ-009, RULE-005
**类型**: 功能

### Given-When-Then

```gherkin
Feature: Score Breakdown

  Scenario: 五维度评分完整
    Given 候选人张三的排序已完成
    When 查看 RankingResult
    Then score_breakdown 包含 5 个字段
    And skill_match 在 0-100 之间
    And experience_match 在 0-100 之间
    And project_relevance 在 0-100 之间
    And industry_match 在 0-100 之间
    And education_match 在 0-100 之间
```

### 验证方法

1. 单元测试：验证 ScoreBreakdown Schema 的字段约束

---

## AC-010: 去重正确

**覆盖**: REQ-010, RULE-007, EC-008
**类型**: 功能

### Given-When-Then

```gherkin
Feature: Deduplication

  Scenario: 同一候选人多份简历去重
    Given 候选人列表: [
      张三(candidate_id=C001, resume_id=R001, hybrid=0.9),
      张三(candidate_id=C001, resume_id=R003, hybrid=0.95),
      李四(candidate_id=C002, resume_id=R002, hybrid=0.85)
    ]
    When 执行 deduplicate(candidates)
    Then 返回 [张三(resume_id=R003), 李四(resume_id=R002)]
    And 张三保留 hybrid_score 更高的 R003

  Scenario: 无重复候选人
    Given 候选人列表: [张三(C001), 李四(C002), 王五(C003)]
    When 执行 deduplicate(candidates)
    Then 返回 3 个候选人，无变化
```

### 验证方法

1. 单元测试：构造重复 candidate_id 的候选列表

---

## AC-011: 可配置权重生效

**覆盖**: REQ-011
**类型**: 功能

### Given-When-Then

```gherkin
Feature: 可配置排序权重

  Scenario: 使用默认权重
    Given weight_config = None
    And job_title = None
    When resolve_weights(job_title, weight_config)
    Then 返回默认权重（0.40, 0.25, 0.20, 0.10, 0.05）

  Scenario: 使用岗位预设权重
    Given weight_config = None
    And job_title = "算法工程师"
    And config/weight_presets.yaml 中有 "算法工程师" 预设
    When resolve_weights(job_title, weight_config)
    Then 返回预设权重（0.30, 0.20, 0.20, 0.10, 0.20）

  Scenario: 使用显式权重
    Given weight_config = {skill: 0.50, experience: 0.20, ...}
    When resolve_weights(job_title, weight_config)
    Then 返回传入的 weight_config（不查预设）
```

### 验证方法

1. 单元测试：覆盖三种优先级场景

---

## AC-012: Reranker 降级正常

**覆盖**: REQ-012, RULE-009, EC-002
**类型**: 功能 + 异常

### Given-When-Then

```gherkin
Feature: Reranker 降级

  Scenario: Reranker 超时降级
    Given BGE Reranker API 响应时间 > 3 秒
    When 执行 rerank(candidates, query, slots, timeout=3.0)
    Then 重试 1 次后仍超时
    And 结果按 hybrid_score 降序排列
    And degradation = "reranker_fallback"
    And 降级事件记录到 Audit Log

  Scenario: Reranker API 错误降级
    Given BGE Reranker API 返回 500 错误
    When 执行 rerank(candidates, query, slots)
    Then 结果按 hybrid_score 降序排列
    And degradation = "reranker_fallback"
```

### 验证方法

1. 单元测试：Mock Reranker API 返回超时/错误

---

## AC-013: 全部候选人不满足约束时放宽重试

**覆盖**: EC-001
**类型**: 异常

### Given-When-Then

```gherkin
Feature: 放宽约束重试

  Scenario: Level 1 放宽经验浮动
    Given 候选人列表: [张三(exp=4.5), 李四(exp=3)]
    And filters: {experience: 5, experience_op: ">=", tolerance: 0.20}
    When Level 0 过滤（tolerance=0.20, 下界=4.0）→ [张三]（非空，直接返回）
    Then 不触发放宽

  Scenario: 需要放宽到 Level 2
    Given 候选人列表: [张三(exp=3, city=上海)]
    And filters: {experience: 5, city: "杭州"}
    When Level 0 过滤 → 空
    And Level 1 放宽经验（tolerance=0.40, 下界=3.0）→ [张三]（非空）
    Then 返回 [张三]
    And relaxed_filters = ["经验浮动放宽至±40%"]

  Scenario: 全部放宽仍为空
    Given 候选人列表: [张三(exp=1, city=上海, edu=高中)]
    And filters: {experience: 5, city: "杭州", education: "硕士"}
    When 所有 Level 都返回空
    Then 返回空列表
    And relaxed_filters = ["已放宽所有条件，仍未找到候选人"]
```

### 验证方法

1. 单元测试：覆盖多级放宽场景

---

## AC-014: 候选人数量不足 count 返回实际数量

**覆盖**: RULE-008, EC-004
**类型**: 边界

### Given-When-Then

```gherkin
Feature: 候选人不足

  Scenario: 候选人不足 count
    Given 过滤后候选人: [张三, 李四]
    And count = 10
    When 执行 search_candidates(slots, count=10)
    Then 返回 2 条推荐结果
    And total_candidates = 2

  Scenario: 候选人恰好等于 count
    Given 过滤后候选人: 10 人
    And count = 10
    When 执行 search_candidates(slots, count=10)
    Then 返回 10 条推荐结果
    And total_candidates = 10
```

### 验证方法

1. 单元测试：构造不足 count 的候选列表

---

## AC-015: Milvus 超时返回正确错误码

**覆盖**: EC-006
**类型**: 异常

### Given-When-Then

```gherkin
Feature: Milvus 超时

  Scenario: Milvus 连接超时
    Given Milvus 服务不可用
    When 执行 hybrid_retrieve(query, slots, top_k)
    Then 重试 2 次后仍失败
    And 抛出 RetrievalError
    And error.code = "RETRIEVAL_TIMEOUT"
    And error.message 包含 "Milvus 连接超时"
    And 致命错误记录到 Audit Log
```

### 验证方法

1. 单元测试：Mock Milvus 连接超时
