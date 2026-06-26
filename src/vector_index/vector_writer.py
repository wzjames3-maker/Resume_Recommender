"""
智能招聘 RAG 推荐系统 - 向量写入模块

将 Chunk 向量写入 Milvus
"""

from typing import Any, Dict, List, Optional

from src.common.errors import ErrorCode, ExternalServiceError
from src.common.logger import get_logger
from src.resume_parser.chunk_builder import ChunkLevel, ChunkSchema
from src.vector_index.embedding_generator import EmbeddingResult, get_embedding_generator
from src.vector_index.index import get_vector_index

logger = get_logger("vector_writer")

# 批量写入大小限制
MAX_BATCH_SIZE = 500


class VectorWriter:
    """向量写入器"""

    def __init__(self):
        """初始化向量写入器"""
        self.embedding_generator = get_embedding_generator()
        self.vector_index = get_vector_index()

    def write_chunks(
        self,
        chunks: List[ChunkSchema],
        resume_id: str,
    ) -> List[int]:
        """
        将 Chunk 写入 Milvus

        Args:
            chunks: Chunk 列表
            resume_id: 简历 ID

        Returns:
            List[int]: Milvus ID 列表

        Raises:
            ExternalServiceError: 写入失败
        """
        if not chunks:
            return []

        try:
            # 生成 Embedding
            logger.info(f"生成 Embedding: {len(chunks)} 个 Chunk")
            texts = [chunk.content for chunk in chunks]
            embeddings = self.embedding_generator.batch_generate(texts)

            # 准备写入数据
            write_data = []
            for chunk, embedding in zip(chunks, embeddings):
                write_data.append({
                    "chunk_id": chunk.chunk_id,
                    "resume_id": chunk.resume_id,
                    "chunk_level": chunk.chunk_level.value,
                    "parent_chunk_id": chunk.parent_chunk_id or "",
                    "section_type": chunk.section_type.value if chunk.section_type else "",
                    "dense_vector": embedding.dense,
                    "sparse_vector": embedding.sparse,
                    "content": chunk.content,
                    "metadata": chunk.metadata,
                })

            # 分批写入
            all_ids = []
            for batch_start in range(0, len(write_data), MAX_BATCH_SIZE):
                batch_end = min(batch_start + MAX_BATCH_SIZE, len(write_data))
                batch_data = write_data[batch_start:batch_end]

                logger.info(f"写入 Milvus: {len(batch_data)} 条记录")
                ids = self.vector_index.insert_chunks(batch_data)
                all_ids.extend(ids)

            logger.info(f"向量写入完成: {len(all_ids)} 条记录")

            return all_ids

        except Exception as e:
            logger.error(f"向量写入失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"向量写入失败: {str(e)}",
            )

    def update_chunks(
        self,
        chunks: List[ChunkSchema],
        resume_id: str,
    ) -> List[int]:
        """
        更新简历向量（先删后插）

        Args:
            chunks: 新的 Chunk 列表
            resume_id: 简历 ID

        Returns:
            List[int]: 新的 Milvus ID 列表

        Raises:
            ExternalServiceError: 更新失败
        """
        try:
            # 删除旧向量
            logger.info(f"删除旧向量: resume_id={resume_id}")
            self.vector_index.delete_chunks_by_resume(resume_id)

            # 写入新向量
            logger.info(f"写入新向量: {len(chunks)} 个 Chunk")
            ids = self.write_chunks(chunks, resume_id)

            logger.info(f"向量更新完成: {len(ids)} 条记录")

            return ids

        except Exception as e:
            logger.error(f"向量更新失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"向量更新失败: {str(e)}",
            )

    def delete_chunks(self, resume_id: str) -> None:
        """
        删除简历向量

        Args:
            resume_id: 简历 ID

        Raises:
            ExternalServiceError: 删除失败
        """
        try:
            logger.info(f"删除向量: resume_id={resume_id}")
            self.vector_index.delete_chunks_by_resume(resume_id)
            logger.info(f"向量删除成功: resume_id={resume_id}")

        except Exception as e:
            logger.error(f"向量删除失败: {str(e)}")
            raise ExternalServiceError(
                error_code=ErrorCode.VEC_002,
                detail=f"向量删除失败: {str(e)}",
            )


# 全局向量写入器实例
vector_writer = VectorWriter()


def get_vector_writer() -> VectorWriter:
    """获取向量写入器实例"""
    return vector_writer
