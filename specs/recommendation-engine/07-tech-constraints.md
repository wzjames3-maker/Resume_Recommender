<!-- Module: recommendation-engine -->
<!-- Spec Layer: 07 - Tech Constraints -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 技术约束：Recommendation Engine

## 决策来源

本模块的技术约束引用并遵循 `docs/tech-decision.md`（冻结版）的决策。

---

## 1. 核心依赖版本

| 组件 | 包名 | 最低版本 | 用途 |
|------|------|----------|------|
| 向量数据库客户端 | pymilvus | >=2.4.6,<2.5 | Milvus Dense + Sparse Hybrid Search |
| Embedding 模型 | FlagEmbedding BGEM3FlagModel | BAAI/bge-m3 | 本地推理查询 Dense + Sparse 向量 |
| Reranker 模型 | BGE Reranker v2 M3（云端 API） | 专用 Rerank API | 候选精细化重排序 |
| LLM | DeepSeek / OpenAI | OpenAI Compatible API | 推荐理由生成 |
| LLM SDK | openai | >= 1.0 | OpenAI Compatible API 调用 |
| 数据验证 | pydantic | >= 2.0 | Schema 定义与输出约束 |
| 缓存 | cachetools | >= 5.3 | Embedding 结果双层缓存（L1 本地 + L2 Redis） |
| 日志 | python-json-logger | >= 3.2 | 结构化 JSON 日志 |

---

## 2. Embedding 模型约束

### FlagEmbedding 本地推理（替代 BGE-M3 云端 API）

> **决策**: 因 SiliconFlow `/v1/embeddings` 不返回 sparse 向量，改用 FlagEmbedding BGEM3FlagModel 本地推理。

| 约束 | 值 | 说明 |
|------|-----|------|
| 模型 | `BAAI/bge-m3` | HuggingFace 自动下载，首次 ~2GB |
| 输出维度（Dense） | 1024 | 固定 |
| 输出格式（Sparse） | dict[int, float] | `lexical_weights`: token_id → weight |
| 推理模式 | CPU（use_fp16=False） | 兼容无 GPU 环境 |
| 模型实例 | 懒加载 + 单例 | 复用同一模型，避免重复加载 |
| Batch size | 32 | 批量 encode 时每批大小 |
| 推理延迟（单条） | P95 <= 200ms | CPU 模式 |
| 缓存 | L1 cachetools TTL 1h + L2 Redis TTL 24h | 减少重复推理

### FlagEmbedding 调用格式

```python
from FlagEmbedding import BGEM3FlagModel

model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=False)
output = model.encode(
    ["查询文本"],
    return_dense=True,
    return_sparse=True,
    return_colbert_vecs=False,
    batch_size=32,
)
# output['dense_vecs'] -> np.ndarray [1, 1024]
# output['lexical_weights'] -> list[dict[int, float]]
```

### 缓存策略

```python
# L1: cachetools 进程内缓存，TTL 1h，maxsize=10000
from cachetools import TTLCache
embedding_cache_l1 = TTLCache(maxsize=10000, ttl=3600)

# L2: Redis 分布式缓存，TTL 24h
# key = f"emb:{hash(text)}"
# value = json.dumps({"dense": dense_list, "sparse": {"tok_id": val, ...}})
```

---

## 3. Reranker 模型约束

### BGE Reranker v2 M3 云端 API

| 约束 | 值 | 说明 |
|------|-----|------|
| API 格式 | 专用 Rerank API | `POST /v1/rerank` |
| 模型名 | `BAAI/bge-reranker-v2-m3` | 硬编码 |
| 输入格式 | (query, documents) 对 | query 为字符串，documents 为字符串列表 |
| 输出格式 | list[{index, relevance_score}] | relevance_score 范围 0~1 |
| 最大 documents 数 | 100 | 超过需分批 |
| 最大输入长度 | 512 tokens per document | 超长需截断 |
| 超时阈值 | 3 秒 | 超时降级（EC-002） |

### API 调用格式

```python
POST https://api.siliconflow.cn/v1/rerank
{
    "model": "BAAI/bge-reranker-v2-m3",
    "query": "5年Java工程师",
    "documents": ["简历摘要1", "简历摘要2", ...],
    "top_n": 100,
    "return_documents": false
}

# Response
{
    "results": [
        {"index": 0, "relevance_score": 0.95},
        {"index": 1, "relevance_score": 0.87},
        ...
    ],
    "usage": {"prompt_tokens": 500, "total_tokens": 500}
}
```

---

## 4. LLM 约束

### DeepSeek（主）/ OpenAI（备）

