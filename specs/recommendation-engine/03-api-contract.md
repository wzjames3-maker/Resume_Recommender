<!-- Module: recommendation-engine -->
<!-- Spec Layer: 03 - API Contract -->
<!-- ⚠️ 部分更新: FlagEmbedding/BGE-M3 引用已修正，核心内容仍为旧架构流程，待 Tier L 全文重构 -->

# 内部接口契约：Recommendation Engine

## 概述

本模块的所有接口均为**内部函数调用接口**，不对外暴露 HTTP 端点。由 API Layer 通过直接 import 调用。所有接口同步返回（非 Streaming），Streaming 由 API Layer 负责。

---

## 接口总览

| 接口 | 入口函数 | 说明 | 调用者 |
|------|----------|------|--------|
| search_candidates | `search_candidates()` | 端到端推荐主流程 | api-layer |
| hybrid_retrieve | `hybrid_retrieve()` | Hybrid Retrieval 子流程 | 内部 / api-layer（Refine） |
| apply_filters | `apply_filters()` | Metadata Filter 子流程 | 内部 / api-layer（Refine） |
| rerank | `rerank()` | LLM Rerank 子流程 | 内部 |
| generate_reason | `generate_reason()` | 推荐理由生成子流程 | 内部 |
| resolve_weights | `resolve_weights()` | 权重配置解析 | 内部 / api-layer |

---

## 1. search_candidates

**用途**: 端到端推荐主流程，串联所有子流程。
**对应需求**: REQ-001 ~ REQ-012（全链路）

### 函数签名

```python
def search_candidates(
    slots: dict,
    weight_config: Optional[WeightConfig] = None,
    top_k: int = 50,
    count: int = 10,
) -> SearchCandidatesResult:
    """
    端到端候选人推荐。

    Args:
        slots: 从 intent-router 获取的 Slots 字典
            {
                "job_title": str,           # 期望岗位
                "skills": list[str],        # 要求技能
                "experience": float,        # 要求年限
                "experience_op": str,       # 年限比较符
                "education": str,           # 最低学历
                "city": str,                # 城市
                "gender": str,              # 性别
                "industry": str,            # 行业
                "company": str,             # 公司
                "job_type": str,            # 用工形式
                "exclude": list[str],       # 排除条件
                ...                         # 其他 Slots
            }
        weight_config: 排序权重配置，None 时使用默认值或岗位预设值
        top_k: Hybrid Retrieval 初始召回数量，默认 50
        count: 最终返回的推荐数量，默认 10

    Returns:
        SearchCandidatesResult:
            {
                "recommendations": list[RankingResult],  # 推荐列表（最多 count 条）
                "total_candidates": int,                  # 过滤后候选总数
                "degradation": Optional[str],             # 降级标识
                "latency_ms": int,                        # 总耗时（毫秒）
                "token_usage": int,                       # LLM Token 消耗
            }
    """
```

### 处理流程

```
1. slots → query_text（拼接 job_title + skills + 其他关键描述）
2. slots → FilterCriteria（提取结构化过滤条件）
3. resolve_weights(job_title, weight_config) → WeightConfig
4. hybrid_retrieve(query_text, slots, top_k) → candidates
5. apply_filters(candidates, FilterCriteria) → filtered
6. deduplicate(filtered) → deduped
7. rerank(deduped, query_text, slots) → reranked
8. 对每个候选人:
   a. 从 resume-store 获取 Resume 数据
   b. generate_reason(candidate, query_text, slots, score_breakdown) → reason_data
   c. 计算 score_breakdown
   d. 组装 RankingResult
9. 按 final_score 降序排列，取前 count 条，填充 rank
10. 返回 SearchCandidatesResult
```

### 错误处理

| 错误 | 处理 | 错误码 |
|------|------|--------|
| slots 为空或格式错误 | 抛出 ValueError | - |
| Milvus 连接超时 | 返回错误 | RETRIEVAL_TIMEOUT |
| Embedding API 全部失败 | 返回错误 | LLM_ERROR |
| Reranker 超时 | 降级到 hybrid_score | - |
| LLM 生成理由失败 | 降级到模板化理由 | - |

---

## 2. hybrid_retrieve

**用途**: 执行 Hybrid Retrieval（Dense + Sparse + RRF Merge）。
**对应需求**: REQ-001, REQ-002, REQ-003

### 函数签名

