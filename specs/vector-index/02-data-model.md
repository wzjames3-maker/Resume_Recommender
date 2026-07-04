<!-- Module: vector-index -->
<!-- Spec Layer: 02 - Data Model -->
<!-- 变更: Tier L - RAG 全量重构 -->
<!-- Date: 2026-07-03 -->

# 02-data-model: Vector Index

## 1. Milvus Collection Schema

```
Collection: resume_chunks
├── id: INT64 (PK, auto_id)
├── chunk_id: VARCHAR(64)              # 唯一标识，格式: {resume_id}:{level}:{index:04d}
├── resume_id: VARCHAR(64)             # 关联 MongoDB
├── chunk_level: VARCHAR(16)           # "small" / "parent" / "full"
├── parent_chunk_id: VARCHAR(64)       # Small Chunk 的父 Chunk ID
├── section_type: VARCHAR(32)          # "education"/"experience"/"project"/"skill"/"other"
│
│   ── 标量字段（从 ResumeStructured 提取，支持 Milvus expr 预过滤）──
├── years_of_experience: INT64         # 工作年限（从 personal_info 继承）
├── highest_education_level: INT8     # 0=未知 1=大专 2=本科 3=硕士 4=博士
├── city: VARCHAR(64)                  # 所在城市
├── gender: VARCHAR(8)                 # 性别
│
│   ── 向量字段 ──
├── dense_vector: FLOAT_VECTOR(1024)   # BGE-M3 Dense
├── sparse_vector: SPARSE_FLOAT_VECTOR # BGE-M3 Sparse (lexical_weights)
│
│   ── 内容字段 ──
├── content: VARCHAR(65535)            # Chunk 文本内容
└── metadata: JSON                     # 完整元数据（见 §2）
```

## 2. 标量字段映射规则

| Milvus 字段 | 来源 | 类型 | 默认值 | 过滤用途 |
|-------------|------|------|--------|----------|
| years_of_experience | ResumeStructured.personal_info.years_of_experience | INT64 | 0 | experience >= N |
| highest_education_level | 从 education_list 中取最高学历映射 | INT8 | 0 | education_level >= N |
| city | ResumeStructured.personal_info.city | VARCHAR | "" | city == "杭州" |
| gender | ResumeStructured.personal_info.gender | VARCHAR | "" | gender == "男" |

### 学历映射表

| 学历 | level |
|------|-------|
| 未知/空 | 0 |
| 高中 | 0 |
| 大专 | 1 |
| 本科 | 2 |
| 硕士 | 3 |
| 博士 | 4 |

## 3. metadata JSON Schema

```json
{
  "candidate_name": "张三",
  "current_title": "高级Java工程师",
  "current_company": "阿里巴巴",
  "skills_normalized": ["java", "spring cloud", "mysql"],
  "skills_original": ["Java", "Spring Cloud", "MySQL"],
  "industry": "互联网",
  "is_985": true,
  "is_211": false,
  
  "section_type": "experience",
  "organization": "阿里巴巴",
  "title": "高级Java工程师",
  "start_date": "2019-07",
  "end_date": "2024-03",
  "tech_stack": ["Spring Cloud", "MySQL", "Kafka"],
  
  "sequence_index": 3,
  "char_count": 280
}
```

## 4. 索引定义

| 字段 | 索引类型 | 参数 |
|------|----------|------|
| dense_vector | HNSW | metric=COSINE, efConstruction=256, M=16 |
| sparse_vector | SPARSE_INVERTED_INDEX | metric=IP |
| chunk_level | 标量索引 | — |
| resume_id | 标量索引 | — |
| years_of_experience | 标量索引 | — |
| highest_education_level | 标量索引 | — |
| city | 标量索引 | — |
| gender | 标量索引 | — |

## 5. 检索参数

| 模式 | 参数 |
|------|------|
| Dense Search | metric=COSINE, params={"ef": 128} |
| Sparse Search | metric=IP, params={} |
| Hybrid (RRF) | RRFRanker(k=60) |

## 6. Embedding 数据结构

### FlagEmbedding BGE-M3 输出

```python
# Dense: float[1024]
dense = [0.0123, -0.0456, ..., 0.0789]  # 1024 floats

# Sparse: Dict[int, float] (token_id -> weight)
sparse = {
    67912: 0.1523,   # "java" token
    89234: 0.0891,   # "工程师" token
    45678: 0.0634,   # "经验" token
    ...
}
```

### EmbeddingResult

```python
class EmbeddingResult:
    dense: list[float]           # [1024] floats
    sparse: dict[int, float]     # {token_id: weight}
    token_count: int = 0         # input token count
```

## 7. 向量写入量估算

| Chunk Level | 每份简历数量 | 向量类型 |
|-------------|-------------|----------|
| Full | 1 | Dense + Sparse |
| Parent | ~4-6 | Dense + Sparse |
| Small | ~8-15 | Dense + Sparse |
| **合计** | **~13-22** | **~26-44 vectors** |

10 万份简历 → ~200 万个向量（Milvus 单机无压力）
