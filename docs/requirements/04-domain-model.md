<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: 04-domain-model.md -->
<!-- Date: 2026-06-23 -->

# 04 - 领域模型（Domain Model）

## 核心实体关系图

```
                        +-------------------+
                        |    Conversation    |
                        +-------------------+
                        | conversation_id   |
                        | user_id           |
                        | turn_count        |
                        | created_at        |
                        +-------------------+
                               | 1
                               |
                               | N
                        +-------------------+
                        |    Message         |
                        +-------------------+
                        | message_id        |
                        | role              |
                        | content           |
                        | intent            |
                        | slots             |
                        | created_at        |
                        +-------------------+
                               |
                               |
               +---------------+---------------+
               |                               |
               v                               v
    +-------------------+            +-------------------+
    |  Recommendation   |            |   Knowledge QA    |
    +-------------------+            +-------------------+
    | recommendation_id |            | answer            |
    | query             |            | sources           |
    | candidates[]      |            +-------------------+
    | ranking_rules[]   |
    | created_at        |
    +-------------------+
               | 1
               |
               | N
    +-------------------+
    | RecommendedItem   |
    +-------------------+
    | candidate_id      |
    | score             |
    | rank              |
    | reason            |
    | matched_skills[]  |
    | missing_skills[]  |
    +-------------------+
               |
               | N
               |
               v
    +-------------------+
    |     Resume         |
    +-------------------+
    | resume_id          |
    | candidate_name     |
    | source_type        |
    | raw_file_path      |
    | parsed_at          |
    | status             |
    | created_at         |
    | updated_at         |
    +-------------------+
               | 1
               |
       +-------+-------+
       |       |       |
       v       v       v
  +--------+ +--------+ +--------+
  |Education| |Experience| |Project |
  +--------+ +--------+ +--------+
  |school   | |company  | |name    |
  |degree   | |title    | |role    |
  |major    | |duration | |desc    |
  |start    | |start    | |skills[]|
  |end      | |end      | |start   |
  |tier     | |desc     | |end     |
  +--------+ +--------+ +--------+

  +-------------------+
  |      Skill        |
  +-------------------+
  | skill_id          |
  | name              |
  | category          |
  | proficiency       |
  | years             |
  | source            |  (from_resume / inferred)
  +-------------------+

  +-------------------+
  |   JobRequest      |    (HR 发起的招聘需求)
  +-------------------+
  | request_id        |
  | title             |
  | description       |
  | filters{}         |
  | ranking_rules[]   |
  | created_by        |
  | status            |
  | created_at        |
  +-------------------+
```

---

## 实体详细定义

### 1. Resume（简历）

系统的核心实体，对应一份完整的候选人简历。

| 属性 | 类型 | 说明 |
|------|------|------|
| resume_id | UUID | 简历唯一标识 |
| candidate_name | string | 候选人姓名 |
| phone | string | 手机号（PII 加密存储） |
| email | string | 邮箱（PII 加密存储） |
| gender | enum | 性别 |
| age | integer | 年龄 |
| city | string | 所在城市 |
| source_type | enum | 来源类型（pdf/docx/image/json/upload） |
| raw_file_path | string | 原始文件存储路径 |
| parsed_content | text | 解析后的纯文本 |
| embedding_id | string | Milvus 中的向量 ID |
| status | enum | active / archived / deleted |
| parsed_at | datetime | 解析时间 |
| created_at | datetime | 入库时间 |
| updated_at | datetime | 最后更新时间 |

**关系**：
- 1:N Education
- 1:N Experience
- 1:N Project
- 1:N Skill

---

### 2. Education（教育经历）

| 属性 | 类型 | 说明 |
|------|------|------|
| education_id | UUID | 教育经历唯一标识 |
| resume_id | FK | 关联简历 |
| school | string | 学校名称 |
| degree | enum | 学历（高中/专科/本科/硕士/博士） |
| major | string | 专业 |
| start_date | date | 开始时间 |
| end_date | date | 结束时间 |
| tier | enum | 学校层级（985/211/双一流/普通） |

---

### 3. Experience（工作经历）

| 属性 | 类型 | 说明 |
|------|------|------|
| experience_id | UUID | 工作经历唯一标识 |
| resume_id | FK | 关联简历 |
| company | string | 公司名称 |
| title | string | 职位名称 |
| description | text | 工作描述 |
| start_date | date | 开始时间 |
| end_date | date | 结束时间（null = 至今） |
| industry | string | 行业 |
| is_outsource | boolean | 是否外包 |

---

### 4. Project（项目经历）

| 属性 | 类型 | 说明 |
|------|------|------|
| project_id | UUID | 项目经历唯一标识 |
| resume_id | FK | 关联简历 |
| name | string | 项目名称 |
| role | string | 担任角色 |
| description | text | 项目描述 |
| skills | string[] | 使用的技术栈 |
| start_date | date | 开始时间 |
| end_date | date | 结束时间 |

