# 需求收集与澄清（Phase 1）

> 合并自 docs/requirements/ 目录下 8 个文件
> 日期：2026-06-23

---

<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: requirements-summary.md -->
<!-- Date: 2026-06-23 -->

# Phase 1 需求收集总结

## 交付物清单

| 文件 | 内容 | 状态 |
|------|------|------|
| 01-user-journey.md | 用户旅程（主旅程 + 3个子旅程） | Done |
| 02-intent-inventory.md | 意图清单（10类 Intent + 详细定义） | Done |
| 03-slot-definition.md | 参数定义（3类 Slot + 提取示例） | Done |
| 04-domain-model.md | 领域模型（10个实体 + 关系图） | Done |
| 05-business-rules.md | 业务规则（17条 BR） | Done |
| 06-output-contract.md | 输出契约（8种响应结构 + 错误码） | Done |
| 07-non-functional.md | 非功能需求（16条 NFR） | Done |

---

## 核心决策记录

### D-01: 产品定位
- 企业内部智能招聘助手（Enterprise AI Recruiting Assistant）
- 单企业内部部署，V1 不做 SaaS 多租户
- 作为 AI 检索推荐层，通过 API 集成现有 ATS

### D-02: 推荐策略
- 采用软匹配（Soft Match），非严格布尔匹配
- 三阶段: Hybrid Retrieval -> Metadata Filter -> LLM Rerank
- 排序权重可配置（默认: 技能40% + 经验25% + 项目20% + 行业10% + 教育5%）

### D-03: 多轮对话
- 支持增量合并、条件覆盖、条件重置三种 Refine 策略
- 依赖 Conversation Memory 维护上下文
- Refine 时智能决策是否重新全库检索

### D-04: 意图体系
- 10类 Intent，覆盖招聘检索、候选人管理、知识问答、数据分析
- Intent Router 支持上下文感知（多轮对话）
- Fallback 必须给出引导性回复

### D-05: 数据规模
- V1: 10万份简历，可扩展至100万+
- 按语义段落切分，不按固定 Token 长度切块
- 支持 PDF / DOCX / 图片 OCR / JSON

### D-06: 输出规范
- 每条推荐必须包含: score + reason + matched_skills + missing_skills + score_breakdown
- PII 数据默认脱敏
- 统一错误码体系

### D-07: 非功能约束
- P95 响应时间 <=3s，支持 Streaming
- 必须支持 Explainability 和 Audit Log
- LLM 和向量库均可替换（抽象接口）

---

## 待确认事项

以下事项需要在 Phase 2（可行性分析）或 Phase 3（PRD）中进一步明确：

| # | 事项 | 影响范围 | 优先级 |
|---|------|----------|--------|
| 1 | Embedding 模型选型（BGE / OpenAI / Jina） | 检索质量 | P0 |
| 2 | LLM 选型（GPT-4 / Claude / Qwen / DeepSeek） | 全局 | P0 |
| 3 | Resume Parser 实现方案（自研 vs Unstructured.io vs LlamaParse） | 简历解析质量 | P0 |
| 4 | 性别字段是否需要过滤（法律法规合规性） | 数据模型 + 业务规则 | P1 |
| 5 | 技能标准化词典的维护方式 | Skill 质量 | P1 |
| 6 | 简历加密存储的密钥管理方案 | 安全性 | P1 |
| 7 | 生产环境部署架构（K8s 资源规划） | 部署 | P2 |

---

## Phase 1 Checklist 自检

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | 用户旅程覆盖主要场景 | Done |
| 2 | 意图清单完整（10类 Intent） | Done |
| 3 | Slot 定义清晰（3类，含示例） | Done |
| 4 | 领域模型定义完整（10个实体） | Done |
| 5 | 业务规则可执行（17条 BR） | Done |
| 6 | 输出契约明确（8种结构 + 错误码） | Done |
| 7 | 非功能需求量化（16条 NFR） | Done |
| 8 | 核心决策已记录 | Done |
| 9 | 待确认事项已列出 | Done |

All checks passed. Phase 1 完成，可进入 Phase 2（可行性分析）。

---

<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: 01-user-journey.md -->
<!-- Date: 2026-06-23 -->

# 01 — 用户旅程（User Journey）

## 核心用户角色