```python
def hybrid_retrieve(
    query: str,
    slots: dict,
    top_k: int = 50,
) -> HybridRetrieveResult:
    """
    执行 Hybrid Retrieval。

    Args:
        query: 查询文本（由 Slots 拼接）
        slots: Slots 字典（用于查询文本构建和软匹配参考）
        top_k: 合并后保留数量，默认 50

    Returns:
        HybridRetrieveResult:
            {
                "candidates": list[RetrievalResult],
                "dense_latency_ms": int,
                "sparse_latency_ms": int,
                "merge_latency_ms": int,
                "degradation": Optional[str],
            }
    """
```

### 处理流程

```
1. query_encode(query) → (dense_vector, sparse_vector)
   - 检查 cachetools 缓存
   - 缓存未命中 → 调用 FlagEmbedding 本地推理
   - API 失败 → 按 REQ-012 降级
2. dense_retrieve(dense_vector, top_k) → dense_results
   - Milvus search, metric_type=COSINE
3. sparse_retrieve(sparse_vector, top_k) → sparse_results
   - Milvus search, sparse 字段
4. hybrid_merge(dense_results, sparse_results, rrf_k=60, top_k) → merged
   - RRF 算法合并
5. 返回 HybridRetrieveResult
```

### Milvus 查询参数

```python
# Dense 查询
dense_search_params = {
    "metric_type": "COSINE",
    "params": {"ef": 128},  # HNSW 搜索参数
}

# Sparse 查询
sparse_search_params = {
    "metric_type": "BM25",  # 或 IP，取决于 Milvus 配置
    "params": {},
}
```

### 缓存策略

```python
from cachetools import TTLCache

# Embedding 缓存：最多 1000 条，TTL 10 分钟
embedding_cache = TTLCache(maxsize=1000, ttl=600)

def query_encode(query: str) -> tuple[list[float], dict]:
    cache_key = f"embed:{hash(query)}"
    if cache_key in embedding_cache:
        return embedding_cache[cache_key]
    result = bge_m3_api.encode(query)
    embedding_cache[cache_key] = result
    return result
```

---

## 3. apply_filters

**用途**: 对候选列表应用 Metadata Filter 和 Soft Match。
**对应需求**: REQ-004, REQ-005, REQ-010

### 函数签名

```python
def apply_filters(
    candidates: list[RetrievalResult],
    filters: FilterCriteria,
    skill_synonyms: Optional[dict[str, list[str]]] = None,
) -> FilterResult:
    """
    应用 Metadata Filter。

    Args:
        candidates: 候选列表
        filters: 过滤条件
        skill_synonyms: 技能近义词映射表，None 时从 resume-parser 获取

    Returns:
        FilterResult:
            {
                "filtered": list[RetrievalResult],
                "removed_count": int,
                "relaxed_filters": list[str],  # 被放宽的过滤条件（EC-001）
            }
    """
```

### 处理流程

```
1. 对每个候选人，从 resume-store 获取 metadata（city, education, experience, gender, ...）
2. 逐项检查硬约束:
   - city: 精确匹配
   - education: 向上兼容（EDUCATION_HIERARCHY）
   - experience: 数值比较 + 浮动（±20%）
   - gender: 精确匹配
   - exclude_job_type: 排除列表
3. 对 skills 做 Soft Match:
   - 精确匹配 → matched
   - 近义词匹配（skill_synonyms）→ matched（标注来源）
   - 都不匹配 → missing
4. 过滤后为空 → 尝试放宽约束重试（EC-001）
5. 返回 FilterResult
```

### 学历等级比较

```python
EDUCATION_HIERARCHY = {
    "高中": 1, "大专": 2, "本科": 3, "硕士": 4, "博士": 5,
}

def education_meets_requirement(candidate_edu: str, required_edu: str) -> bool:
    """向上兼容：候选学历 >= 要求学历"""
    return EDUCATION_HIERARCHY.get(candidate_edu, 0) >= EDUCATION_HIERARCHY.get(required_edu, 0)
```

---

## 4. rerank

**用途**: 使用 BGE Reranker v2 M3 对候选进行精细化重排序。
**对应需求**: REQ-006

### 函数签名

```python
def rerank(
    candidates: list[RetrievalResult],
    query: str,
    slots: dict,
    timeout: float = 3.0,
) -> RerankResult:
    """
    执行 LLM Rerank。

    Args:
        candidates: 过滤后的候选列表
        query: 原始查询文本
        slots: Slots 字典
        timeout: API 超时阈值（秒），默认 3.0

    Returns:
        RerankResult:
            {
                "ranked": list[RetrievalResult],  # metadata.rerank_score 已填充
                "latency_ms": int,
                "degradation": Optional[str],
            }
    """
```

