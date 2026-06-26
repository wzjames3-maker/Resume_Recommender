<!-- Module: recommendation-engine -->
<!-- Spec Layer: 08 - Dependencies -->
<!-- Phase: Phase 4 - Spec Writing -->
<!-- Project: 企业智能招聘 RAG 推荐系统 -->
<!-- Date: 2026-06-23 -->

# 模块依赖关系：Recommendation Engine

## 依赖总览

```
                    ┌──────────────┐
                    │  api-layer   │ (后置依赖：封装为 HTTP API)
                    └──────┬───────┘
                           │ 调用
                           ▼
              ┌────────────────────────┐
              │  recommendation-engine │ (本模块)
              └────────────────────────┘
                    │         │         │
          ┌─────────┘         │         └─────────┐
          ▼                   ▼                    ▼
  ┌──────────────┐   ┌──────────────┐    ┌──────────────┐
  │ resume-store │   │ vector-index │    │ intent-router │
  │ (前置依赖)    │   │ (前置依赖)    │    │ (前置依赖)    │
  └──────────────┘   └──────────────┘    └──────────────┘
          │                   │
          ▼                   ▼
  ┌──────────────┐   ┌──────────────┐
  │   MongoDB    │   │    Milvus    │
  └──────────────┘   └──────────────┘
```

---

## 前置依赖（本模块依赖的模块）

### 1. resume-store

**依赖类型**: 数据依赖（强依赖）
**依赖方式**: 函数调用
**用途**: 获取候选人简历数据，用于 Metadata Filter 和推荐理由生成

#### 依赖的具体接口

| 接口 | 调用时机 | 说明 |
|------|----------|------|
| `get_resume(resume_id)` | 推荐理由生成（REQ-008） | 获取完整简历数据 |
| `get_resume_metadata(resume_ids)` | Metadata Filter（REQ-004） | 批量获取 city/education/experience 等结构化字段 |
| `get_resume_summary(resume_id)` | Rerank（REQ-006） | 获取简历文本摘要，作为 Reranker 输入 |

#### 依赖的 Schema

```python
# resume-store 提供的 Resume 结构（简化）
class Resume:
    resume_id: str
    candidate_id: str
    name: str
    gender: str
    age: int
    city: str
    education: list[Education]       # 学历列表
    experience: list[Experience]     # 工作经历列表
    projects: list[Project]          # 项目经历列表
    skills: list[Skill]              # 技能列表
    total_experience: float          # 总工作年限
    summary: str                     # 简历摘要
    current_company: str
    current_title: str
    job_type: str                    # 用工形式
    industry: str                    # 行业
```

#### 降级策略

- resume-store 不可用时，无法生成推荐理由 → 使用模板化理由
- resume-store 响应慢时，批量查询改为单条查询（牺牲性能保功能）

---

### 2. vector-index

**依赖类型**: 数据依赖（强依赖）
**依赖方式**: 通过 pymilvus 直接操作 Milvus
**用途**: Dense + Sparse 向量检索

#### 依赖的具体接口

| 接口 | 调用时机 | 说明 |
|------|----------|------|
| Milvus Collection.search (Dense) | Hybrid Retrieval（REQ-001） | Dense 向量相似度检索 |
| Milvus Collection.search (Sparse) | Hybrid Retrieval（REQ-002） | Sparse 向量检索 |
| Milvus Collection.hybrid_search | Hybrid Retrieval（REQ-003） | 原生 Hybrid Search（如可用） |

#### 依赖的数据结构

```python
# Milvus Collection Schema（由 vector-index 创建和维护）
# recommendation-engine 只读取，不写入

fields = [
    FieldSchema("id", DataType.INT64, is_primary=True),
    FieldSchema("resume_id", DataType.VARCHAR, max_length=64),
    FieldSchema("candidate_id", DataType.VARCHAR, max_length=64),
    FieldSchema("dense_vector", DataType.FLOAT_VECTOR, dim=1024),
    FieldSchema("sparse_vector", DataType.SPARSE_FLOAT_VECTOR),
    FieldSchema("metadata", DataType.JSON),  # city, education, experience, ...
]
```

#### 依赖配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| Milvus 地址 | MILVUS_HOST | milvus | Docker 服务名 |
| Milvus 端口 | MILVUS_PORT | 19530 | 默认端口 |
| Collection 名 | MILVUS_COLLECTION | resumes | 向量集合名 |
| 连接超时 | MILVUS_CONNECT_TIMEOUT | 5.0 | 秒 |
| 查询超时 | MILVUS_SEARCH_TIMEOUT | 10.0 | 秒 |

#### 降级策略

- Milvus 不可用 → 致命错误，返回 `RETRIEVAL_TIMEOUT`，无法降级

---

### 3. intent-router