| 角色 | 描述 | 使用频率 |
|------|------|----------|
| HR | 负责初筛简历、生成推荐名单 | 每日高频 |
| Tech Recruiter | 技术招聘专员，关注技能匹配 | 每日高频 |
| Hiring Manager | 用人部门负责人，审核推荐结果 | 按需使用 |

## 主旅程：从招聘需求到推荐名单

`
┌─────────────────────────────────────────────────────────────────────┐
│                        HR 发起招聘需求                               │
│                   "找5年Java后端，杭州，985"                          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Intent Router 识别意图                             │
│              recruitment.search → Hybrid Search                     │
│              解析 Slots: job_title=Java, exp=5yr, city=杭州,         │
│                        education=985                                │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                Hybrid Retrieval (Dense + Sparse)                    │
│         Milvus 向量检索 + Elasticsearch 关键词检索                    │
│                        → Merge + Dedup                             │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Metadata Filter + LLM Rerank                           │
│         工作年限、学历、城市等硬约束过滤                               │
│         LLM 综合排序: 技能(40%) + 经验(25%) + 项目(20%) +            │
│                      行业(10%) + 教育(5%)                           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     推荐结果输出                                      │
│         Top-N 候选人 + Score + Reason + Skills + Missing             │
│                    (Streaming 流式返回)                              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    HR 进入多轮对话                                    │
│                                                                     │
│  "女生呢"              → recruitment.refine (加 gender=F 过滤)       │
│  "学历高一点"           → recruitment.refine (升 education 约束)      │
│  "不要外包"            → recruitment.refine (加 exclude=outsource)   │
│  "再推荐几个"           → recruitment.refine (扩 count)              │
│  "对比前两个候选人"      → recruitment.compare                       │
│  "看看张三的简历"       → candidate.lookup                          │
│  "Java薪资范围多少"     → knowledge.qa                              │
│  "人才库有多少Java"     → analytics                                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   HR 确认推荐名单                                     │
│              提交给业务部门 / Hiring Manager                          │
└─────────────────────────────────────────────────────────────────────┘
`

## 子旅程 1：简历入库

`
HR / 系统管理员上传简历（PDF / DOCX / 图片 / JSON）
    ↓
Resume Parser 解析 → 结构化数据
    ↓
写入 Resume Store（MongoDB / PostgreSQL）
    ↓
生成 Embedding → 写入 Vector Index（Milvus）
    ↓
更新 Elasticsearch 索引
    ↓
入库完成，可用于检索
`

## 子旅程 2：候选人详情查看

`
HR: "第一个人是谁？"
    ↓
Intent: candidate.lookup
    ↓
从上次推荐结果中提取 candidate_id
    ↓
查询完整简历信息
    ↓
返回结构化候选人详情
`

## 子旅程 3：推荐结果对比

`
HR: "对比前两个候选人"
    ↓
Intent: recruitment.compare
    ↓
提取 last_candidates[0:2]
    ↓
LLM 生成对比分析
    ↓
返回并排对比表格（技能、经验、项目、教育）
`


---

<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: 02-intent-inventory.md -->
<!-- Date: 2026-06-23 -->

# 02 — 意图清单（Intent Inventory）

## 意图分类总览

| Intent | 分类 | 描述 | 触发 Workflow | 优先级 |
|--------|------|------|---------------|--------|
| 
ecruitment.search | 招聘 | 初始招聘检索 | Hybrid Search | P0 |
| 
ecruitment.refine | 招聘 | 对上一次结果进行条件修正 | Filter Last Result | P0 |
| 
ecruitment.compare | 招聘 | 对比多个候选人 | Candidate Compare | P1 |
| candidate.lookup | 候选人 | 查看某位候选人详情 | Resume Detail | P1 |
| 
esume.upload | 简历 | 上传新简历入库 | Resume Parser | P0 |
| 
esume.manage | 简历 | 管理已有简历（删除、重新解析） | Resume Management | P2 |
| knowledge.qa | 知识 | 行业/薪资/岗位知识问答 | Knowledge RAG | P2 |
| nalytics | 分析 | 人才库统计数据查询 | Statistics | P2 |
| chat | 通用 | 闲聊/寒暄/通用对话 | Chat | P3 |
| allback | 兜底 | 无法识别意图 | Recovery | P0 |

## 意图详细定义

### 1. 
ecruitment.search — 招聘检索

**描述**：HR 发起新的招聘需求，系统进行初始候选人检索。

**典型输入**：
`
找5年Java工程师，杭州，985
推荐几个算法工程师
需要3个有大厂经验的后端
有做过电商的PM吗
`