### 处理流程

```
1. 构造 Reranker 输入: [(query, candidate.resume_summary) for candidate in candidates]
2. 调用 BGE Reranker v2 M3 API
   - POST /rerank
   - 输入: {"query": str, "documents": list[str]}
   - 输出: [{"index": int, "score": float}, ...]
3. API 超时（>3s）→ 降级到 hybrid_score（EC-002）
4. API 错误 → 降级到 hybrid_score（EC-002）
5. 将 rerank_score 写入 RetrievalResult.metadata.rerank_score
6. 按 rerank_score 降序排列
7. 返回 RerankResult
```

### API 调用格式

```python
# BGE Reranker v2 M3 API（OpenAI Compatible）
async def call_reranker(query: str, documents: list[str], timeout: float) -> list[dict]:
    """
    POST https://api.siliconflow.cn/v1/rerank
    {
        "model": "BAAI/bge-reranker-v2-m3",
        "query": "5年Java工程师",
        "documents": ["简历摘要1", "简历摘要2", ...],
        "top_n": 100,
        "return_documents": false
    }

    Response:
    {
        "results": [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.87},
            ...
        ]
    }
    """
```

### 降级行为

```python
async def rerank_with_fallback(candidates, query, slots, timeout):
    try:
        result = await call_reranker(query, documents, timeout)
        # 正常流程
    except (TimeoutError, APIError):
        # 降级: 按 hybrid_score 排序
        for c in candidates:
            c.metadata.rerank_score = None  # 标记未 Rerank
        candidates.sort(key=lambda c: c.hybrid_score, reverse=True)
        return RerankResult(ranked=candidates, degradation="reranker_fallback")
```

---

## 5. generate_reason

**用途**: 使用 LLM 生成推荐理由、匹配技能和缺失技能。
**对应需求**: REQ-008

### 函数签名

```python
def generate_reason(
    candidate: "Resume",
    query: str,
    slots: dict,
    score_breakdown: ScoreBreakdown,
    timeout: float = 5.0,
) -> ReasonResult:
    """
    生成推荐理由。

    Args:
        candidate: 候选人完整简历数据（从 resume-store 获取）
        query: 原始查询文本
        slots: Slots 字典
        score_breakdown: 各维度评分
        timeout: LLM 调用超时（秒），默认 5.0

    Returns:
        ReasonResult:
            {
                "reason": list[str],          # 至少 2 条
                "matched_skills": list[str],
                "missing_skills": list[str],
                "token_usage": int,
                "degradation": Optional[str],
            }
    """
```

### 处理流程

```
1. 构造 LLM Prompt:
   - System: 角色定义 + Faithfulness 约束
   - User: 查询需求 + Slots + 候选人简历摘要 + score_breakdown
2. 调用 LLM API（DeepSeek 主，OpenAI 备）
   - 使用 Structured Output（Pydantic Schema 约束输出格式）
3. 解析 LLM 输出为 ReasonResult
4. 校验:
   - reason 列表长度 >= 2
   - matched_skills 中的技能在候选人简历中存在
   - missing_skills 中的技能在 Slots 中存在
5. 校验失败 → 补充/修正
6. LLM 超时 → 降级为模板化理由（EC-003 场景的预防）
7. 返回 ReasonResult
```

### LLM Prompt 模板

```python
SYSTEM_PROMPT = """你是一个专业的招聘推荐分析师。你的任务是根据候选人的简历和招聘需求，生成推荐理由。

**严格约束**：
1. 推荐理由必须基于简历原文中的具体信息，禁止编造
2. 每条理由必须引用简历中的具体事实（如工作年限、公司名、项目名、技能名）
3. 输出必须为 JSON 格式，符合给定的 Schema

**输出格式**：
{
    "reason": ["理由1（引用简历事实）", "理由2（引用简历事实）", ...],
    "matched_skills": ["技能1", "技能2", ...],
    "missing_skills": ["缺失技能1", ...]
}"""

USER_PROMPT = """
## 招聘需求
{query}

## 结构化条件
{slots_json}

## 候选人简历摘要
{candidate_summary}

## 各维度评分
技能匹配: {skill_score}/100
经验匹配: {experience_score}/100
项目相关性: {project_score}/100
行业匹配: {industry_score}/100
教育匹配: {education_score}/100

请生成推荐理由（至少 2 条）、匹配技能列表和缺失技能列表。
"""
```

### 降级行为（模板化理由）

