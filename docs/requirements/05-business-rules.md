<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: 05-business-rules.md -->
<!-- Date: 2026-06-23 -->

# 05 - 业务规则（Business Rules）

## 一、推荐检索规则

### BR-01: Hybrid Retrieval（混合检索）

系统必须同时支持向量语义检索（Dense）和关键词检索（Sparse），最终结果通过 Hybrid Merge 合并去重。

- Dense Retrieval: 使用 Embedding 模型进行语义相似度检索
- Sparse Retrieval: 使用 Elasticsearch BM25 进行关键词匹配
- Merge 策略: Reciprocal Rank Fusion (RRF) 或可配置的加权合并

### BR-02: Metadata Filter（元数据过滤）

对可结构化表达的约束，在检索后进行硬过滤：

- 工作年限（experience）
- 学历（education）
- 城市（city）
- 性别（gender，若业务允许且符合法律法规）
- 期望岗位（job_title）
- 用工形式（job_type，用于排除外包等）

### BR-03: Soft Match（软匹配）

系统采用软匹配策略，而非严格布尔匹配。

**允许的模糊匹配**：
- "Java工程师" 可召回: Java / Kotlin+Java / Spring Boot / Java+Go
- "5年经验" 可召回: 4.5年 ~ 6年（可配置浮动范围）
- "985" 可召回: 985 / 211 / 双一流

**不允许的模糊匹配**：
- 城市必须精确匹配或明确标注可接受远程
- 学历只能向上兼容（要求硕士不可降为本科）

---

## 二、排序规则

### BR-04: 多维度加权排序

最终排序采用可配置的加权策略：

| 维度 | 默认权重 | 说明 |
|------|----------|------|
| 技能匹配度 | 40% | 技能重叠度 + 语义相似度 |
| 工作经验匹配 | 25% | 年限匹配 + 岗位相关性 |
| 项目经历相关性 | 20% | 项目领域 + 技术栈匹配 |
| 行业经验 | 10% | 行业匹配度 |
| 教育背景 | 5% | 学历 + 学校层级 |

**规则**：
- 权重可通过配置文件或 API 参数调整
- 不同岗位可有不同的权重配置
- 排序结果必须附带 Score（0-100）和 Reason

---

## 三、多轮对话规则

### BR-05: Refine 合并规则

当 Intent 为 recruitment.refine 时：

**增量合并**：新条件追加到已有条件
```
已有: skills=["Java"], city="杭州"
新增: gender="女"
合并: skills=["Java"], city="杭州", gender="女"
```

**条件覆盖**：同类条件被新值覆盖
```
已有: count=10
新增: count=20
结果: count=20
```

**排除条件**：否定表达追加到排除列表
```
已有: skills=["Java"]
新增: "不要外包"
结果: skills=["Java"], exclude_job_type=["外包"]
```

### BR-06: 检索范围决策

Refine 时是否重新检索全库：

| 条件变化类型 | 处理方式 |
|-------------|----------|
| 仅修改排序/数量 | 在 last_candidates 内重新排序 |
| 追加过滤条件 | 在 last_candidates 内过滤，结果为空则扩大到全库 |
| 修改核心条件（岗位/技能） | 重新全库检索 |
| 排除条件（不要XX） | 在 last_candidates 内过滤 |

### BR-07: 条件重置

当用户发起新的 recruitment.search 时，所有历史 filters 重置，开始全新查询。

---

## 四、推荐结果规则

### BR-08: 推荐数量

- 默认推荐 10 个候选人
- 用户可通过 count Slot 自定义（1-100）
- 如果符合条件的候选人不足 count 个，返回实际数量并提示

### BR-09: Explainability（可解释性）

每条推荐结果必须包含：

- score: 综合匹配分（0-100）
- reason: 推荐理由（自然语言，至少 2 条）
- matched_skills: 匹配的技能列表
- missing_skills: 缺失的技能列表
- matched_experience: 匹配的经验描述

### BR-10: Deduplication（去重）

同一候选人在一次推荐中只能出现一次。如果同一候选人有多份简历（如更新过），取最新版本。

---

## 五、简历入库规则

### BR-11: Resume Parser 策略

- 按语义段落切分（教育经历、工作经历、项目经历、技能），不按固定 Token 长度切块
- 每个段落保留 Metadata（段落类型、关联候选人）
- Chunk 内容与原始简历保持可追溯关联

### BR-12: Skill 标准化

- 技能名称统一标准化（大小写、别名映射）
- 维护同义词表: "Java后端" -> ["Java", "Spring Boot"]
- 推断技能必须标注 source=inferred 和置信度

### BR-13: PII 保护

- 手机号、邮箱等 PII 字段加密存储
- API 返回时默认脱敏（如 138****1234）
- Audit Log 中不记录 PII 明文

---

## 六、候选人详情规则

### BR-14: Candidate Lookup 解析

当 Intent 为 candidate.lookup 时：

- "第一个人" / "第一个" -> last_candidates[0]
- "张三" -> 在 last_candidates 中按 name 匹配
- "他的项目经历" -> 对已定位的候选人查询 Project 实体

### BR-15: Candidate Compare 规则

对比维度默认包含：
- 技能对比（匹配/缺失）
- 工作经验对比（年限/岗位/公司）
- 项目经历对比（领域/技术栈）
- 教育背景对比

---

## 七、数据统计规则

### BR-16: Analytics 查询

支持的统计维度：
- 按技能统计: "人才库有多少Java工程师"
- 按城市统计: "北京有多少算法工程师"
- 按经验统计: "3年以下的有多少人"
- 按学历统计: "硕士以上有多少"

统计结果必须基于实时查询，不使用缓存。

---

## 八、兜底规则

### BR-17: Fallback 处理

当意图置信度低于阈值（建议 0.6）时：

- 触发 Fallback
- 返回引导性回复，不静默失败
- 引导内容: 简述系统能力 + 示例查询
- 记录到 Audit Log 用于后续优化