**Workflow**：
`
Intent Router
    ↓
Slot Extraction
    ↓
Hybrid Retrieval (Dense + Sparse)
    ↓
Metadata Filter
    ↓
LLM Rerank
    ↓
Output Top-N
`

**输出**：候选人列表 + Score + Reason + Skills + Missing

---

### 2. 
ecruitment.refine — 条件修正

**描述**：HR 在上一次推荐结果基础上，追加/修改/排除条件。

**典型输入**：
`
女生呢
学历高一点
不要外包
年龄小一点
再推荐几个
按经验排序
薪资20k以下的
`

**Workflow**：
`
解析当前 Query 的增量 Slots
    ↓
合并 last_query + last_filters + new_slots
    ↓
在 last_candidates 范围内重新过滤/排序
    ↓
或在全库重新检索（视条件变化幅度）
    ↓
Output Top-N
`

**关键依赖**：Conversation Memory（last_query, last_filters, last_candidates）

---

### 3. 
ecruitment.compare — 候选人对比

**描述**：HR 要求对比多个候选人。

**典型输入**：
`
对比前两个候选人
张三和李四哪个更合适
这三个人的技能差异是什么
`

**Workflow**：
`
提取目标候选人（从 last_candidates 或 by name）
    ↓
获取各候选人完整简历数据
    ↓
LLM 生成多维度对比分析
    ↓
Output 对比表格
`

---

### 4. candidate.lookup — 候选人详情

**描述**：HR 查看某位候选人的完整信息。

**典型输入**：
`
第一个人是谁
看看张三的简历
他的项目经历详细说说
`

**Workflow**：
`
识别候选人（by name / by position in last_candidates）
    ↓
查询 Resume Store 获取完整数据
    ↓
LLM 生成结构化摘要
    ↓
Output 候选人详情
`

---

### 5. 
esume.upload — 简历上传

**描述**：HR 或管理员上传新简历到人才库。

**典型输入**：
`
上传这份简历
导入这批简历
`

**Workflow**：
`
接收文件（PDF / DOCX / Image / JSON）
    ↓
Resume Parser 解析
    ↓
写入 Resume Store
    ↓
生成 Embedding → 写入 Milvus
    ↓
更新 Elasticsearch 索引
    ↓
返回入库状态
`

---

### 6. 
esume.manage — 简历管理

**描述**：对已有简历进行管理操作。

**典型输入**：
`
删除这份简历
重新解析这份简历
更新张三的信息
`

**Workflow**：
`
识别目标简历
    ↓
执行操作（delete / re-parse / update）
    ↓
同步更新 Resume Store + Vector Index + ES
    ↓
返回操作结果
`

---

### 7. knowledge.qa — 知识问答

**描述**：HR 询问行业、薪资、岗位等知识性问题。

**典型输入**：
`
Java工程师薪资范围是多少
P7和P8的职级区别
算法工程师需要什么技能
`

**Workflow**：
`
Knowledge RAG 检索
    ↓
LLM 生成回答
    ↓
Output 知识回答
`

---

### 8. nalytics — 数据分析

**描述**：HR 查询人才库统计数据。

**典型输入**：
`
人才库有多少Java工程师
北京的算法工程师有多少
3年以下经验的有多少人
`

**Workflow**：
`
解析统计维度和条件
    ↓
查询 Resume Store 聚合统计
    ↓
Output 统计结果
`

---

### 9. chat — 闲聊

**描述**：通用对话，无明确业务意图。

**典型输入**：
`
你好
谢谢
今天天气怎么样
`

**Workflow**：
`
LLM 直接回复
    ↓
Output 对话响应
`

---

### 10. allback — 兜底

**描述**：系统无法识别用户意图时的兜底处理。

**典型输入**：
`
asdfghjkl
帮我订个外卖
（语音识别错误的乱码）
`

**Workflow**：
`
意图置信度低于阈值
    ↓
触发 Fallback
    ↓
Output 引导性回复
    例："我是招聘助手，可以帮您搜索候选人、上传简历等，请问有什么需要？"
`

## 意图识别优先级

当多个意图可能匹配时，按以下优先级判断：

`
1. resume.upload        （明确动作，优先识别）
2. resume.manage        （明确动作）
3. recruitment.compare  （包含对比关键词）
4. candidate.lookup     （包含查看详情关键词）
5. recruitment.refine   （有上文且为条件性输入）
6. recruitment.search   （默认招聘意图）
7. analytics            （包含统计关键词）
8. knowledge.qa         （包含知识性关键词）
9. chat                 （通用对话）
10. fallback            （兜底）
`