**依赖类型**: 数据依赖（弱依赖）
**依赖方式**: 通过 Slots 字典传递（非直接函数调用）
**用途**: 提供结构化的查询参数（Slots），作为推荐引擎的输入

#### 依赖的具体数据

```python
# intent-router 输出的 Slots 格式
slots = {
    "job_title": str,           # 期望岗位
    "skills": list[str],        # 要求技能
    "experience": float,        # 要求年限
    "experience_op": str,       # 年限比较符: >=, <=, ==, between
    "education": str,           # 最低学历
    "city": str,                # 城市
    "gender": str,              # 性别
    "industry": str,            # 行业
    "company": str,             # 公司
    "job_type": str,            # 用工形式
    "count": int,               # 推荐数量
    "exclude": list[str],       # 排除条件
}
```

#### 依赖方式

- **非直接调用**: intent-router 将 Slots 传给 API Layer，API Layer 再调用 `search_candidates(slots, ...)`
- **松耦合**: recommendation-engine 只关心 Slots 字典结构，不关心 intent-router 的内部实现

#### 降级策略

- Slots 缺失部分字段 → 使用默认值（如 count 默认 10）
- Slots 为空 → 抛出 ValueError

---

## 后置依赖（依赖本模块的模块）

### 4. api-layer

**依赖类型**: 调用依赖
**依赖方式**: 直接 import 调用
**用途**: 将推荐引擎的能力封装为 HTTP API 接口

#### 被调用的接口

| 接口 | 对应 HTTP 端点 | 说明 |
|------|---------------|------|
| `search_candidates()` | `POST /api/v1/search` | recruitment.search 端到端推荐 |
| `hybrid_retrieve()` | 内部（Refine 时复用） | recruitment.refine 的检索子流程 |
| `apply_filters()` | 内部（Refine 时复用） | recruitment.refine 的过滤子流程 |
| `resolve_weights()` | 内部 | 权重解析 |

#### 数据流

```
HTTP Request → api-layer → search_candidates(slots, ...) → RankingResult → HTTP Response
```

---

## 外部服务依赖（非模块）

### 5. BGE-M3 云端 API

**依赖类型**: 外部 API（强依赖）
**用途**: 查询向量生成（Dense + Sparse）
**降级**: 参见 EC-005

| 配置项 | 环境变量 |
|--------|----------|
| API URL | BGE_M3_API_URL |
| API Key | BGE_M3_API_KEY |
| 模型名 | BGE_M3_MODEL |

---

### 6. BGE Reranker v2 M3 云端 API

**依赖类型**: 外部 API（弱依赖，可降级）
**用途**: 候选精细化重排序
**降级**: 超时/错误时跳过 Rerank，使用 hybrid_score（EC-002）

| 配置项 | 环境变量 |
|--------|----------|
| API URL | RERANKER_API_URL |
| API Key | RERANKER_API_KEY |
| 模型名 | RERANKER_MODEL |

---

### 7. LLM API（DeepSeek / OpenAI）

**依赖类型**: 外部 API（弱依赖，可降级）
**用途**: 推荐理由生成
**降级**: 超时/错误时使用模板化理由（REQ-012）

| 配置项 | 环境变量 |
|--------|----------|
| API URL | LLM_API_URL |
| API Key | LLM_API_KEY |
| 主模型 | LLM_MODEL |
| 备用模型 | LLM_FALLBACK_MODEL |

---

## 依赖矩阵

| 依赖 | 类型 | 强度 | 可降级 | 降级策略 |
|------|------|------|--------|----------|
| resume-store | 内部模块 | 强 | 部分 | 理由生成降级为模板 |
| vector-index (Milvus) | 内部模块 | 强 | 否 | 致命错误 |
| intent-router | 内部模块 | 弱 | 否 | Slots 缺失用默认值 |
| BGE-M3 API | 外部服务 | 强 | 是 | 降级到纯 Sparse 或缓存 |
| BGE Reranker API | 外部服务 | 弱 | 是 | 降级到 hybrid_score |
| LLM API | 外部服务 | 弱 | 是 | 降级到模板化理由 |
| api-layer | 内部模块 | - | - | 本模块不依赖 api-layer |

---

## 初始化依赖顺序

```
1. 配置加载（环境变量、weight_presets.yaml）
2. Milvus 连接建立（vector-index）
3. MongoDB 连接建立（resume-store）
4. Embedding 缓存初始化（cachetools TTLCache）
5. API 连接验证（BGE-M3, Reranker, LLM）
6. recommendation-engine 就绪
```

---

## 依赖版本锁定

```requirements.txt
# 本模块核心依赖（精确到主版本号）
pymilvus>=2.5,<3.0
openai>=1.0,<2.0
pydantic>=2.0,<3.0
cachetools>=5.5,<6.0
httpx>=0.28,<1.0
python-json-logger>=3.2,<4.0
pyyaml>=6.0,<7.0
```
