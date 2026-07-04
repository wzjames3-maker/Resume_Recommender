"""
智能招聘 RAG 推荐系统 - 向量写入模块

变更 (Tier L): 从 chunk.metadata 提取标量字段写入 Milvus 标量列
"""

from typing import Any, Dict, List

from src.common.errors import ErrorCode, ExternalServiceError
from src.common.logger import get_logger
from src.resume_parser.chunk_builder import ChunkSchema
from src.vector_index.embedding_generator import get_embedding_generator
from src.vector_index.index import get_vector_index

logger = get_logger(__name__)

MAX_BATCH_SIZE = 500


class VectorWriter:

    def __init__(self):
        self.embedding_generator = get_embedding_generator()
        self.vector_index = get_vector_index()

    def write_chunks(self, chunks: List[ChunkSchema], resume_id: str) -> List[int]:
        if not chunks:
            return []

        try:
            logger.info(f"生成 Embedding: {len(chunks)} 个 Chunk")
            texts = [chunk.content for chunk in chunks]
            embeddings = self.embedding_generator.batch_generate(texts)

            write_data = []
            for chunk, emb in zip(chunks, embeddings):
                meta = chunk.metadata
                write_data.append({
                    "chunk_id": chunk.chunk_id,
                    "resume_id": chunk.resume_id,
                    "chunk_level": chunk.chunk_level.value,
                    "parent_chunk_id": chunk.parent_chunk_id or "",
                    "section_type": chunk.section_type.value if chunk.section_type else "",
                    "years_of_experience": int(meta.get("years_of_experience", 0) or 0),
                    "highest_education_level": int(meta.get("highest_education_level", 0) or 0),
                    "city": str(meta.get("city", "") or ""),
                    "gender": str(meta.get("gender", "") or ""),
                    "dense_vector": emb.dense,
                    "sparse_vector": emb.sparse,
                    "content": chunk.content,
                    "metadata": meta,
                })

            all_ids = []
            for batch_start in range(0, len(write_data), MAX_BATCH_SIZE):
                batch_end = min(batch_start + MAX_BATCH_SIZE, len(write_data))
                batch = write_data[batch_start:batch_end]
                ids = self.vector_index.insert_chunks(batch)
                all_ids.extend(ids)

            logger.info(f"向量写入完成: {len(all_ids)} 条")
            return all_ids

        except Exception as e:
            logger.error(f"向量写入失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"向量写入失败: {str(e)}",
            )

    def update_chunks(self, chunks: List[ChunkSchema], resume_id: str) -> List[int]:
        logger.info(f"删除旧向量: resume_id={resume_id}")
        self.vector_index.delete_chunks_by_resume(resume_id)
        return self.write_chunks(chunks, resume_id)

    def delete_chunks(self, resume_id: str) -> None:
        self.vector_index.delete_chunks_by_resume(resume_id)
        logger.info(f"向量删除成功: resume_id={resume_id}")


_vector_writer: VectorWriter | None = None


def get_vector_writer() -> VectorWriter:
    global _vector_writer
    if _vector_writer is None:
        _vector_writer = VectorWriter()
    return _vector_writer
