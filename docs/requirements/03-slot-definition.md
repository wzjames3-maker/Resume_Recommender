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