## Intent Router 设计约束

- 意图识别必须支持上下文（多轮对话），不能仅基于单条消息判断
- 
ecruitment.refine 依赖 Conversation Memory，必须有上一次 
ecruitment.search 的上下文
- allback 必须给出引导性回复，不能静默失败
- 所有意图识别结果必须写入 Audit Log

---

<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: 03-slot-definition.md -->
<!-- Date: 2026-06-23 -->

# 03 - 参数定义（Slot Definition）

## Slot 分类体系

系统 Slot 分为三大类：Candidate Slot（候选人属性）、Query Slot（查询控制参数）、Conversation Slot（对话上下文）。

---

## 一、Candidate Slot（候选人属性）

描述候选人本身特征的 Slot，用于检索过滤和匹配。

| Slot | 类型 | 说明 | 示例 | 必填 |
|------|------|------|------|------|
| job_title | string | 目标岗位/职位 | Java工程师、算法工程师、产品经理 | 是 |
| skills | string[] | 技能列表 | Java, Spring Boot, MySQL | 否 |
| experience | number | 工作年限 | 5 | 否 |
| experience_op | enum | 年限比较运算符 | >=, <=, =, between | 否 |
| education | enum | 学历要求 | 本科、硕士、博士、985、211 | 否 |
| gender | enum | 性别 | 男、女 | 否 |
| age | number | 年龄 | 28 | 否 |
| age_op | enum | 年龄比较运算符 | >=, <=, between | 否 |
| city | string | 工作城市 | 杭州、北京、上海 | 否 |
| industry | string | 行业经验 | 电商、金融、游戏 | 否 |
| company | string | 公司经历 | 阿里巴巴、字节跳动 | 否 |
| school | string | 毕业学校 | 清华大学、浙大 | 否 |
| salary | number | 期望薪资 | 25000 | 否 |
| salary_op | enum | 薪资比较运算符 | >=, <=, between | 否 |
| language | string[] | 语言能力 | 英语六级、日语N1 | 否 |
| certificate | string[] | 证书资质 | PMP、CPA、AWS认证 | 否 |
| job_type | enum | 用工形式 | 全职、兼职、外包、实习 | 否 |
| status | enum | 候选人状态 | 在职、离职、看机会 | 否 |

### Slot 解析规则

**复合表达**：
- "5年以上Java" -> experience=5, experience_op=>=, skills=[Java]
- "3到5年经验" -> experience=[3,5], experience_op=between
- "20k以下" -> salary=20000, salary_op=<=
- "不要外包" -> job_type!=外包 (排除条件)
- "985硕士" -> education=硕士, school_tier=985

---

## 二、Query Slot（查询控制参数）

控制推荐结果的呈现方式，不属于候选人属性。

| Slot | 类型 | 说明 | 示例 | 默认值 |
|------|------|------|------|--------|
| count | integer | 推荐数量 | 10 | 10 |
| sort_by | enum | 排序字段 | score、experience、education、recent | score |
| order | enum | 排序方向 | asc、desc | desc |
| page | integer | 页码 | 1 | 1 |
| top_k | integer | 检索召回数量 | 50 | 50 |

### 使用场景

- "推荐20个" -> count=20
- "按经验排序" -> sort_by=experience
- "第一页" -> page=1
- "再推荐几个" -> count = last_count + 5（增量）

---

## 三、Conversation Slot（对话上下文）

维护多轮对话状态，由系统自动管理，用户不直接设定。

| Slot | 类型 | 说明 | 生命周期 |
|------|------|------|----------|
| conversation_id | string | 会话唯一标识 | 整个对话 |
| last_query | object | 上一次查询的完整 Slots | 单轮，可被覆盖 |
| last_filters | object | 上一次生效的过滤条件 | 单轮，可被合并 |
| last_candidates | array | 上一次推荐的候选人列表 | 单轮，可被引用 |
| last_sort_by | enum | 上一次排序方式 | 单轮，可被覆盖 |
| turn_count | integer | 当前对话轮次 | 整个对话 |
| intent_history | array | 历史意图序列 | 整个对话 |

### 上下文合并规则

