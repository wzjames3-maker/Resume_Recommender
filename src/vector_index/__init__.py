# 向量索引模块
"""
负责简历向量的索引和检索（Milvus）
支持：Dense + Sparse 双模态向量、Hybrid Search

变更 (Tier L): FlagEmbedding 本地推理替代 SiliconFlow API
"""

from src.vector_index.embedding_generator import (
    EmbeddingGenerator,
    EmbeddingResult,
    get_embedding_generator,
)
from src.vector_index.index import VectorIndex, get_vector_index
from src.vector_index.vector_writer import VectorWriter, get_vector_writer

__version__ = "0.2.0"

__all__ = [
    "EmbeddingGenerator",
    "EmbeddingResult",
    "get_embedding_generator",
    "VectorIndex",
    "get_vector_index",
    "VectorWriter",
    "get_vector_writer",
]
