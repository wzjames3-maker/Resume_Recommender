<!-- Module: vector-index -->
<!-- Spec Layer: 07 - Tech Constraints -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 07-tech-constraints: Vector Index

| 类别 | 选择 | 版本 | 理由 |
|------|------|------|------|
| 向量数据库 | Milvus Standalone | v2.4.6 (Docker) | 原生 Hybrid Search + 标量过滤 |
| Python SDK | pymilvus | >=2.4.6,<2.5 | SPARSE_FLOAT_VECTOR + RRFRanker 支持 |
| Dense Embedding | FlagEmbedding BGEM3FlagModel | BAAI/bge-m3 | 原生 dense 1024d，CPU 推理可用 |
| Sparse Embedding | FlagEmbedding BGEM3FlagModel | BAAI/bge-m3 | 原生 lexical_weights，词级权重 |
| L1 本地缓存 | cachetools | >=5.3 | Embedding 热数据，进程内毫秒级读取 |
| L2 分布式缓存 | Redis | >=5.0 | Embedding 结果跨进程共享 |

## 禁用项

| 禁用 | 理由 |
|------|------|
| SiliconFlow /v1/embeddings API | 不返回 sparse 向量，只返回 dense |
| _dense_to_sparse 伪 sparse | 从 dense 派生，提供零增量信息 |
| 空 sparse dict | 导致 hybrid_search 退化为 dense-only |
| ChromaDB | 不支持原生 Hybrid Search |

## FlagEmbedding 配置

```python
from FlagEmbedding import BGEM3FlagModel

# 单例 + 懒加载
_model: BGEM3FlagModel | None = None

def get_model() -> BGEM3FlagModel:
    global _model
    if _model is None:
        _model = BGEM3FlagModel(
            'BAAI/bge-m3',
            use_fp16=False,  # CPU 模式
        )
    return _model

# 生成 dense + sparse
output = model.encode(
    texts,
    return_dense=True,
    return_sparse=True,
    return_colbert_vecs=False,
    batch_size=32,
)
# output['dense_vecs'] -> np.ndarray [N, 1024]
# output['lexical_weights'] -> list[dict[int, float]]
```

## Docker 镜像影响

| 新增依赖 | 镜像大小增加 |
|----------|-------------|
| FlagEmbedding | ~50MB |
| torch (CPU) | ~1.5GB |
| BGE-M3 模型权重 | ~2GB（首次运行时从 HuggingFace 下载，可预下载到 Docker volume） |
