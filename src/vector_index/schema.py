"""
智能招聘 RAG 推荐系统 - Milvus Collection Schema 定义

变更 (Tier L): 添加标量字段支持 Milvus expr 预过滤
- years_of_experience (INT64): 工作年限
- highest_education_level (INT8): 最高学历等级 0=未知 1=大专 2=本科 3=硕士 4=博士
- city (VARCHAR): 所在城市
- gender (VARCHAR): 性别
"""

from pymilvus import CollectionSchema, FieldSchema, DataType

COLLECTION_NAME = "resume_chunks"
DENSE_DIMENSION = 1024

CHUNK_ID_MAX_LENGTH = 64
RESUME_ID_MAX_LENGTH = 64
CHUNK_LEVEL_MAX_LENGTH = 16
PARENT_CHUNK_ID_MAX_LENGTH = 64
SECTION_TYPE_MAX_LENGTH = 32
CITY_MAX_LENGTH = 64
GENDER_MAX_LENGTH = 8
CONTENT_MAX_LENGTH = 65535

CHUNK_LEVELS = ["small", "parent", "full"]
SECTION_TYPES = ["education", "experience", "project", "skill", "other"]

DENSE_INDEX_PARAMS = {
    "metric_type": "COSINE",
    "index_type": "HNSW",
    "params": {"efConstruction": 256, "M": 16},
}

SPARSE_INDEX_PARAMS = {
    "metric_type": "IP",
    "index_type": "SPARSE_INVERTED_INDEX",
    "params": {},
}

HYBRID_SEARCH_PARAMS = {
    "dense": {"metric_type": "COSINE", "params": {"ef": 128}},
    "sparse": {"metric_type": "IP", "params": {}},
}

RRF_K = 60


def get_collection_schema() -> CollectionSchema:
    """获取 Milvus Collection Schema（含标量字段）"""
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=CHUNK_ID_MAX_LENGTH),
        FieldSchema(name="resume_id", dtype=DataType.VARCHAR, max_length=RESUME_ID_MAX_LENGTH),
        FieldSchema(name="chunk_level", dtype=DataType.VARCHAR, max_length=CHUNK_LEVEL_MAX_LENGTH),
        FieldSchema(name="parent_chunk_id", dtype=DataType.VARCHAR, max_length=PARENT_CHUNK_ID_MAX_LENGTH),
        FieldSchema(name="section_type", dtype=DataType.VARCHAR, max_length=SECTION_TYPE_MAX_LENGTH),

        # 标量字段 — 支持 Milvus expr 预过滤
        FieldSchema(name="years_of_experience", dtype=DataType.INT64),
        FieldSchema(name="highest_education_level", dtype=DataType.INT8),
        FieldSchema(name="city", dtype=DataType.VARCHAR, max_length=CITY_MAX_LENGTH),
        FieldSchema(name="gender", dtype=DataType.VARCHAR, max_length=GENDER_MAX_LENGTH),

        # 向量字段
        FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=DENSE_DIMENSION),
        FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),

        # 内容字段
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=CONTENT_MAX_LENGTH),
        FieldSchema(name="metadata", dtype=DataType.JSON),
    ]
    return CollectionSchema(
        fields=fields,
        description="简历多粒度 Chunk 向量索引（含标量字段预过滤）",
        enable_dynamic_field=False,
    )


def get_collection_name() -> str:
    """获取 Collection 名称"""
    from src.common.config import get_settings
    settings = get_settings()
    prefix = settings.milvus.MILVUS_COLLECTION_PREFIX
    return f"{prefix}chunks"
