"""
智能招聘 RAG 推荐系统 - 向量写入器测试
"""

import pytest

from src.resume_parser.chunk_builder import ChunkLevel, ChunkSchema
from src.vector_index.vector_writer import VectorWriter, get_vector_writer


@pytest.fixture
def writer():
    """创建向量写入器实例"""
    return VectorWriter()


@pytest.fixture
def sample_chunks():
    """示例 Chunk 列表"""
    return [
        ChunkSchema(
            chunk_id="R001:full:0",
            resume_id="R001",
            chunk_level=ChunkLevel.FULL,
            parent_chunk_id=None,
            section_type=None,
            content="完整简历文本",
            char_count=6,
            sequence_index=0,
        ),
        ChunkSchema(
            chunk_id="R001:parent:0",
            resume_id="R001",
            chunk_level=ChunkLevel.PARENT,
            parent_chunk_id=None,
            section_type="education",
            content="教育经历内容",
            char_count=6,
            sequence_index=1,
        ),
        ChunkSchema(
            chunk_id="R001:small:0",
            resume_id="R001",
            chunk_level=ChunkLevel.SMALL,
            parent_chunk_id="R001:parent:0",
            section_type="education",
            content="2018-2022 北京大学",
            char_count=10,
            sequence_index=2,
        ),
    ]


class TestVectorWriter:
    """VectorWriter 测试"""

    def test_get_vector_writer(self):
        """测试获取全局实例"""
        writer = get_vector_writer()
        assert isinstance(writer, VectorWriter)


class TestVectorWriterIntegration:
    """VectorWriter 集成测试（需要 Milvus）"""

    @pytest.mark.skip(reason="需要 Milvus 连接")
    def test_write_chunks(self, writer, sample_chunks):
        """测试写入 Chunk（需要 Milvus）"""
        ids = writer.write_chunks(sample_chunks, "R001")

        assert len(ids) == len(sample_chunks)

    @pytest.mark.skip(reason="需要 Milvus 连接")
    def test_update_chunks(self, writer, sample_chunks):
        """测试更新 Chunk（需要 Milvus）"""
        ids = writer.update_chunks(sample_chunks, "R001")

        assert len(ids) == len(sample_chunks)

    @pytest.mark.skip(reason="需要 Milvus 连接")
    def test_delete_chunks(self, writer):
        """测试删除 Chunk（需要 Milvus）"""
        writer.delete_chunks("R001")