**增量合并**（recruitment.refine）：
- Turn 1: "找Java工程师" -> skills=[Java]
- Turn 2: "女生呢" -> skills=[Java], gender=女
- Turn 3: "学历高一点" -> skills=[Java], gender=女, education=硕士
- Turn 4: "不要外包" -> skills=[Java], gender=女, education=硕士, exclude=[外包]

**条件覆盖**：
- Turn 1: "推荐10个" -> count=10
- Turn 2: "推荐20个" -> count=20（覆盖）

**条件重置**（当用户发起新的 recruitment.search）：
- Turn 3: "找算法工程师" -> 重置所有 last_filters，开始新查询

---

## 四、Slot Extraction 示例

### 示例 1：初始查询
```
输入: "找5年Java工程师，杭州，985"

提取结果:
{
  "intent": "recruitment.search",
  "slots": {
    "job_title": "Java工程师",
    "skills": ["Java"],
    "experience": 5,
    "experience_op": ">=",
    "city": "杭州",
    "education": "985"
  },
  "query_slots": {
    "count": 10,
    "sort_by": "score",
    "order": "desc"
  }
}
```

### 示例 2：条件修正
```
输入: "女生呢"
上下文: last_query = { job_title: "Java工程师", ... }

提取结果:
{
  "intent": "recruitment.refine",
  "slots": {
    "gender": "女"
  },
  "merged_slots": {
    "job_title": "Java工程师",
    "skills": ["Java"],
    "experience": 5,
    "experience_op": ">=",
    "city": "杭州",
    "education": "985",
    "gender": "女"
  }
}
```

### 示例 3：候选人查看
```
输入: "第一个人是谁"
上下文: last_candidates = [{ name: "张三", id: "xxx" }, ...]

提取结果:
{
  "intent": "candidate.lookup",
  "slots": {
    "candidate_ref": "last_candidates[0]"
  },
  "resolved": {
    "candidate_id": "xxx",
    "candidate_name": "张三"
  }
}
```

---

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



---

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

---

<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: 06-output-contract.md -->
<!-- Date: 2026-06-23 -->

# 06 - 输出契约（Output Contract）

## 一、推荐结果输出（recruitment.search / recruitment.refine）

### 响应结构

