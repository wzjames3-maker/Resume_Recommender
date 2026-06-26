"""
智能招聘 RAG 推荐系统 - Chunk 构建器测试
"""

import pytest

from src.resume_parser.chunk_builder import (
    ChunkBuilder,
    ChunkBuildResult,
    ChunkLevel,
    ChunkSchema,
    get_chunk_builder,
)
from src.resume_parser.segmenter import SectionType, Segment


@pytest.fixture
def chunk_builder():
    """创建 Chunk 构建器实例"""
    return ChunkBuilder()


@pytest.fixture
def sample_segments():
    """示例段落列表"""
    return [
        Segment(
            segment_type=SectionType.EDUCATION,
            content="2018-2022 北京大学 计算机科学与技术 本科\nGPA 3.8/4.0",
            title="教育经历",
            organization="北京大学",
            start_date="2018-09",
            end_date="2022-06",
        ),
        Segment(
            segment_type=SectionType.EXPERIENCE,
            content="2022-至今 字节跳动 后端工程师\n负责推荐系统开发，日均处理请求 1000 万+",
            title="工作经历",
            organization="字节跳动",
            start_date="2022-07",
            end_date=None,
        ),
    ]


class TestChunkLevel:
    """ChunkLevel 测试"""

    def test_chunk_levels(self):
        """测试 Chunk 级别"""
        assert ChunkLevel.SMALL.value == "small"
        assert ChunkLevel.PARENT.value == "parent"
        assert ChunkLevel.FULL.value == "full"


class TestChunkBuilder:
    """ChunkBuilder 测试"""

    def test_build_chunks(self, chunk_builder, sample_segments):
        """测试构建 Chunk"""
        resume_id = "test-resume-001"
        full_text = "张三\n\n教育经历\n2018-2022 北京大学\n\n工作经历\n2022-至今 字节跳动"

        result = chunk_builder.build(sample_segments, resume_id, full_text)

        assert isinstance(result, ChunkBuildResult)
        assert result.total_chunks > 0
        assert result.full_chunk is not None
        assert len(result.parent_chunks) > 0
        assert len(result.small_chunks) > 0

    def test_full_chunk(self, chunk_builder, sample_segments):
        """测试 Full Chunk"""
        resume_id = "test-resume-001"
        full_text = "完整简历文本"

        result = chunk_builder.build(sample_segments, resume_id, full_text)

        full_chunk = result.full_chunk
        assert full_chunk.chunk_level == ChunkLevel.FULL
        assert full_chunk.resume_id == resume_id
        assert full_chunk.parent_chunk_id is None
        assert full_chunk.content == full_text

    def test_parent_chunks(self, chunk_builder, sample_segments):
        """测试 Parent Chunks"""
        resume_id = "test-resume-001"
        full_text = "完整简历文本"

        result = chunk_builder.build(sample_segments, resume_id, full_text)

        parent_chunks = result.parent_chunks
        assert len(parent_chunks) == len(sample_segments)

        for i, parent_chunk in enumerate(parent_chunks):
            assert parent_chunk.chunk_level == ChunkLevel.PARENT
            assert parent_chunk.resume_id == resume_id
            assert parent_chunk.parent_chunk_id is None
            assert parent_chunk.section_type == sample_segments[i].segment_type

    def test_small_chunks(self, chunk_builder, sample_segments):
        """测试 Small Chunks"""
        resume_id = "test-resume-001"
        full_text = "完整简历文本"

        result = chunk_builder.build(sample_segments, resume_id, full_text)

        small_chunks = result.small_chunks
        assert len(small_chunks) > 0

        for small_chunk in small_chunks:
            assert small_chunk.chunk_level == ChunkLevel.SMALL
            assert small_chunk.resume_id == resume_id
            assert small_chunk.parent_chunk_id is not None
            assert small_chunk.char_count > 0

    def test_chunk_id_format(self, chunk_builder, sample_segments):
        """测试 Chunk ID 格式"""
        resume_id = "R001"
        full_text = "完整简历文本"

        result = chunk_builder.build(sample_segments, resume_id, full_text)

        # 验证 Full Chunk ID
        assert result.full_chunk.chunk_id == "R001:full:0"

        # 验证 Parent Chunk ID
        for i, parent_chunk in enumerate(result.parent_chunks):
            assert parent_chunk.chunk_id == f"R001:parent:{i}"

        # 验证 Small Chunk ID
        for small_chunk in result.small_chunks:
            assert ":small:" in small_chunk.chunk_id

    def test_generate_chunk_id(self, chunk_builder):
        """测试生成 Chunk ID"""
        chunk_id = chunk_builder._generate_chunk_id("R001", ChunkLevel.SMALL, 5)
        assert chunk_id == "R001:small:5"

    def test_split_into_sentences(self, chunk_builder):
        """测试切分句子"""
        text = "这是第一句。这是第二句；这是第三句"
        sentences = chunk_builder._split_into_sentences(text)

        assert len(sentences) >= 3

    def test_merge_and_split_chunks(self, chunk_builder):
        """测试合并和拆分"""
        sentences = ["短句", "另一个短句", "这是一个很长的句子" * 20]
        chunks = chunk_builder._merge_and_split_chunks(sentences)

        assert len(chunks) > 0
        for chunk in chunks:
            # 每个 chunk 都应该在合理大小范围内
            assert len(chunk) <= chunk_builder.SMALL_CHUNK_MAX_SIZE + 100  # 允许一些容差

    def test_get_chunk_builder(self):
        """测试获取全局实例"""
        builder = get_chunk_builder()
        assert isinstance(builder, ChunkBuilder)
