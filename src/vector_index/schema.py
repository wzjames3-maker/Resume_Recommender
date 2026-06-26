"""
智能招聘 RAG 推荐系统 - Milvus Collection Schema 定义

严格对齐 specs/vector-index/00-overview.md 中的 02-data-model
"""

from pymilvus import CollectionSchema, FieldSchema, DataType

# ==================== 常量定义 ====================

# Collection 名称
COLLECTION_NAME = "resume_chunks"

# 向量维度（BGE-M3 固定输出 1024 维）
DENSE_DIMENSION = 1024

# 字段最大长度
CHUNK_ID_MAX_LENGTH = 64
RESUME_ID_MAX_LENGTH = 64
CHUNK_LEVEL_MAX_LENGTH = 16
PARENT_CHUNK_ID_MAX_LENGTH = 64
SECTION_TYPE_MAX_LENGTH = 32
CONTENT_MAX_LENGTH = 65535

# Chunk Level 枚举
CHUNK_LEVELS = ["small", "parent", "full"]

# Section Type 枚举
SECTION_TYPES = ["education", "experience", "project", "skill", "other"]

# 索引参数
DENSE_INDEX_PARAMS = {
    "metric_type": "COSINE",
    "index_type": "HNSW",
    "params": {
        "efConstruction": 256,
        "M": 16,
    },
}

SPARSE_INDEX_PARAMS = {
    "metric_type": "IP",
    "index_type": "SPARSE_INVERTED_INDEX",
    "params": {},
}

# Hybrid Search 参数
HYBRID_SEARCH_PARAMS = {
    "dense": {
        "metric_type": "COSINE",
        "params": {"ef": 128},
    },
    "sparse": {
        "metric_type": "IP",
        "params": {},
    },
}

# RRF 融合参数
RRF_K = 60


# ==================== Schema 定义 ====================

def get_collection_schema() -> CollectionSchema:
    """
    获取 Milvus Collection Schema

    Returns:
        CollectionSchema: Collection Schema 定义
    """
    # 定义字段
    fields = [
        # 主键字段（auto_id）
        FieldSchema(
            name="id",
            dtype=DataType.INT64,
            is_primary=True,
            auto_id=True,
        ),
        # Chunk ID（唯一索引）
        FieldSchema(
            name="chunk_id",
            dtype=DataType.VARCHAR,
            max_length=CHUNK_ID_MAX_LENGTH,
        ),
        # 简历 ID（关联 MongoDB）
        FieldSchema(
            name="resume_id",
            dtype=DataType.VARCHAR,
            max_length=RESUME_ID_MAX_LENGTH,
        ),
        # Chunk 级别
        FieldSchema(
            name="chunk_level",
            dtype=DataType.VARCHAR,
            max_length=CHUNK_LEVEL_MAX_LENGTH,
        ),
        # 父 Chunk ID（Small Chunk 必填）
        FieldSchema(
            name="parent_chunk_id",
            dtype=DataType.VARCHAR,
            max_length=PARENT_CHUNK_ID_MAX_LENGTH,
        ),
        # Section 类型
        FieldSchema(
            name="section_type",
            dtype=DataType.VARCHAR,
            max_length=SECTION_TYPE_MAX_LENGTH,
        ),
        # Dense 向量（BGE-M3, 1024 维）
        FieldSchema(
            name="dense_vector",
            dtype=DataType.FLOAT_VECTOR,
            dim=DENSE_DIMENSION,
        ),
        # Sparse 向量（BGE-M3）
        FieldSchema(
            name="sparse_vector",
            dtype=DataType.SPARSE_FLOAT_VECTOR,
        ),
        # Chunk 文本内容
        FieldSchema(
            name="content",
            dtype=DataType.VARCHAR,
            max_length=CONTENT_MAX_LENGTH,
        ),
        # 元数据（JSON 格式）
        FieldSchema(
            name="metadata",
            dtype=DataType.JSON,
        ),
    ]

    # 创建 Schema
    schema = CollectionSchema(
        fields=fields,
        description="简历多粒度 Chunk 向量索引",
        enable_dynamic_field=False,
    )

    return schema


def get_collection_name() -> str:
    """
    获取 Collection 名称（从配置读取前缀）

    Returns:
        str: Collection 名称
    """
    from src.common.config import get_settings

    settings = get_settings()
    prefix = settings.milvus.MILVUS_COLLECTION_PREFIX

    return f"{prefix}chunks"
