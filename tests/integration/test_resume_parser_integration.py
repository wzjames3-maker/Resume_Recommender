"""
智能招聘 RAG 推荐系统 - 集成测试

Resume Parser → Store → Vector 全链路测试
"""

import pytest
from unittest.mock import Mock, patch

from src.resume_parser.text_extractor import TextExtractor, FileType
from src.resume_parser.llm_extractor import LLMExtractor, ResumeStructured
from src.resume_parser.segmenter import Segmenter
from src.resume_parser.chunk_builder import ChunkBuilder
from src.resume_parser.skill_normalizer import SkillNormalizer
from src.resume_store.models import PersonalInfo, EducationEntry, ExperienceEntry, SkillEntry


class TestResumeParserIntegration:
    """Resume Parser 集成测试"""

    @pytest.fixture
    def text_extractor(self):
        return TextExtractor()

    @pytest.fixture
    def segmenter(self):
        return Segmenter()

    @pytest.fixture
    def chunk_builder(self):
        return ChunkBuilder()

    @pytest.fixture
    def skill_normalizer(self):
        return SkillNormalizer()

    def test_json_extraction_pipeline(self, text_extractor, segmenter, chunk_builder, skill_normalizer):
        """测试 JSON 格式简历的完整处理流程"""
        # 1. 准备测试数据
        import json
        resume_data = {
            "name": "张三",
            "phone": "13800138000",
            "email": "zhangsan@example.com",
            "education": [
                {"school": "北京大学", "degree": "本科", "major": "计算机科学"}
            ],
            "experience": [
                {"company": "字节跳动", "title": "后端工程师", "years": 3}
            ],
            "skills": ["Python", "Java", "Go"]
        }
        json_content = json.dumps(resume_data, ensure_ascii=False).encode("utf-8")

        # 2. 文本提取
        extracted = text_extractor.extract(json_content, "test.json", FileType.JSON)
        assert extracted.status.value == "success"
        assert "张三" in extracted.raw_text

        # 3. 语义切分
        segments = segmenter.segment(extracted.raw_text)
        assert segments.total_segments >= 0

        # 4. Chunk 构建
        chunks = chunk_builder.build(segments.segments, "test-resume-001", extracted.raw_text)
        assert chunks.total_chunks > 0
        assert chunks.full_chunk is not None

        # 5. Skill 标准化
        normalized = skill_normalizer.normalize(["Python", "Java", "Go"])
        assert normalized.total_skills == 3
        assert len(normalized.normalized_skills) == 3

    def test_segment_to_chunk_pipeline(self, segmenter, chunk_builder):
        """测试段落切分到 Chunk 构建的流程"""
        text = """
        教育经历
        2018-2022 北京大学 计算机科学与技术 本科

        工作经历
        2022-至今 字节跳动 后端工程师
        负责推荐系统开发

        技能
        Python, Java, Go
        """

        # 段落切分
        segments = segmenter.segment(text)

        # Chunk 构建
        chunks = chunk_builder.build(segments.segments, "test-001", text)

        # 验证 Chunk 结构
        assert chunks.full_chunk.chunk_level.value == "full"
        assert len(chunks.parent_chunks) > 0
        assert len(chunks.small_chunks) > 0

        # 验证 Small Chunk 有 parent_chunk_id
        for small_chunk in chunks.small_chunks:
            assert small_chunk.parent_chunk_id is not None
            assert small_chunk.parent_chunk_id.startswith("test-001:parent:")

    def test_skill_normalization_pipeline(self, skill_normalizer):
        """测试 Skill 标准化流程"""
        skills = ["Python", "python3", "PyTorch", "JS", "K8s", "SomeUnknownSkill"]

        result = skill_normalizer.normalize(skills)

        # 验证标准化结果
        assert result.total_skills == 6

        # 验证已识别的技能
        python_skill = next(s for s in result.normalized_skills if s.raw_name == "Python")
        assert python_skill.normalized_name == "Python"
        assert python_skill.is_recognized is True

        js_skill = next(s for s in result.normalized_skills if s.raw_name == "JS")
        assert js_skill.normalized_name == "JavaScript"

        # 验证未识别的技能
        unknown_skill = next(s for s in result.normalized_skills if s.raw_name == "SomeUnknownSkill")
        assert unknown_skill.is_recognized is False

    def test_chunk_id_format(self, chunk_builder):
        """测试 Chunk ID 格式"""
        from src.resume_parser.segmenter import Segment, SectionType

        segments = [
            Segment(
                segment_type=SectionType.EDUCATION,
                content="教育经历内容",
                title="教育经历",
            ),
        ]

        chunks = chunk_builder.build(segments, "R001", "完整简历")

        # 验证 Chunk ID 格式
        assert chunks.full_chunk.chunk_id == "R001:full:0"
        assert chunks.parent_chunks[0].chunk_id == "R001:parent:0"
        assert chunks.small_chunks[0].chunk_id.startswith("R001:small:")


