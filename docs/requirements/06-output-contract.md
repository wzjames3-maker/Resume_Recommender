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