```json
{
  "conversation_id": "conv_abc123",
  "intent": "recruitment.search",
  "slots_parsed": {
    "job_title": "Java工程师",
    "skills": ["Java"],
    "experience": 5,
    "experience_op": ">=",
    "city": "杭州",
    "education": "985"
  },
  "total_candidates": 28,
  "recommendations": [
    {
      "rank": 1,
      "candidate": {
        "resume_id": "resume_xyz789",
        "name": "张三",
        "gender": "男",
        "age": 28,
        "city": "杭州",
        "education": {
          "degree": "硕士",
          "school": "浙江大学",
          "tier": "985"
        },
        "current_company": "阿里巴巴",
        "current_title": "高级Java工程师",
        "total_experience": 6
      },
      "score": 92.5,
      "reason": [
        "6年Java后端开发经验，超过要求的5年",
        "精通Spring Boot与微服务架构，技术栈高度匹配",
        "具有大型电商项目经验，业务场景契合"
      ],
      "matched_skills": ["Java", "Spring Boot", "MySQL", "Redis"],
      "missing_skills": ["Kafka"],
      "matched_experience": "6年后端开发，含3年电商行业",
      "score_breakdown": {
        "skill_match": 95,
        "experience_match": 90,
        "project_relevance": 88,
        "industry_match": 85,
        "education_match": 95
      }
    }
  ],
  "latency_ms": 2340,
  "llm_tokens": 1580,
  "timestamp": "2026-06-23T10:30:00Z"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| conversation_id | string | 是 | 会话 ID |
| intent | string | 是 | 识别的意图 |
| slots_parsed | object | 是 | 解析的 Slots |
| total_candidates | integer | 是 | 符合条件的候选人总数 |
| recommendations | array | 是 | 推荐列表 |
| recommendations[].rank | integer | 是 | 排名（1-based） |
| recommendations[].candidate | object | 是 | 候选人基本信息 |
| recommendations[].score | float | 是 | 综合匹配分（0-100） |
| recommendations[].reason | string[] | 是 | 推荐理由（至少2条） |
| recommendations[].matched_skills | string[] | 是 | 匹配的技能 |
| recommendations[].missing_skills | string[] | 是 | 缺失的技能 |
| recommendations[].matched_experience | string | 是 | 匹配的经验摘要 |
| recommendations[].score_breakdown | object | 是 | 各维度评分拆解 |
| latency_ms | integer | 是 | 推荐耗时（毫秒） |
| llm_tokens | integer | 是 | 消耗 Token 数 |
| timestamp | datetime | 是 | 响应时间戳 |

---

## 二、候选人详情输出（candidate.lookup）

```json
{
  "conversation_id": "conv_abc123",
  "intent": "candidate.lookup",
  "candidate": {
    "resume_id": "resume_xyz789",
    "name": "张三",
    "gender": "男",
    "age": 28,
    "city": "杭州",
    "phone": "138****1234",
    "email": "zhang***@gmail.com",
    "education": [
      {
        "school": "浙江大学",
        "degree": "硕士",
        "major": "计算机科学",
        "start_date": "2016-09",
        "end_date": "2019-06",
        "tier": "985"
      }
    ],
    "experience": [
      {
        "company": "阿里巴巴",
        "title": "高级Java工程师",
        "industry": "电商",
        "start_date": "2019-07",
        "end_date": null,
        "is_outsource": false,
        "description": "负责核心交易系统架构设计..."
      }
    ],
    "projects": [
      {
        "name": "双十一大促系统",
        "role": "技术负责人",
        "description": "主导大促期间交易系统的高可用改造...",
        "skills": ["Java", "Spring Boot", "Redis", "Kafka"],
        "start_date": "2021-01",
        "end_date": "2022-06"
      }
    ],
    "skills": [
      {"name": "Java", "category": "programming", "proficiency": "精通", "years": 6, "source": "from_resume"},
      {"name": "Spring Boot", "category": "framework", "proficiency": "精通", "years": 5, "source": "from_resume"}
    ],
    "summary": "6年Java后端开发经验，目前在阿里巴巴担任高级工程师，精通微服务架构和高并发系统设计。"
  },
  "latency_ms": 850,
  "timestamp": "2026-06-23T10:31:00Z"
}
```

### PII 脱敏规则

| 字段 | 脱敏方式 | 示例 |
|------|----------|------|
| phone | 保留前3后4 | 138****1234 |
| email | 保留首字母和域名 | zhang***@gmail.com |
| name | 不脱敏 | 张三 |

---

## 三、候选人对比输出（recruitment.compare）

```json
{
  "conversation_id": "conv_abc123",
  "intent": "recruitment.compare",
  "compared_candidates": ["张三", "李四"],
  "comparison": {
    "skill_comparison": {
      "common_skills": ["Java", "MySQL"],
      "only_first": ["Spring Boot", "Redis"],
      "only_second": ["Go", "Docker"]
    },
    "experience_comparison": {
      "first": {"years": 6, "companies": ["阿里巴巴"], "title": "高级Java工程师"},
      "second": {"years": 5, "companies": ["字节跳动"], "title": "Go工程师"}
    },
    "project_comparison": {
      "first": {"count": 3, "highlight": "双十一大促系统"},
      "second": {"count": 2, "highlight": "推荐系统重构"}
    },
    "education_comparison": {
      "first": {"degree": "硕士", "school": "浙江大学", "tier": "985"},
      "second": {"degree": "本科", "school": "北京大学", "tier": "985"}
    },
    "summary": "张三在Java生态和电商经验方面更强，李四在Go和云原生方面更有优势。如果岗位偏Java后端，推荐张三；如果偏基础设施，推荐李四。"
  },
  "latency_ms": 1200,
  "timestamp": "2026-06-23T10:32:00Z"
}
```

---

## 四、知识问答输出（knowledge.qa）

```json
{
  "conversation_id": "conv_abc123",
  "intent": "knowledge.qa",
  "question": "Java工程师薪资范围是多少",
  "answer": "根据市场行情，Java工程师薪资范围如下：\n- 初级（1-3年）：15K-25K\n- 中级（3-5年）：25K-40K\n- 高级（5年以上）：40K-70K\n- 架构师：60K-100K+\n\n以上为一线城市（北京/上海/杭州/深圳）的参考范围，实际薪资因公司规模、行业和个人能力有所差异。",
  "sources": ["市场薪资报告2026", "人才库统计"],
  "confidence": 0.85,
  "latency_ms": 1500,
  "timestamp": "2026-06-23T10:33:00Z"
}
```

---

## 五、数据分析输出（analytics）

```json
{
  "conversation_id": "conv_abc123",
  "intent": "analytics",
  "query": "人才库有多少Java工程师",
  "result": {
    "total": 3250,
    "breakdown": {
      "by_experience": {
        "1-3年": 1200,
        "3-5年": 1100,
        "5-10年": 800,
        "10年以上": 150
      },
      "by_city": {
        "北京": 850,
        "上海": 720,
        "杭州": 680,
        "深圳": 500,
        "其他": 500
      },
      "by_education": {
        "本科": 2100,
        "硕士": 950,
        "博士": 200
      }
    }
  },
  "latency_ms": 600,
  "timestamp": "2026-06-23T10:34:00Z"
}
```

---

## 六、简历上传输出（resume.upload）

```json
{
  "conversation_id": "conv_abc123",
  "intent": "resume.upload",
  "upload_result": {
    "resume_id": "resume_new001",
    "filename": "张三_简历.pdf",
    "status": "success",
    "parsed_fields": {
      "name": "张三",
      "skills_count": 12,
      "experience_count": 3,
      "education_count": 2,
      "project_count": 4
    },
    "warnings": [],
    "indexed": true
  },
  "latency_ms": 3200,
  "timestamp": "2026-06-23T10:35:00Z"
}
```

---

## 七、Fallback 输出（fallback）

```json
{
  "conversation_id": "conv_abc123",
  "intent": "fallback",
  "original_input": "asdfghjkl",
  "response": "抱歉，我没有理解您的意思。我是招聘助手，可以帮您：\n1. 搜索候选人（如：找5年Java工程师）\n2. 上传简历\n3. 查看人才库统计\n4. 回答招聘相关问题\n\n请问有什么可以帮您？",
  "latency_ms": 200,
  "timestamp": "2026-06-23T10:36:00Z"
}
```

---

## 八、错误输出（通用）

```json
{
  "error": {
    "code": "RESUME_NOT_FOUND",
    "message": "未找到指定候选人",
    "details": {
      "candidate_name": "王五",
      "suggestion": "请检查候选人姓名是否正确，或尝试其他关键词"
    }
  },
  "conversation_id": "conv_abc123",
  "timestamp": "2026-06-23T10:37:00Z"
}
```

### 错误码定义

| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| INVALID_INPUT | 400 | 输入参数无效 |
| RESUME_NOT_FOUND | 404 | 候选人未找到 |
| RESUME_PARSE_FAILED | 422 | 简历解析失败 |
| INTENT_RECOGNITION_FAILED | 422 | 意图识别失败（fallback） |
| RETRIEVAL_TIMEOUT | 504 | 检索超时 |
| LLM_ERROR | 502 | LLM 调用失败 |
| INTERNAL_ERROR | 500 | 内部错误 |

---

<!-- Phase: Phase 1 - Requirements -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- File: 07-non-functional.md -->
<!-- Date: 2026-06-23 -->

# 07 - 非功能需求（Non-functional Requirements）

## 一、性能需求

### NFR-01: 响应时间

| 场景 | P95 目标 | P99 目标 |
|------|----------|----------|
| 初始推荐（recruitment.search） | <=3s | <=5s |
| 条件修正（recruitment.refine） | <=2s | <=3s |
| 候选人详情（candidate.lookup） | <=1s | <=2s |
| 候选人对比（recruitment.compare） | <=2s | <=3s |
| 知识问答（knowledge.qa） | <=3s | <=5s |
| 数据统计（analytics） | <=1s | <=2s |
| 简历解析（resume.upload 单份） | <=5s | <=10s |
| 简历解析（批量 100 份） | <=5min | <=10min |

### NFR-02: Streaming

- 推荐结果支持 Streaming 流式返回
- 首 Token 响应时间 <=800ms
- 用户体验目标: 0.8s 开始输出，2-3s 推荐完成

### NFR-03: 吞吐量

| 指标 | 目标 |
|------|------|
| 并发用户数 | >=50 |
| QPS（推荐查询） | >=20 |
| QPS（简历入库） | >=10 |

---

## 二、可解释性需求

### NFR-04: Explainability

每条推荐结果必须包含完整的可解释信息：

| 字段 | 要求 |
|------|------|
| score | 0-100 综合匹配分 |
| reason | 自然语言推荐理由，至少2条 |
| matched_skills | 匹配的技能列表 |
| missing_skills | 缺失的技能列表 |
| matched_experience | 匹配的经验摘要 |
| score_breakdown | 各维度评分拆解 |

目的: HR 可以直接将推荐理由转述给业务部门，无需额外解释。

---

## 三、审计日志需求

### NFR-05: Audit Log

每次用户交互必须记录以下信息：

| 字段 | 说明 |
|------|------|
| timestamp | 交互时间 |
| user_id | 用户标识 |
| conversation_id | 会话 ID |
| user_query | 用户原始输入 |
| intent | 识别的意图 |
| slots | 提取的 Slots |
| retrieved_candidates | 召回的候选人 ID 列表 |
| final_recommendations | 最终推荐的候选人 ID 列表 |
| prompt | 发送给 LLM 的 Prompt（用于 Debug） |
| llm_output | LLM 原始输出 |
| latency_ms | 端到端耗时 |
| llm_tokens | 消耗的 Token 数 |
| error | 错误信息（如有） |

**约束**：
- Audit Log 中不记录 PII 明文（手机号、邮箱等）
- 日志保留期: 至少 180 天
- 支持按 user_id / conversation_id / 时间范围查询

---

## 四、安全需求

### NFR-06: API 认证

- 所有 API 接口必须认证（JWT / API Key）
- 支持基于角色的访问控制（RBAC）
- 角色划分: admin（管理员）、hr（HR 用户）、viewer（只读）

### NFR-07: PII 数据保护

| 数据 | 存储 | 传输 | 展示 |
|------|------|------|------|
| 手机号 | AES 加密 | HTTPS | 脱敏（138****1234） |
| 邮箱 | AES 加密 | HTTPS | 脱敏（zhang***@gmail.com） |
| 身份证号 | AES 加密 | HTTPS | 默认不返回 |
| 简历原文 | 明文存储 | HTTPS | 权限控制 |

### NFR-08: 操作审计

- 所有敏感操作必须记录: 简历删除、批量导入、权限变更
- 操作日志包含: 操作人、操作类型、操作对象、操作时间、操作结果

---

## 五、评估指标

### NFR-09: RAG 质量评估

系统上线后需定期评估以下指标：

| 指标 | 目标 | 评估方式 |
|------|------|----------|
| Recall@10 | >=0.85 | Top-10 结果中包含相关候选人的比例 |
| MRR (Mean Reciprocal Rank) | >=0.7 | 第一个相关结果的排名倒数均值 |
| NDCG@10 | >=0.75 | 排序质量评估 |
| Faithfulness | >=0.9 | 推荐理由与简历内容的一致性 |
| Answer Relevancy | >=0.85 | 推荐结果与查询的相关性 |

### NFR-10: 业务指标

| 指标 | 目标 | 数据来源 |
|------|------|----------|
| Top-10 采纳率 | >=80% | HR 反馈 |
| 首轮筛选时间 | 减少70% | 时间对比 |
| 意图识别准确率 | >=90% | Audit Log 分析 |
| Fallback 率 | <=5% | Audit Log 统计 |

---

## 六、可用性需求

### NFR-11: 系统可用性

| 指标 | 目标 |
|------|------|
| SLA | 99.5%（每月宕机 <=3.6 小时） |
| 故障恢复时间 | <=30 分钟 |
| 数据备份 | 每日增量备份，每周全量备份 |

### NFR-12: 降级策略

当 LLM 服务不可用时：
- 降级为纯向量检索 + 关键词检索，跳过 LLM Rerank
- 推荐理由使用模板化生成，而非 LLM 生成
- 告警通知运维团队

---

## 七、部署需求

### NFR-13: 部署方式

- V1 采用单企业内部部署（On-Premise）
- 支持 Docker Compose 部署（开发/测试环境）
- 支持 Kubernetes 部署（生产环境）
- 配置与代码分离，支持环境变量覆盖

### NFR-14: 可观测性

- 日志: 结构化 JSON 日志，支持 ELK 收集
- 指标: Prometheus Metrics（QPS、延迟、Token 消耗、错误率）
- 链路追踪: OpenTelemetry（可选，V2 实现）

---

## 八、兼容性需求

### NFR-15: LLM 可替换

- LLM 调用层抽象为统一接口
- 支持快速切换: OpenAI GPT-4 / Claude / 开源模型（Qwen / DeepSeek）
- 切换 LLM 时不需要修改业务代码

### NFR-16: 向量库可替换

- 向量检索层抽象为统一接口
- V1 使用 Milvus，未来可切换为 Qdrant / Weaviate / Pinecone

---