class TestSearchIntegration:
    """搜索集成测试"""

    def test_query_builder_integration(self):
        """测试查询构建器集成"""
        from src.recommendation_engine.query_builder import QueryBuilder
        from src.intent_router.schemas import CandidateSlot

        builder = QueryBuilder()

        slots = CandidateSlot(
            job_title="Java工程师",
            skills=["Spring Boot"],
            experience=3,
            city="北京",
        )

        query = builder.build_query_text(slots)

        assert "Java工程师" in query
        assert "Spring Boot" in query
        assert "3年经验" in query
        assert "北京" in query

    def test_rrf_merger_integration(self):
        """测试 RRF 融合集成"""
        from src.recommendation_engine.rrf_merger import RRFMerger

        merger = RRFMerger(k=60)

        dense_results = [
            {"chunk_id": "chunk-1", "content": "内容1"},
            {"chunk_id": "chunk-2", "content": "内容2"},
        ]

        sparse_results = [
            {"chunk_id": "chunk-2", "content": "内容2"},
            {"chunk_id": "chunk-3", "content": "内容3"},
        ]

        merged = merger.merge(dense_results, sparse_results)

        assert len(merged) == 3
        # chunk-2 应该排在最前面
        assert merged[0]["chunk_id"] == "chunk-2"

    def test_metadata_filter_integration(self):
        """测试元数据过滤器集成"""
        from src.recommendation_engine.metadata_filter import MetadataFilter
        from src.recommendation_engine.hybrid_retriever import RetrievalResult
        from src.intent_router.schemas import CandidateSlot, EducationLevel

        filter = MetadataFilter()

        results = [
            RetrievalResult(
                resume_id="R001",
                chunk_id="R001:small:0",
                chunk_level="small",
                parent_chunk_id="R001:parent:0",
                content="内容1",
                score=0.9,
                rank=1,
                metadata={"city": "北京", "education": "本科", "years_of_experience": 3},
            ),
            RetrievalResult(
                resume_id="R002",
                chunk_id="R002:small:0",
                chunk_level="small",
                parent_chunk_id="R002:parent:0",
                content="内容2",
                score=0.8,
                rank=2,
                metadata={"city": "上海", "education": "硕士", "years_of_experience": 5},
            ),
        ]

        slots = CandidateSlot(city="北京", education=EducationLevel.BACHELOR)

        filter_result = filter.filter(results, slots)

        # R001 应该通过过滤（北京 + 本科）
        # R002 应该被过滤掉（上海）
        assert len(filter_result.results) == 1
        assert filter_result.results[0].resume_id == "R001"


class TestConversationIntegration:
    """对话集成测试"""

    def test_session_lifecycle(self):
        """测试会话生命周期"""
        from src.conversation_memory.session_manager import SessionManager

        manager = SessionManager()

        # 创建会话
        session = manager.create_session("user-001")
        assert session.status.value == "active"
        assert session.turn_count == 0

        # 追加消息
        manager.append_message(session.session_id, "user", "帮我找Java工程师")
        manager.append_message(session.session_id, "assistant", "为您找到5位候选人")

        # 验证轮次
        updated_session = manager.get_session(session.session_id)
        assert updated_session.turn_count == 1
        assert len(updated_session.messages) == 2

        # 删除会话
        manager.delete_session(session.session_id)
        deleted_session = manager.get_session(session.session_id)
        assert deleted_session is None

    def test_slot_merger_integration(self):
        """测试 Slot 合并集成"""
        from src.conversation_memory.slot_merger import SlotMerger, MergeStrategy
        from src.intent_router.schemas import CandidateSlot

        merger = SlotMerger()

        old_slots = CandidateSlot(job_title="Python工程师", city="上海")
        new_slots = CandidateSlot(job_title="Java工程师", experience=3)

        # 增量合并
        merged = merger.merge_candidate_slots(new_slots, old_slots, MergeStrategy.INCREMENTAL)

        assert merged.job_title == "Java工程师"  # 新值覆盖
        assert merged.experience == 3  # 新值
        assert merged.city == "上海"  # 旧值保留