---

### 5. Skill（技能）

| 属性 | 类型 | 说明 |
|------|------|------|
| skill_id | UUID | 技能唯一标识 |
| resume_id | FK | 关联简历 |
| name | string | 技能名称 |
| category | enum | 技能分类（programming/framework/database/devops/soft_skill/other） |
| proficiency | enum | 熟练程度（了解/熟悉/熟练/精通） |
| years | integer | 使用年限 |
| source | enum | 来源（from_resume=简历提取 / inferred=系统推断） |

---

### 6. JobRequest（招聘需求）

HR 发起的招聘查询，对应一次 recruitment.search。

| 属性 | 类型 | 说明 |
|------|------|------|
| request_id | UUID | 需求唯一标识 |
| conversation_id | FK | 关联对话 |
| title | string | 需求标题 |
| description | text | 需求描述（原始用户输入） |
| filters | object | 过滤条件（Candidate Slots） |
| ranking_rules | object | 排序规则及权重 |
| created_by | string | 创建人 |
| status | enum | active / closed / archived |
| created_at | datetime | 创建时间 |

---

### 7. Recommendation（推荐结果）

一次推荐查询的完整结果。

| 属性 | 类型 | 说明 |
|------|------|------|
| recommendation_id | UUID | 推荐唯一标识 |
| request_id | FK | 关联招聘需求 |
| conversation_id | FK | 关联对话 |
| query | text | 原始查询 |
| intent | string | 识别的意图 |
| slots | object | 提取的 Slots |
| total_candidates | integer | 候选人总数 |
| latency_ms | integer | 推荐耗时（毫秒） |
| llm_tokens | integer | 消耗的 Token 数 |
| created_at | datetime | 推荐时间 |

**关系**：
- 1:N RecommendedItem

---

### 8. RecommendedItem（推荐条目）

推荐结果中的单个候选人条目。

| 属性 | 类型 | 说明 |
|------|------|------|
| item_id | UUID | 条目唯一标识 |
| recommendation_id | FK | 关联推荐 |
| resume_id | FK | 关联简历 |
| rank | integer | 排名 |
| score | float | 综合匹配分（0-100） |
| reason | text | 推荐理由 |
| matched_skills | string[] | 匹配的技能 |
| missing_skills | string[] | 缺失的技能 |
| matched_experience | text | 匹配的经验描述 |
| explanation | object | 详细评分拆解 |

---

### 9. Conversation（对话）

一次完整的用户对话会话。

| 属性 | 类型 | 说明 |
|------|------|------|
| conversation_id | UUID | 会话唯一标识 |
| user_id | string | 用户标识 |
| title | string | 会话标题（自动生成） |
| turn_count | integer | 对话轮次 |
| status | enum | active / closed |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 最后活跃时间 |

**关系**：
- 1:N Message
- 1:N Recommendation

---

### 10. Message（对话消息）

| 属性 | 类型 | 说明 |
|------|------|------|
| message_id | UUID | 消息唯一标识 |
| conversation_id | FK | 关联对话 |
| role | enum | user / assistant / system |
| content | text | 消息内容 |
| intent | string | 识别的意图 |
| confidence | float | 意图置信度 |
| slots | object | 提取的 Slots |
| tool_calls | array | 调用的工具列表 |
| latency_ms | integer | 响应耗时 |
| tokens | integer | 消耗 Token 数 |
| created_at | datetime | 发送时间 |

---

## 实体关系总结

```
Conversation  1---N  Message
Conversation  1---N  Recommendation
Recommendation 1---N  RecommendedItem
RecommendedItem N---1  Resume
Resume  1---N  Education
Resume  1---N  Experience
Resume  1---N  Project
Resume  1---N  Skill
JobRequest  1---N  Recommendation
```

---

## V2 预留实体

以下实体在领域模型中定义，但 V1 不实现，仅作为 V2 扩展预留：

- **Knowledge QA**: 知识问答实体（answer, sources），V1 不做知识问答功能

---

## 关键设计决策

### PII 数据处理
- phone、email 等敏感字段采用加密存储
- API 返回时默认脱敏，需要明确授权才能查看完整信息
- Audit Log 中不记录 PII 明文

### Embedding 与原文分离
- 原始简历文本存储在 Resume Store（MongoDB/PostgreSQL）
- Embedding 向量存储在 Milvus
- 两者的关联通过 embedding_id 维护
- 重建索引时可以独立重建向量，不影响原始数据

### Skill 标准化
- 技能名称需要标准化（如 "java" / "Java" / "JAVA" 统一为 "Java"）
- 维护技能同义词表（如 "Java后端" -> ["Java", "Spring Boot"]）
- 推断技能（inferred）需要标注来源和置信度