| 约束 | 值 | 说明 |
|------|-----|------|
| API 格式 | OpenAI Compatible | `POST /v1/chat/completions` |
| 主模型 | `deepseek-chat` | DeepSeek V3 |
| 备用模型 | `gpt-4o-mini` | OpenAI |
| 输出格式 | Structured Output | Pydantic Schema 约束 |
| 超时阈值 | 5 秒 | 超时降级为模板化理由 |
| 最大输出 tokens | 1024 | 推荐理由不需要太长 |
| Temperature | 0.3 | 偏低，保证理由稳定性 |

### Structured Output Schema

```python
class ReasonOutput(BaseModel):
    """LLM 输出 Schema，用于 Structured Output 约束"""
    reason: list[str] = Field(min_length=2, max_length=5)
    matched_skills: list[str]
    missing_skills: list[str]
```

### 降级链路

```
DeepSeek API → 超时/错误 → OpenAI API → 超时/错误 → 模板化理由
```

---

## 5. 向量数据库约束

### Milvus Standalone

| 约束 | 值 | 说明 |
|------|-----|------|
| 部署方式 | Docker | docker-compose.yml 统一管理 |
| 版本 | Milvus >= 2.5 | 支持 Hybrid Search |
| Collection 数量 | 1 | 所有简历向量在同一个 Collection |
| Dense 索引 | HNSW | metric_type=COSINE |
| Sparse 索引 | SPARSE_INVERTED_INDEX | metric_type=BM25 或 IP |
| 检索参数 ef | 128 | HNSW 搜索精度参数 |
| 连接超时 | 5 秒 | 超时返回 RETRIEVAL_TIMEOUT |
| 查询超时 | 10 秒 | 单次 search 超时 |

### Collection Schema（读取端）

```python
# recommendation-engine 只读取，不写入
# Collection 创建和数据写入由 vector-index 负责

# 需要的字段:
# - id: int64 (primary key)
# - resume_id: varchar
# - candidate_id: varchar
# - dense_vector: float_vector(1024)
# - sparse_vector: SparseFloatVector
# - metadata (JSON): city, education, experience, ...
```

### 混合检索参数

```python
search_params = {
    "anns_field": "dense_vector",
    "param": {"metric_type": "COSINE", "params": {"ef": 128}},
    "limit": top_k,
}

# Milvus Hybrid Search (>= 2.4)
# reqs = [dense_search_req, sparse_search_req]
# collection.hybrid_search(reqs, rerank=RRFRanker(60), limit=top_k)
```

---

## 6. 禁用项

| 禁用 | 原因 |
|------|------|
| Elasticsearch 做主检索 | Milvus 原生 Hybrid Search（Dense + Sparse）已满足需求，无需额外引入 ES |
| SiliconFlow /v1/embeddings API | 不返回 sparse 向量，改用 FlagEmbedding 本地推理 |
| _dense_to_sparse 伪 sparse | 从 dense 派生，提供零增量信息 |
| 空 sparse dict | 导致 hybrid_search 退化为 dense-only |
| ChromaDB | 不支持原生 Hybrid Search |
| Redis 缓存 | V1 单机部署，cachetools 本地缓存足够 |
| Celery 异步队列 | V1 同步处理，不需要消息队列 |

---

## 7. 容器内执行约束

| 约束 | 说明 |
|------|------|
| 所有测试在 Docker 容器内运行 | `docker compose exec app pytest tests/` |
| 所有依赖通过 requirements.txt 管理 | 不依赖宿主机安装的包 |
| 环境变量通过 .env 注入 | API Key、Milvus 地址等 |
| 日志输出到 stdout/stderr | Docker 原生日志收集 |

### 环境变量

```bash
# FlagEmbedding 本地模型
BGE_M3_MODEL_PATH=/models/bge-m3       # 预下载模型路径（可选，默认 HuggingFace 自动下载）
BGE_M3_USE_FP16=false                  # CPU 模式

# Reranker API
RERANKER_API_URL=https://api.siliconflow.cn/v1
RERANKER_API_KEY=sk-xxx
RERANKER_MODEL=BAAI/bge-reranker-v2-m3

# LLM API
LLM_API_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=deepseek-chat
LLM_FALLBACK_MODEL=gpt-4o-mini

# Milvus
MILVUS_HOST=milvus
MILVUS_PORT=19530
MILVUS_COLLECTION=resumes

# 缓存
EMBEDDING_CACHE_MAXSIZE=1000
EMBEDDING_CACHE_TTL=600

# 超时（秒）
RERANKER_TIMEOUT=3.0
LLM_TIMEOUT=5.0
MILVUS_CONNECT_TIMEOUT=5.0
MILVUS_SEARCH_TIMEOUT=10.0
```

---

## 8. Python 依赖清单（本模块专用）

```requirements.txt
# 向量数据库
pymilvus>=2.5

# LLM / Embedding / Reranker API
openai>=1.0
httpx>=0.28

# 数据验证
pydantic>=2.0

# 缓存
cachetools>=5.5

# 日志
python-json-logger>=3.2

# 工具
pyyaml>=6.0           # 读取 weight_presets.yaml
```