```python
def generate_template_reason(
    candidate: "Resume",
    slots: dict,
    score_breakdown: ScoreBreakdown,
) -> ReasonResult:
    """LLM 不可用时的模板化理由"""
    reasons = []

    # 技能匹配
    matched = [s for s in slots.get("skills", []) if s in candidate.skills]
    if matched:
        reasons.append(f"具备要求的技能：{', '.join(matched)}")

    # 经验匹配
    if candidate.total_experience >= slots.get("experience", 0):
        reasons.append(f"拥有 {candidate.total_experience} 年相关经验，满足 {slots['experience']} 年要求")

    # 最高分维度
    top_dim = max(score_breakdown.model_dump(), key=score_breakdown.model_dump().get)
    dim_names = {
        "skill_match": "技能", "experience_match": "经验",
        "project_relevance": "项目", "industry_match": "行业",
        "education_match": "教育",
    }
    reasons.append(f"{dim_names[top_dim]}维度表现突出（{getattr(score_breakdown, top_dim):.0f}分）")

    return ReasonResult(
        reason=reasons[:3],
        matched_skills=matched,
        missing_skills=[s for s in slots.get("skills", []) if s not in candidate.skills],
        degradation="llm_fallback",
    )
```

---

## 6. resolve_weights

**用途**: 解析和确定最终生效的排序权重配置。
**对应需求**: REQ-011

### 函数签名

```python
def resolve_weights(
    job_title: Optional[str] = None,
    weight_config: Optional[WeightConfig] = None,
) -> WeightConfig:
    """
    解析权重配置。

    Args:
        job_title: 岗位名称，用于查找预设权重
        weight_config: 直接传入的权重配置（优先级最高）

    Returns:
        WeightConfig: 生效的权重配置
    """
```

### 优先级

```
weight_config 参数（显式传入）
  ↓ 未传入
岗位预设权重（config/weight_presets.yaml 中按 job_title 查找）
  ↓ 未找到
默认权重（WeightConfig() → 技能40/经验25/项目20/行业10/教育5）
```

### 岗位预设权重配置文件

```yaml
# config/weight_presets.yaml
presets:
  "算法工程师":
    skill_weight: 0.30
    experience_weight: 0.20
    project_weight: 0.20
    industry_weight: 0.10
    education_weight: 0.20   # 算法岗教育权重更高
  "产品经理":
    skill_weight: 0.25
    experience_weight: 0.30  # 产品经理更看重经验
    project_weight: 0.25
    industry_weight: 0.15
    education_weight: 0.05
```

---

## 模块外调用接口（本模块调用其他模块）

### 调用 vector-index

```python
# 通过 pymilvus 直接操作 Milvus
from pymilvus import Collection

def milvus_search(
    collection_name: str,
    dense_vector: list[float],
    sparse_vector: dict[int, float],
    top_k: int,
) -> list[dict]:
    """
    向 Milvus 发起混合检索。

    对应模块: vector-index
    注意: vector-index 负责 Collection 的创建和数据写入，
          recommendation-engine 负责读取（search）。
    """
```

### 调用 resume-store

```python
def get_resume(resume_id: str) -> Optional[Resume]:
    """获取完整简历数据。对应模块: resume-store"""

def get_resume_metadata(resume_ids: list[str]) -> dict[str, dict]:
    """批量获取简历元数据（city, education, experience, ...）。对应模块: resume-store"""

def get_resume_summary(resume_id: str) -> str:
    """获取简历摘要文本（用于 Reranker 输入）。对应模块: resume-store"""
```

### 调用 FlagEmbedding 本地推理

```python
def encode_query(query: str) -> tuple[list[float], dict[int, float]]:
    """
    调用 FlagEmbedding BGEM3FlagModel，同时获取 Dense 和 Sparse 向量。

    API Endpoint: https://api.siliconflow.cn/v1/embeddings
    Model: BAAI/bge-m3
    """
```

### 调用 BGE Reranker API

```python
def call_reranker(query: str, documents: list[str]) -> list[dict]:
    """
    调用 BGE Reranker v2 M3 云端 API。

    API Endpoint: https://api.siliconflow.cn/v1/rerank
    Model: BAAI/bge-reranker-v2-m3
    """
```

### 调用 LLM API

```python
def call_llm(system_prompt: str, user_prompt: str, schema: type) -> dict:
    """
    调用 LLM（DeepSeek/OpenAI）生成结构化输出。

    API: OpenAI Compatible API
    Model: deepseek-chat (主) / gpt-4o-mini (备)
    Output: Structured Output（Pydantic Schema 约束）
    """
```
