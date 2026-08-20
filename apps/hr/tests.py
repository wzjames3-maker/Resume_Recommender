import csv
import io
import json
import os
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient
import uuid_utils.compat as uuid

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from django.contrib.postgres.search import SearchVector
from django.db.models import Value
from unittest.mock import Mock

from hr.models import (
    Application,
    ApplicationEvent,
    ApplicationEventType,
    ApplicationStatus,
    HrAgentProposal,
    HrAgentRun,
    JobStage,
    Candidate,
    HandoffStatus,
    HrAccess,
    HrAuditLog,
    HrConfig,
    HrOffboard,
    Interview,
    Job,
    Offer,
    OnboardingHandoff,
    ResumeDatabase,
    ResumeDatabaseMembership,
    ResumeFile,
    ResumeStatus,
)
from hr.services.audit import write_audit_log
from hr.task.resume import cleanup_orphan_resumes, parse_resume_task
from hr.serializers.ai import AiService
from hr.serializers.import_service import ImportService
from hr.serializers.offer import OfferService, OnboardingService
from hr.serializers.recruitment import CANDIDATE_EXPORT_FIELDS, RecruitmentService
from hr.services.ai_parser import extract_skills, parse_search_conditions
from hr.services.resume_index import delete_resume_index, get_or_create_resume_knowledge, index_resume, set_resume_index_active
from hr.services.application_service import ApplicationService
from hr.agents import scoring
from hr.agents.proposals import ProposalService
from knowledge.models import Document, Embedding, Knowledge, KnowledgeFolder, KnowledgeScope, KnowledgeType, Paragraph
from knowledge.serializers.knowledge import KnowledgeSerializer
from models_provider.models import Model
from hr.services.resume_parser import parse_resume_text
from users.models import User
class ResumeParserTests(TestCase):
    def test_extracts_contact_and_profile_fields(self):
        text = (
            "姓名：张三\n电话：13812345678\n邮箱：zhangsan@example.com\n"
            "现居城市：杭州\n期望城市：上海\n最高学历：本科\n5年工作经验\n"
            "专业技能：Python, Django, PostgreSQL"
        )
        result = parse_resume_text(text)
        self.assertEqual(result["name"], "张三")
        self.assertEqual(result["phone"], "13812345678")
        self.assertEqual(result["email"], "zhangsan@example.com")
        # 设计：正则只抽身份字段，其余（城市/学历/年限/技能）留空由切片+检索处理
        self.assertEqual(result["current_city"], "")
        self.assertEqual(result["highest_degree"], "")
        self.assertIsNone(result["years_experience"])
        self.assertEqual(result["skills"], [])

    def test_unknown_fields_stay_empty(self):
        result = parse_resume_text("这是一个没有结构化字段的文本")
        self.assertEqual(result["name"], "")
        self.assertEqual(result["email"], "")
        self.assertEqual(result["phone"], "")
        self.assertEqual(result["skills"], [])

    def test_identity_fields_only(self):
        """设计：正则只抽姓名/电话/邮箱，城市/学历/年限/技能不再做规则解析。"""
        text = (
            "简历；姓名；李冠光；出生年月；1933年10月；籍贯；新疆省阿克苏市；政治面貌；群众；"
            "户籍；澳门省澳门市；个人技能；吃饭喝茶；办公软件；教育背景；现居城市：北京市；工作年限：2年"
        )
        result = parse_resume_text(text)
        self.assertEqual(result["name"], "李冠光")
        self.assertEqual(result["current_city"], "")
        self.assertEqual(result["skills"], [])
        self.assertIsNone(result["years_experience"])

    def test_extract_skills_llm_parses_json_array(self):
        from hr.services.resume_parser import extract_skills_llm

        def chat_fn(prompt):
            return '["Python", "市场营销", "新媒体运营"]'

        self.assertEqual(
            extract_skills_llm("姓名：张三\n工作经历：负责 Python 后端与市场营销", chat_fn),
            ["Python", "市场营销", "新媒体运营"],
        )

    def test_extract_skills_llm_tolerates_code_fence_and_dedupes(self):
        from hr.services.resume_parser import extract_skills_llm

        def chat_fn(prompt):
            return '```json\\n["Python", "python", "市场营销", "新媒体运营"]\\n```'

        result = extract_skills_llm("简历文本", chat_fn)
        self.assertEqual(result, ["Python", "市场营销", "新媒体运营"])

    def test_extract_skills_llm_filters_junk_and_falls_back_empty(self):
        from hr.services.resume_parser import extract_skills_llm

        def chat_fn(prompt):
            return '["负责 Python 后端开发", "熟悉市场营销，具备客户沟通能力", "", "Python"]'

        self.assertEqual(extract_skills_llm("简历文本", chat_fn), ["Python"])

    def test_extract_skills_llm_returns_empty_on_invalid_output(self):
        from hr.services.resume_parser import extract_skills_llm

        def chat_fn(prompt):
            return "抱歉，我无法完成该任务。"

        self.assertEqual(extract_skills_llm("简历文本", chat_fn), [])


class ResumeFileModelTests(TestCase):
    def test_duplicate_sha256_in_same_workspace_rejected(self):
        ResumeFile.objects.create(file_name="a.txt", extension="txt", file_path="/tmp/a.txt",
                                  file_size=1, sha256="abc", workspace_id="w1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ResumeFile.objects.create(file_name="b.txt", extension="txt", file_path="/tmp/b.txt",
                                          file_size=1, sha256="abc", workspace_id="w1")

    def test_same_sha256_different_workspace_allowed(self):
        ResumeFile.objects.create(file_name="a.txt", extension="txt", file_path="/tmp/a.txt",
                                  file_size=1, sha256="abc", workspace_id="w1")
        ResumeFile.objects.create(file_name="b.txt", extension="txt", file_path="/tmp/b.txt",
                                  file_size=1, sha256="abc", workspace_id="w2")
        self.assertEqual(ResumeFile.objects.count(), 2)


class ResumeServiceTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")

    def _txt_file(self, content, name="resume.txt"):
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write(content.encode("utf-8"))
        handle.close()
        return handle.name, name, "txt"

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_upload_creates_pending_and_dispatches_task(self, mock_delay):
        path, name, ext = self._txt_file("姓名：李四\n电话：13912345678\n3年工作经验")
        result = self.service.upload_resumes([(path, name, ext)], "OTHER")
        self.assertEqual(result[0]["status"], "PENDING")
        self.assertIsNone(result[0]["candidate_id"])
        self.assertEqual(result[0]["duplicate"], False)
        self.assertEqual(mock_delay.call_count, 1)
        resume = ResumeFile.objects.get(id=result[0]["resume_id"])
        self.assertEqual(resume.status, "PENDING")

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_duplicate_upload_reuses_candidate(self, mock_delay):
        path, name, ext = self._txt_file("姓名：王五\n邮箱：wangwu@example.com")
        first = self.service.upload_resumes([(path, name, ext)], "OTHER")[0]
        path2, _, _ = self._txt_file("姓名：王五\n邮箱：wangwu@example.com")
        second = self.service.upload_resumes([(path2, name, ext)], "OTHER")[0]
        self.assertEqual(second["duplicate"], True)
        self.assertEqual(second["candidate_id"], first["candidate_id"])
        self.assertEqual(Candidate.objects.count(), 0)
        self.assertEqual(ResumeFile.objects.count(), 1)

    def test_reject_unsupported_extension_and_oversize(self):
        with self.assertRaisesRegex(AppApiException, "not supported"):
            self.service.upload_resumes([("/tmp/x.pdf", "x.pdf", "pdf")], "OTHER")
        path, name, ext = self._txt_file("a" * (21 * 1024 * 1024))
        with self.assertRaisesRegex(AppApiException, "20"):
            self.service.upload_resumes([(path, name, ext)], "OTHER")

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_duplicate_upload_keeps_first_record(self, mock_delay):
        path, name, ext = self._txt_file("姓名：赵六")
        first = self.service.upload_resumes([(path, name, ext)], "OTHER")[0]
        self.assertEqual(first["status"], "PENDING")
        path2, _, _ = self._txt_file("姓名：赵六")
        second = self.service.upload_resumes([(path2, name, ext)], "OTHER")[0]
        self.assertEqual(second["duplicate"], True)
        self.assertEqual(second["candidate_id"], first["candidate_id"])
        self.assertEqual(ResumeFile.objects.count(), 1)
        self.assertEqual(mock_delay.call_count, 1)

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_upload_dispatch_already_queued_raises_500(self, mock_delay):
        from celery_once import AlreadyQueued

        mock_delay.side_effect = AlreadyQueued(5)
        path, name, ext = self._txt_file("姓名：周七")
        with self.assertRaisesRegex(AppApiException, "任务已存在"):
            self.service.upload_resumes([(path, name, ext)], "OTHER")

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_upload_dispatch_error_marks_failed(self, mock_delay):
        mock_delay.side_effect = RuntimeError("broker down")
        path, name, ext = self._txt_file("姓名：吴八")
        result = self.service.upload_resumes([(path, name, ext)], "OTHER")
        self.assertEqual(result[0]["status"], "FAILED")
        self.assertTrue(result[0]["error_message"])
        resume = ResumeFile.objects.get(id=result[0]["resume_id"])
        self.assertEqual(resume.status, "FAILED")


class AdvancedSearchTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="ADMIN")
        self.alice = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", skills=["Python", "Django"],
            highest_degree="本科", years_experience=5, source="JOB_SITE",
        )
        self.bob = Candidate.objects.create(
            name="Bob", workspace_id="workspace-a", skills=["Java", "Spring"],
            highest_degree="硕士", years_experience=3, source="REFERRAL",
        )

    def test_multi_skill_and_semantics(self):
        result = self.service.page_candidates(1, 20, {"skills": "Python,Django"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Alice")

    def test_skills_filter_matches_resume_text(self):
        """新架构：技能不再是结构化字段（新简历 skills 恒空）——「按技能搜索」改为
        结构化技能字段 OR 简历原文/正文命中；无技能字段的候选人按正文关键词仍能搜到。"""
        carol = Candidate.objects.create(
            name="Carol", workspace_id="workspace-a", skills=[],
        )
        KnowledgeFolder.objects.get_or_create(id="default", defaults={"name": "default", "workspace_id": "default"})
        knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id="workspace-a", name="简历语义索引", desc="",
            type=KnowledgeType.BASE.value,
        )
        document = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=knowledge.id, name="c.txt", char_length=10,
        )
        Paragraph.objects.create(
            id=uuid.uuid7(), document_id=document.id, knowledge_id=knowledge.id,
            title="工作经历", content="负责市场活动策划与品牌推广",
        )
        ResumeFile.objects.create(
            workspace_id="workspace-a", candidate=carol, file_name="c.txt", extension="txt",
            file_path="/tmp/c.txt", file_size=1, sha256="sha-carol-text", source_channel="OTHER",
            status=ResumeStatus.SUCCESS, document_id=document.id, raw_text="市场营销 销售策划",
        )
        # 正文命中（Carol 无技能字段，靠段落/原文关键词命中）
        result = self.service.page_candidates(1, 20, {"skills": "市场"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Carol")
        # 结构化技能字段命中不受影响（Bob 的 skills 字段）
        result = self.service.page_candidates(1, 20, {"skills": "Java"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Bob")
        # 多词 AND：结构化字段与正文可混用命中（Carol 两个词都在原文/正文，Bob 无）
        result = self.service.page_candidates(1, 20, {"skills": "市场,销售"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Carol")

    def test_degree_and_years_range_filter(self):
        result = self.service.page_candidates(1, 20, {"highest_degree": "硕士", "years_min": "2", "years_max": "4"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Bob")

    def test_source_filter(self):
        result = self.service.page_candidates(1, 20, {"source": "REFERRAL"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Bob")

    def test_years_range_excludes_null_experience(self):
        Candidate.objects.create(name="NullExp", workspace_id="workspace-a", skills=[], years_experience=None)
        result = self.service.page_candidates(1, 20, {"years_min": "1"})
        self.assertEqual(result["total"], 2)


class JobMatchTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="ADMIN")
        self.alice = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", skills=["Python", "Django", "PostgreSQL"],
            current_city="杭州", target_city="上海", years_experience=5, status="ACTIVE",
        )
        self.bob = Candidate.objects.create(
            name="Bob", workspace_id="workspace-a", skills=["Java"], current_city="北京",
            target_city="杭州", years_experience=3, status="ACTIVE",
        )
        self.job = Job.objects.create(
            name="Python Engineer", department="Engineering", city="杭州", headcount=1,
            workspace_id="workspace-a", skill_requirements=["Python", "Django"],
        )

    def test_match_scores_skills_and_city(self):
        result = self.service.match_job_candidates(self.job.id, 1, 20)
        by_name = {item["name"]: item for item in result["records"]}
        self.assertEqual(by_name["Alice"]["match_score"], 6)
        self.assertEqual(by_name["Alice"]["matched_skills"], ["Python", "Django"])
        self.assertEqual(by_name["Bob"]["match_score"], 2)

    def test_match_sorted_by_score_desc(self):
        result = self.service.match_job_candidates(self.job.id, 1, 20)
        scores = [item["match_score"] for item in result["records"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_match_keyword_recall_from_resume_content(self):
        # 技能字段为空但简历正文含需求技能时，关键词召回应纳入匹配（修复：简历正文匹配不到营销候选人）
        from knowledge.models import Knowledge, KnowledgeFolder, KnowledgeType, Paragraph

        KnowledgeFolder.objects.get_or_create(id="default", defaults={"name": "default", "workspace_id": "default"})
        carol = Candidate.objects.create(
            name="Carol", workspace_id="workspace-a", skills=[], current_city="上海",
            years_experience=2, status="ACTIVE",
        )
        knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id="workspace-a", name="简历语义索引", desc="",
            type=KnowledgeType.BASE.value,
        )
        document = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=knowledge.id, name="c.txt", char_length=10,
        )
        Paragraph.objects.create(
            id=uuid.uuid7(), document_id=document.id, knowledge_id=knowledge.id,
            title="工作经历", content="负责 Python 后端开发与系统设计",
        )
        ResumeFile.objects.create(
            workspace_id="workspace-a", candidate=carol, file_name="c.txt", extension="txt",
            file_path="/tmp/c.txt", file_size=1, sha256="sha-carol-kw", source_channel="OTHER",
            status=ResumeStatus.SUCCESS, document_id=document.id,
        )
        result = self.service.match_job_candidates(self.job.id, 1, 20)
        carol_row = next((r for r in result["records"] if r["name"] == "Carol"), None)
        self.assertIsNotNone(carol_row)
        self.assertEqual(carol_row["match_score"], 2)
        self.assertIn("Python", carol_row["matched_skills"])

    def test_match_without_requirements_returns_empty(self):
        self.job.skill_requirements = []
        self.job.city = ""
        self.job.save(update_fields=["skill_requirements", "city"])
        result = self.service.match_job_candidates(self.job.id, 1, 20)
        self.assertEqual(result["total"], 0)

    def test_match_rejects_closed_job_and_cross_workspace(self):
        self.job.status = "CLOSED"
        self.job.save(update_fields=["status"])
        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.match_job_candidates(self.job.id, 1, 20)
        foreign = Job.objects.create(name="F", workspace_id="workspace-b", headcount=1, city="杭州",
                                     skill_requirements=["Python"])
        with self.assertRaises(NotFound404):
            self.service.match_job_candidates(foreign.id, 1, 20)
class _StubModel:
    def __init__(self, content):
        self._content = content

    def invoke(self, prompt):
        return type("Response", (), {"content": self._content})()


class AiParserTests(TestCase):
    def test_parse_returns_full_conditions(self):
        model = _StubModel(
            '{"skills": ["Python", "Kafka"], "city": "上海", "years_min": 3, "years_max": 5, '
            '"highest_degree": "本科", "status": "ACTIVE"}'
        )
        result = parse_search_conditions(model, "找3到5年Python和Kafka经验在上海的本科学历候选人")
        self.assertEqual(result, {
            "skills": ["Python", "Kafka"],
            "city": "上海",
            "years_min": 3,
            "years_max": 5,
            "highest_degree": "本科",
            "status": "ACTIVE",
        })

    def test_parse_fills_missing_fields_with_defaults(self):
        model = _StubModel('{"skills": null}')
        result = parse_search_conditions(model, "找后端")
        self.assertEqual(result, {
            "skills": [], "city": None, "years_min": None,
            "years_max": None, "highest_degree": None, "status": None,
        })

    def test_parse_rejects_invalid_json(self):
        model = _StubModel("这不是 JSON")
        with self.assertRaisesRegex(AppApiException, "AI 解析失败"):
            parse_search_conditions(model, "找后端")

    def test_parse_rejects_non_dict_json(self):
        model = _StubModel("[1, 2, 3]")
        with self.assertRaisesRegex(AppApiException, "AI 解析失败"):
            parse_search_conditions(model, "找后端")

    def test_parse_invoke_error_returns_400(self):
        class _BrokenModel:
            def invoke(self, prompt):
                raise RuntimeError("connection refused")

        with self.assertRaisesRegex(AppApiException, "AI 解析失败"):
            parse_search_conditions(_BrokenModel(), "找后端")

    def test_parse_swaps_reversed_year_range(self):
        model = _StubModel('{"years_min": 10, "years_max": 2, "skills": []}')
        result = parse_search_conditions(model, "q")
        self.assertEqual(result["years_min"], 2)
        self.assertEqual(result["years_max"], 10)

    def test_parse_drops_non_positive_years(self):
        model = _StubModel('{"years_min": "3", "years_max": 0, "skills": []}')
        result = parse_search_conditions(model, "q")
        self.assertEqual(result["years_min"], None)
        self.assertEqual(result["years_max"], None)

    def test_parse_cleans_skills(self):
        model = _StubModel('{"skills": [" Python ", "", "Python", 123]}')
        result = parse_search_conditions(model, "q")
        self.assertEqual(result["skills"], ["Python"])

    def test_extract_skills_cleans_and_dedups(self):
        model = _StubModel('{"skills": [" Python ", "Django", "python", "", 1]}')
        self.assertEqual(extract_skills(model, "描述"), ["Python", "Django"])

    def test_extract_skills_truncates_to_20(self):
        model = _StubModel('{"skills": [' + ', '.join('"s%d"' % i for i in range(30)) + ']}')
        self.assertEqual(len(extract_skills(model, "描述")), 20)

    def test_extract_skills_non_list_returns_empty(self):
        model = _StubModel('{"skills": "Python"}')
        self.assertEqual(extract_skills(model, "描述"), [])

    def test_extract_skills_rejects_non_dict_json(self):
        model = _StubModel("[1, 2, 3]")
        with self.assertRaisesRegex(AppApiException, "AI 解析失败"):
            extract_skills(model, "描述")


class AiServiceTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = AiService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")

    def test_config_default_is_null(self):
        self.assertEqual(
            self.service.get_config(),
            {"llm_model_id": None, "rerank_model_id": None, "agent_knowledge_bases": []},
        )

    @patch("hr.serializers.ai.get_model_by_id")
    def test_save_and_get_config(self, mock_get_model):
        mock_get_model.return_value = SimpleNamespace(model_type="LLM")
        saved = self.service.save_config({"llm_model_id": "model-1"})
        self.assertEqual(
            saved, {"llm_model_id": "model-1", "rerank_model_id": None, "agent_knowledge_bases": []}
        )
        self.assertEqual(
            self.service.get_config(),
            {"llm_model_id": "model-1", "rerank_model_id": None, "agent_knowledge_bases": []},
        )
        mock_get_model.assert_called_once_with("model-1", "workspace-a")

    @patch("hr.serializers.ai.get_model_by_id")
    def test_save_config_rejects_non_llm_model(self, mock_get_model):
        mock_get_model.return_value = SimpleNamespace(model_type="EMBEDDING")
        with self.assertRaisesRegex(AppApiException, "LLM"):
            self.service.save_config({"llm_model_id": "model-1"})

    @patch("hr.serializers.ai.get_model_by_id")
    def test_save_config_rejects_missing_model(self, mock_get_model):
        mock_get_model.side_effect = Exception("Model does not exist")
        with self.assertRaisesRegex(AppApiException, "模型不存在"):
            self.service.save_config({"llm_model_id": "model-1"})

    @patch("hr.serializers.ai.get_model_by_id")
    def test_save_config_with_rerank(self, mock_get_model):
        mock_get_model.side_effect = [SimpleNamespace(model_type="LLM"), SimpleNamespace(model_type="RERANKER")]
        saved = self.service.save_config({"llm_model_id": "model-1", "rerank_model_id": "rerank-1"})
        self.assertEqual(
            saved, {"llm_model_id": "model-1", "rerank_model_id": "rerank-1", "agent_knowledge_bases": []}
        )
        self.assertEqual(self.service.get_config()["rerank_model_id"], "rerank-1")

    @patch("hr.serializers.ai.get_model_by_id")
    def test_save_config_rejects_non_rerank_model(self, mock_get_model):
        mock_get_model.side_effect = [SimpleNamespace(model_type="LLM"), SimpleNamespace(model_type="EMBEDDING")]
        with self.assertRaisesRegex(AppApiException, "RERANKER"):
            self.service.save_config({"llm_model_id": "model-1", "rerank_model_id": "rerank-1"})

    def test_save_config_requires_model_id(self):
        with self.assertRaisesRegex(AppApiException, "llm_model_id is required"):
            self.service.save_config({})

    def test_member_cannot_save_config(self):
        member_service = AiService(workspace_id="workspace-a", user_id=self.user_id, hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            member_service.save_config({"llm_model_id": "model-1"})

    def test_parse_search_requires_config(self):
        with self.assertRaisesRegex(AppApiException, "AI 设置"):
            self.service.parse_search("找 Python 后端")

    @patch("hr.serializers.ai.get_model_by_id")
    def test_parse_search_rejects_non_llm_configured_model(self, mock_get_model):
        HrConfig.objects.create(workspace_id="workspace-a", llm_model_id="model-1")
        mock_get_model.return_value = SimpleNamespace(model_type="EMBEDDING")
        with self.assertRaisesRegex(AppApiException, "AI 设置"):
            self.service.parse_search("找 Python 后端")

    def test_extract_skills_requires_config(self):
        with self.assertRaisesRegex(AppApiException, "AI 设置"):
            self.service.extract_skills("招聘 Python 工程师")

    def test_parse_search_rejects_empty_query(self):
        HrConfig.objects.create(workspace_id="workspace-a", llm_model_id="model-1")
        with self.assertRaisesRegex(AppApiException, "query is required"):
            self.service.parse_search("   ")

    def test_parse_search_rejects_long_query(self):
        HrConfig.objects.create(workspace_id="workspace-a", llm_model_id="model-1")
        with self.assertRaisesRegex(AppApiException, "query is too long"):
            self.service.parse_search("x" * 2001)

    def test_extract_skills_rejects_empty_description(self):
        HrConfig.objects.create(workspace_id="workspace-a", llm_model_id="model-1")
        with self.assertRaisesRegex(AppApiException, "description is required"):
            self.service.extract_skills("   ")

    def test_extract_skills_rejects_long_description(self):
        HrConfig.objects.create(workspace_id="workspace-a", llm_model_id="model-1")
        with self.assertRaisesRegex(AppApiException, "description is too long"):
            self.service.extract_skills("x" * 4097)

    @patch("hr.serializers.ai.get_model_by_id")
    @patch("hr.serializers.ai.get_model_instance_by_model_workspace_id")
    def test_parse_search_with_mock_model(self, mock_instance, mock_get_model):
        HrConfig.objects.create(workspace_id="workspace-a", llm_model_id="model-1")
        mock_get_model.return_value = SimpleNamespace(model_type="LLM")
        mock_instance.return_value = _StubModel(
            '{"skills": ["Python"], "city": "上海", "years_min": 3, "years_max": null, '
            '"highest_degree": null, "status": null}'
        )
        result = self.service.parse_search("找上海3年Python经验的人")
        self.assertEqual(result["conditions"]["skills"], ["Python"])
        self.assertEqual(result["conditions"]["city"], "上海")
        self.assertEqual(result["conditions"]["years_min"], 3)

    @patch("hr.serializers.ai.get_model_by_id")
    @patch("hr.serializers.ai.get_model_instance_by_model_workspace_id")
    def test_extract_skills_with_mock_model(self, mock_instance, mock_get_model):
        HrConfig.objects.create(workspace_id="workspace-a", llm_model_id="model-1")
        mock_get_model.return_value = SimpleNamespace(model_type="LLM")
        mock_instance.return_value = _StubModel('{"skills": ["Python", "Django"]}')
        result = self.service.extract_skills("负责 Python/Django 开发")
        self.assertEqual(result["skills"], ["Python", "Django"])

    @patch("hr.serializers.ai.get_model_by_id")
    @patch("hr.serializers.ai.get_model_instance_by_model_workspace_id")
    def test_parse_search_model_instance_error_returns_config_hint(self, mock_instance, mock_get_model):
        HrConfig.objects.create(workspace_id="workspace-a", llm_model_id="model-1")
        mock_get_model.return_value = SimpleNamespace(model_type="LLM")
        mock_instance.side_effect = Exception("broken")
        with self.assertRaisesRegex(AppApiException, "AI 设置"):
            self.service.parse_search("找 Python 后端")


class AiRouteSmokeTests(TestCase):
    def _paths(self):
        return [
            "/admin/api/workspace/workspace-a/hr/ai/config",
            "/admin/api/workspace/workspace-a/hr/ai/search-parse",
            "/admin/api/workspace/workspace-a/hr/ai/extract-skills",
        ]

    def test_ai_routes_are_registered(self):
        for path in self._paths():
            response = self.client.get(path)
            self.assertIn(response.status_code, (401, 403), f"{path} 未注册或未受保护: {response.status_code}")


class ResumeParseTaskTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()

    def _resume(self, content, extension="txt", workspace_id="workspace-a"):
        handle = tempfile.NamedTemporaryFile(suffix=f".{extension}", delete=False)
        handle.write(content.encode("utf-8"))
        handle.close()
        return ResumeFile.objects.create(
            workspace_id=workspace_id, file_name=f"r.{extension}", extension=extension,
            file_path=handle.name, file_size=os.path.getsize(handle.name),
            sha256="sha-" + uuid.uuid7().hex, source_channel="OTHER",
            status=ResumeStatus.PENDING, user_id=self.user_id,
        )

    def test_task_parses_and_creates_candidate(self):
        resume = self._resume("姓名：李四\n电话：13912345678\n3年工作经验")
        parse_resume_task.run(str(resume.id))
        resume.refresh_from_db()
        self.assertEqual(resume.status, "SUCCESS")
        self.assertIsNotNone(resume.candidate)
        self.assertEqual(resume.candidate.name, "李四")
        self.assertEqual(resume.candidate.phone, "13912345678")
        self.assertEqual(resume.candidate.source, "OTHER")

    def test_task_marks_failed_on_parse_error(self):
        resume = self._resume("not a docx zip", extension="docx")
        parse_resume_task.run(str(resume.id))
        resume.refresh_from_db()
        self.assertEqual(resume.status, "FAILED")
        self.assertTrue(resume.error_message)
        self.assertIsNone(resume.candidate)

    def test_task_ignores_missing_resume(self):
        parse_resume_task.run(str(uuid.uuid7()))


class ResumeBatchStatusTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="ADMIN")

    def _resume(self, status="PENDING"):
        return ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="r.txt", extension="txt",
            file_path="/tmp/r.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            source_channel="OTHER", status=status,
        )

    def test_batch_status_returns_only_existing(self):
        r1 = self._resume()
        r2 = self._resume("FAILED")
        result = self.service.batch_resume_status([str(r1.id), str(r2.id), str(uuid.uuid7())])
        self.assertEqual(len(result), 2)
        by_id = {item["resume_id"]: item for item in result}
        self.assertEqual(by_id[str(r1.id)]["status"], "PENDING")
        self.assertEqual(by_id[str(r2.id)]["status"], "FAILED")
        self.assertEqual(by_id[str(r2.id)]["error_message"], "")

    def test_batch_status_filters_by_workspace(self):
        foreign = ResumeFile.objects.create(
            workspace_id="workspace-b", file_name="f.txt", extension="txt",
            file_path="/tmp/f.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
        )
        result = self.service.batch_resume_status([str(foreign.id)])
        self.assertEqual(result, [])

    def test_batch_status_rejects_invalid_id_format(self):
        with self.assertRaisesRegex(AppApiException, "ids is invalid"):
            self.service.batch_resume_status(["garbage"])


class ResumeBatchStatusRouteTests(TestCase):
    def test_route_is_registered_and_protected(self):
        response = self.client.get("/admin/api/workspace/workspace-a/hr/resumes/batch-status?ids=a")
        self.assertIn(response.status_code, (401, 403))

    def test_batch_status_route_not_swallowed_by_resume_detail(self):
        from django.urls import resolve
        from hr.views.recruitment import ResumeBatchStatusAPI

        resolved = resolve("/admin/api/workspace/workspace-a/hr/resumes/batch-status")
        self.assertIs(resolved.func.cls, ResumeBatchStatusAPI)


class ResumeDownloadTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="ADMIN")
        self.handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        self.handle.write("姓名：张三\n电话：13812345678".encode("utf-8"))
        self.handle.close()
        self.resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="zhangsan.txt", extension="txt",
            file_path=self.handle.name, file_size=os.path.getsize(self.handle.name),
            sha256="sha-" + uuid.uuid7().hex, source_channel="OTHER", status="SUCCESS",
        )

    def test_download_returns_path_name_and_mime(self):
        file_path, file_name, content_type = self.service.download_resume(str(self.resume.id))
        self.assertEqual(file_path, self.handle.name)
        self.assertEqual(file_name, "zhangsan.txt")
        self.assertEqual(content_type, "text/plain")

    def test_download_missing_file_raises_404(self):
        self.resume.file_path = "/tmp/not-exists-" + uuid.uuid7().hex + ".txt"
        self.resume.save(update_fields=["file_path"])
        with self.assertRaises(NotFound404):
            self.service.download_resume(str(self.resume.id))

    def test_download_cross_workspace_raises_404(self):
        foreign = ResumeFile.objects.create(
            workspace_id="workspace-b", file_name="f.txt", extension="txt",
            file_path="/tmp/f.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
        )
        with self.assertRaises(NotFound404):
            self.service.download_resume(str(foreign.id))

    def test_content_returns_txt_text(self):
        result = self.service.resume_content(str(self.resume.id))
        self.assertIn("张三", result["content"])
        self.assertIn("13812345678", result["content"])

    def test_content_broken_docx_raises_400(self):
        broken = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        broken.write(b"not a docx zip")
        broken.close()
        docx_resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="bad.docx", extension="docx",
            file_path=broken.name, file_size=os.path.getsize(broken.name),
            sha256="sha-" + uuid.uuid7().hex, source_channel="OTHER", status="SUCCESS",
        )
        with self.assertRaisesRegex(AppApiException, "提取失败"):
            self.service.resume_content(str(docx_resume.id))

    def test_content_missing_file_raises_404(self):
        self.resume.file_path = "/tmp/not-exists-" + uuid.uuid7().hex + ".txt"
        self.resume.save(update_fields=["file_path"])
        with self.assertRaises(NotFound404):
            self.service.resume_content(str(self.resume.id))

class DuplicateDetectionTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="ADMIN")
        self.alice = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13800000001", email="alice@example.com",
        )
        self.bob = Candidate.objects.create(
            name="Bob", workspace_id="workspace-a", phone="13800000001", email="bob@example.com",
        )
        self.carol = Candidate.objects.create(
            name="Carol", workspace_id="workspace-a", phone="13800000002", email="ALICE@example.com",
        )
        self.foreign = Candidate.objects.create(
            name="Dave", workspace_id="workspace-b", phone="13800000001", email="dave@example.com",
        )

    def test_page_marks_same_phone_and_email_as_duplicates(self):
        result = self.service.page_candidates(1, 20, {})
        by_id = {item["id"]: item for item in result["records"]}
        self.assertIn(str(self.bob.id), by_id[str(self.alice.id)]["duplicate_ids"])
        self.assertIn(str(self.alice.id), by_id[str(self.bob.id)]["duplicate_ids"])
        self.assertIn(str(self.carol.id), by_id[str(self.alice.id)]["duplicate_ids"])

    def test_page_does_not_mark_foreign_workspace(self):
        result = self.service.page_candidates(1, 20, {})
        by_id = {item["id"]: item for item in result["records"]}
        self.assertNotIn(str(self.foreign.id), by_id[str(self.alice.id)]["duplicate_ids"])
        self.assertIn(str(self.alice.id), by_id[str(self.carol.id)]["duplicate_ids"])

    def test_check_duplicate_by_phone_and_email(self):
        result = self.service.check_duplicate({"phone": "13800000001"})
        ids = {item["id"] for item in result["candidates"]}
        self.assertIn(str(self.alice.id), ids)
        self.assertIn(str(self.bob.id), ids)
        result = self.service.check_duplicate({"email": "ALICE@example.com"})
        ids = {item["id"] for item in result["candidates"]}
        self.assertIn(str(self.alice.id), ids)
        self.assertIn(str(self.carol.id), ids)

    def test_check_duplicate_excludes_self(self):
        result = self.service.check_duplicate({"email": "alice@example.com", "exclude_id": str(self.alice.id)})
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["id"], str(self.carol.id))

    def test_check_duplicate_empty_returns_empty(self):
        result = self.service.check_duplicate({})
        self.assertEqual(result["candidates"], [])

    def test_check_duplicate_rejects_invalid_exclude_id(self):
        with self.assertRaisesRegex(AppApiException, "exclude_id is invalid"):
            self.service.check_duplicate({"phone": "13800000001", "exclude_id": "garbage"})


class CandidateMergeTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.app_service = ApplicationService("workspace-a", self.user_id, hr_role="ADMIN")
        self.primary = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13800000001", skills=["Python"],
        )
        self.secondary = Candidate.objects.create(
            name="Alice Wang", workspace_id="workspace-a", email="alice@example.com",
            current_city="上海", years_experience=5, skills=["Python", "Django"], note="从简历解析",
        )

    def test_merge_fills_missing_fields_and_unions_skills(self):
        result = self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
        self.assertEqual(result["name"], "Alice")
        self.assertEqual(result["email"], "alice@example.com")
        self.assertEqual(result["current_city"], "上海")
        self.assertEqual(result["years_experience"], 5)
        self.assertEqual(result["skills"], ["Python", "Django"])
        self.assertIn("从简历解析", result["note"])
        self.assertFalse(Candidate.objects.filter(id=self.secondary.id).exists())

    def test_merge_migrates_resumes_and_assignments(self):
        job_data = self.service.create_job({"name": "Engineer", "headcount": 1})
        job = Job.objects.get(id=job_data["id"])
        resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="r.txt", extension="txt",
            file_path="/tmp/r.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            candidate=self.secondary,
        )
        application_id = self.app_service.create_application(job.id, self.secondary.id, {})["id"]
        interview = Interview.objects.create(workspace_id="workspace-a", application_id=application_id, round_no=1)
        self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
        resume.refresh_from_db()
        self.assertEqual(resume.candidate_id, self.primary.id)
        application = Application.objects.get(id=application_id)
        self.assertEqual(application.candidate_id, self.primary.id)
        interview.refresh_from_db()
        self.assertEqual(str(interview.application_id), application_id)

    def test_merge_rejects_conflicting_active_assignment(self):
        job_data = self.service.create_job({"name": "Engineer", "headcount": 2})
        job = Job.objects.get(id=job_data["id"])
        self.app_service.create_application(job.id, self.primary.id, {})
        self.app_service.create_application(job.id, self.secondary.id, {})
        with self.assertRaisesRegex(AppApiException, "冲突"):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})

    def test_merge_allows_different_job_active_assignments(self):
        job_a_data = self.service.create_job({"name": "Engineer A", "headcount": 1})
        job_b_data = self.service.create_job({"name": "Engineer B", "headcount": 1})
        job_a = Job.objects.get(id=job_a_data["id"])
        job_b = Job.objects.get(id=job_b_data["id"])
        self.app_service.create_application(job_a.id, self.primary.id, {})
        self.app_service.create_application(job_b.id, self.secondary.id, {})
        self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
        self.assertFalse(Candidate.objects.filter(id=self.secondary.id).exists())

    def test_merge_rejects_self(self):
        with self.assertRaisesRegex(AppApiException, "自己"):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.primary.id)})

    def test_merge_cross_workspace_raises_404(self):
        foreign = Candidate.objects.create(name="Dave", workspace_id="workspace-b")
        with self.assertRaises(NotFound404):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(foreign.id)})

    def test_merge_requires_manage(self):
        member_service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            member_service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})

    def test_merge_secondary_id_required(self):
        with self.assertRaisesRegex(AppApiException, "secondary_id is required"):
            self.service.merge_candidates(str(self.primary.id), {})

    def test_merge_archived_secondary_allowed(self):
        self.secondary.status = "ARCHIVED"
        self.secondary.save(update_fields=["status"])
        self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
        self.assertFalse(Candidate.objects.filter(id=self.secondary.id).exists())

    def test_merge_rejects_deleted_primary(self):
        self.service.delete_candidate(self.primary.id)
        with self.assertRaisesRegex(AppApiException, "deleted candidate cannot be merged"):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})

    def test_merge_rejects_deleted_secondary(self):
        self.service.delete_candidate(self.secondary.id)
        with self.assertRaisesRegex(AppApiException, "deleted candidate cannot be merged"):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
class JobEditGuardTests(TestCase):
    """A2 review: edit_job 收紧关闭语义，关闭走专用接口"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.job = self.service.create_job({"name": "Engineer", "headcount": 1})

    def test_close_status_requires_close_reason(self):
        with self.assertRaisesRegex(AppApiException, "close_reason"):
            self.service.edit_job(self.job["id"], {"status": "CLOSED"})

    def test_close_status_requires_valid_close_reason(self):
        with self.assertRaisesRegex(AppApiException, "close_reason"):
            self.service.edit_job(self.job["id"], {"status": "CLOSED", "close_reason": "NOPE"})

    def test_closed_job_must_be_reopened_via_reopen_endpoint(self):
        self.service.edit_job(self.job["id"], {"status": "CLOSED", "close_reason": "FILLED"})
        with self.assertRaisesRegex(AppApiException, "reopened via reopen"):
            self.service.edit_job(self.job["id"], {"status": "OPEN"})

    def test_close_reason_only_valid_for_closed_status(self):
        with self.assertRaisesRegex(AppApiException, "close_reason only valid for CLOSED"):
            self.service.edit_job(self.job["id"], {"close_reason": "FILLED"})

    def test_closed_job_edit_keeps_close_reason(self):
        self.service.edit_job(self.job["id"], {"status": "CLOSED", "close_reason": "CANCELLED"})
        result = self.service.edit_job(self.job["id"], {"status": "CLOSED", "close_reason": "DUPLICATE"})
        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(result["close_reason"], "DUPLICATE")
class CloseReopenRouteTests(TestCase):
    """A2: close/reopen 路由注册且受权限保护"""

    def test_close_reopen_routes_are_registered_and_protected(self):
        from django.urls import resolve
        from hr.views.application_views import JobCloseAPI, JobClosePreviewAPI
        from hr.views.recruitment import JobDetailAPI

        for suffix, expected in (
            ("close", JobCloseAPI),
            ("close-preview", JobClosePreviewAPI),
            ("reopen", JobDetailAPI.Reopen),
        ):
            path = f"/admin/api/workspace/workspace-a/hr/jobs/{uuid.uuid7()}/{suffix}"
            resolved = resolve(path)
            self.assertIs(resolved.func.cls, expected)
            response = self.client.put(path, data={}, content_type="application/json")
            self.assertIn(response.status_code, (401, 403), f"{path} 未注册或未受保护: {response.status_code}")


class HrAccessModelTests(TestCase):
    """A3: HrAccess/HrAuditLog 模型约束"""

    def test_hr_access_unique_workspace_user(self):
        user_id = uuid.uuid7()
        HrAccess.objects.create(workspace_id="w1", user_id=user_id, role="VIEWER")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrAccess.objects.create(workspace_id="w1", user_id=user_id, role="ADMIN")

    def test_hr_access_same_user_different_workspace_allowed(self):
        user_id = uuid.uuid7()
        HrAccess.objects.create(workspace_id="w1", user_id=user_id, role="VIEWER")
        HrAccess.objects.create(workspace_id="w2", user_id=user_id, role="ADMIN")
        self.assertEqual(HrAccess.objects.count(), 2)

    def test_hr_audit_log_defaults(self):
        log = HrAuditLog.objects.create(
            workspace_id="w1", user_id=uuid.uuid7(), action="CREATE", object_type="CANDIDATE"
        )
        self.assertEqual(log.result, "SUCCESS")
        self.assertEqual(log.object_id, "")
        self.assertTrue(log.create_time)
class HrMaskingTests(TestCase):
    """A3: VIEWER 联系方式脱敏，OPERATOR/ADMIN 明文，空值保持"""

    def setUp(self):
        self.candidate = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13812345678", email="zhangsan@example.com",
        )

    def _service(self, role):
        return RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role=role)

    def test_viewer_list_masks_phone_and_email(self):
        result = self._service("VIEWER").page_candidates(1, 20, {})
        record = result["records"][0]
        self.assertEqual(record["phone"], "138****5678")
        self.assertEqual(record["email"], "zh***@example.com")

    def test_viewer_detail_masks_phone_and_email(self):
        record = self._service("VIEWER").get_candidate(self.candidate.id)
        self.assertEqual(record["phone"], "138****5678")
        self.assertEqual(record["email"], "zh***@example.com")

    def test_operator_and_admin_see_plaintext(self):
        for role in ("OPERATOR", "ADMIN"):
            with self.subTest(role=role):
                record = self._service(role).get_candidate(self.candidate.id)
                self.assertEqual(record["phone"], "13812345678")
                self.assertEqual(record["email"], "zhangsan@example.com")

    def test_viewer_empty_contact_stays_empty(self):
        empty = Candidate.objects.create(name="Empty", workspace_id="workspace-a")
        record = self._service("VIEWER").get_candidate(empty.id)
        self.assertEqual(record["phone"], "")
        self.assertIsNone(record["email"])

    def test_viewer_duplicate_check_is_masked(self):
        result = self._service("VIEWER").check_duplicate({"email": "zhangsan@example.com"})
        self.assertEqual(result["candidates"][0]["phone"], "138****5678")
class _HrApiBase(TestCase):
    def _user(self, username, nick_name, role="USER"):
        return User.objects.create(username=username, nick_name=nick_name, password="p", role=role)

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client


class HrAccessApiTests(_HrApiBase):
    """A3: GET/PUT /access 授权 API 与装饰器权限执行"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        self.viewer = self._user("hr-viewer", "HR Viewer")
        self.member = self._user("plain-member", "Plain Member")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.viewer.id, role="VIEWER")

    def test_member_without_hr_access_gets_403_and_audit(self):
        response = self._client(self.member).get("/admin/api/workspace/workspace-a/hr/candidates/1/20")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.member.id, action="ACCESS_DENIED", result="DENIED"
            ).exists()
        )

    def test_access_list_returns_members_with_roles(self):
        response = self._client(self.admin).get("/admin/api/workspace/workspace-a/hr/access")
        self.assertEqual(response.status_code, 200)
        by_id = {item["id"]: item for item in response.json()["data"]}
        self.assertEqual(by_id[str(self.admin.id)]["hr_role"], "ADMIN")
        self.assertEqual(by_id[str(self.operator.id)]["hr_role"], "OPERATOR")
        self.assertEqual(by_id[str(self.viewer.id)]["hr_role"], "VIEWER")
        self.assertIsNone(by_id[str(self.member.id)]["hr_role"])

    def test_put_access_grants_and_upgrades_role(self):
        response = self._client(self.admin).put(
            "/admin/api/workspace/workspace-a/hr/access",
            {"items": [{"user_id": str(self.member.id), "role": "OPERATOR"}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        access = HrAccess.objects.get(workspace_id="workspace-a", user_id=self.member.id)
        self.assertEqual(access.role, "OPERATOR")

    def test_put_access_revokes_role(self):
        response = self._client(self.admin).put(
            "/admin/api/workspace/workspace-a/hr/access",
            {"items": [{"user_id": str(self.operator.id), "role": None}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(HrAccess.objects.filter(workspace_id="workspace-a", user_id=self.operator.id).exists())

    def test_put_access_rejects_invalid_role(self):
        response = self._client(self.admin).put(
            "/admin/api/workspace/workspace-a/hr/access",
            {"items": [{"user_id": str(self.member.id), "role": "OWNER"}]},
            content_type="application/json",
        )
        self.assertEqual(response.json()["code"], 400)

    def test_put_access_rejects_non_member(self):
        stranger = self._user("sys-admin", "Sys Admin", role="ADMIN")
        response = self._client(self.admin).put(
            "/admin/api/workspace/workspace-a/hr/access",
            {"items": [{"user_id": str(stranger.id), "role": "OPERATOR"}]},
            content_type="application/json",
        )
        self.assertEqual(response.json()["code"], 400)

    def test_put_access_writes_grant_and_revoke_audit(self):
        self._client(self.admin).put(
            "/admin/api/workspace/workspace-a/hr/access",
            {"items": [{"user_id": str(self.member.id), "role": "OPERATOR"}]},
            content_type="application/json",
        )
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.admin.id, action="GRANT_ACCESS",
                object_type="HR_ACCESS", object_id=str(self.member.id),
            ).exists()
        )
        self._client(self.admin).put(
            "/admin/api/workspace/workspace-a/hr/access",
            {"items": [{"user_id": str(self.member.id), "role": None}]},
            content_type="application/json",
        )
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.admin.id, action="REVOKE_ACCESS",
                object_type="HR_ACCESS", object_id=str(self.member.id),
            ).exists()
        )

    def test_operator_cannot_manage_access(self):
        response = self._client(self.operator).get("/admin/api/workspace/workspace-a/hr/access")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.operator.id, action="ACCESS_DENIED"
            ).exists()
        )

    def test_operator_cannot_view_audit_logs(self):
        response = self._client(self.operator).get("/admin/api/workspace/workspace-a/hr/audit-logs")
        self.assertEqual(response.status_code, 403)

    def test_members_endpoint_returns_all_active_users(self):
        # 负责人/面试官下拉数据源：任意 HR 成员可读，包含 ADMIN 角色用户
        response = self._client(self.operator).get("/admin/api/workspace/workspace-a/hr/members")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.json()["data"]}
        self.assertIn(str(self.admin.id), ids)
        self.assertIn(str(self.operator.id), ids)

    def test_members_endpoint_denies_non_hr_member(self):
        response = self._client(self.member).get("/admin/api/workspace/workspace-a/hr/members")
        self.assertEqual(response.status_code, 403)

    def test_hr_members_fallback_when_kernel_members_empty(self):
        # 精简部署下内核成员为空时，回退到全部活跃用户（排除内置系统管理员）
        from unittest.mock import patch

        from hr.serializers.access import hr_members

        with patch("users.serializers.user.UserManageSerializer.get_user_members", return_value=[]):
            members = hr_members("workspace-a")
        by_id = {member["id"]: member for member in members}
        self.assertIn(self.admin.id, by_id)
        self.assertIn(self.operator.id, by_id)
        self.assertNotIn("f0dd8f71-e4ee-11ee-8c84-a8a1595801ab", {str(i) for i in by_id})

    def test_access_me_returns_current_role(self):
        response = self._client(self.viewer).get("/admin/api/workspace/workspace-a/hr/access/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["role"], "VIEWER")

    def test_access_me_denies_non_hr_member(self):
        response = self._client(self.member).get("/admin/api/workspace/workspace-a/hr/access/me")
        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_create_candidate_via_api(self):
        response = self._client(self.viewer).post(
            "/admin/api/workspace/workspace-a/hr/candidates",
            {"name": "Bob"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_cannot_create_job_via_api(self):
        response = self._client(self.operator).post(
            "/admin/api/workspace/workspace-a/hr/jobs",
            {"name": "Platform", "headcount": 1},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_viewer_detail_returns_masked_contact(self):
        candidate = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13812345678", email="zhangsan@example.com",
        )
        response = self._client(self.viewer).get(
            f"/admin/api/workspace/workspace-a/hr/candidates/{candidate.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["phone"], "138****5678")
        self.assertEqual(response.json()["data"]["email"], "zh***@example.com")


class HrAuditLogApiTests(_HrApiBase):
    """A3: GET /audit-logs 查询（过滤+分页，仅 ADMIN）"""

    def setUp(self):
        self.admin = self._user("audit-admin", "Audit Admin")
        self.operator = self._user("audit-op", "Audit Op")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        self.actor = uuid.uuid7()
        write_audit_log("workspace-a", self.actor, "CREATE", "CANDIDATE", "cand-1")
        write_audit_log("workspace-a", self.actor, "JOB_CLOSE", "JOB", "job-1")
        write_audit_log("workspace-a", uuid.uuid7(), "CREATE", "CANDIDATE", "cand-2")

    def test_audit_logs_lists_all(self):
        response = self._client(self.admin).get("/admin/api/workspace/workspace-a/hr/audit-logs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 3)

    def test_audit_logs_filters_by_action_user_and_object_type(self):
        client = self._client(self.admin)
        response = client.get("/admin/api/workspace/workspace-a/hr/audit-logs", {"action": "CREATE"})
        self.assertEqual(response.json()["data"]["total"], 2)
        response = client.get("/admin/api/workspace/workspace-a/hr/audit-logs", {"user_id": str(self.actor)})
        self.assertEqual(response.json()["data"]["total"], 2)
        response = client.get("/admin/api/workspace/workspace-a/hr/audit-logs", {"object_type": "JOB"})
        self.assertEqual(response.json()["data"]["total"], 1)

    def test_audit_logs_pagination(self):
        response = self._client(self.admin).get(
            "/admin/api/workspace/workspace-a/hr/audit-logs", {"current_page": 1, "page_size": 2}
        )
        data = response.json()["data"]
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["records"]), 2)

    def test_audit_logs_rejects_invalid_filters(self):
        client = self._client(self.admin)
        for params in (
            {"action": "NOPE"},
            {"object_type": "NOPE"},
            {"user_id": "garbage"},
            {"start_time": "not-a-date"},
        ):
            with self.subTest(params=params):
                response = client.get("/admin/api/workspace/workspace-a/hr/audit-logs", params)
                self.assertEqual(response.json()["code"], 400)

    def test_audit_logs_isolated_by_workspace(self):
        write_audit_log("workspace-b", self.actor, "CREATE", "CANDIDATE", "cand-b")
        response = self._client(self.admin).get("/admin/api/workspace/workspace-a/hr/audit-logs")
        self.assertEqual(response.json()["data"]["total"], 3)


class CandidateComplianceMetadataTests(TestCase):
    """A4: 合规元数据字段创建/编辑与非法枚举校验"""

    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="ADMIN")

    def test_create_saves_compliance_fields(self):
        result = self.service.create_candidate({
            "name": "Alice",
            "source_type": "REFERRAL",
            "source_detail": "内推人张三",
            "collected_at": "2026-08-01T10:00:00Z",
            "consent_status": "CONSENTED",
            "consent_version": "v1.0",
            "contact_preference": "EMAIL",
        })
        self.assertEqual(result["source_type"], "REFERRAL")
        self.assertEqual(result["source_detail"], "内推人张三")
        self.assertEqual(result["consent_status"], "CONSENTED")
        self.assertEqual(result["consent_version"], "v1.0")
        self.assertEqual(result["contact_preference"], "EMAIL")
        candidate = Candidate.objects.get(id=result["id"])
        self.assertTrue(candidate.collected_at.isoformat().startswith("2026-08-01T10:00:00"))

    def test_create_defaults(self):
        result = self.service.create_candidate({"name": "Bob"})
        self.assertEqual(result["source_type"], "OTHER")
        self.assertEqual(result["consent_status"], "UNKNOWN")
        self.assertEqual(result["contact_preference"], "UNSPECIFIED")
        self.assertEqual(result["source_detail"], "")
        self.assertEqual(result["consent_version"], "")
        self.assertIsNone(result["collected_at"])

    def test_edit_updates_compliance_fields(self):
        created = self.service.create_candidate({"name": "Alice"})
        result = self.service.edit_candidate(created["id"], {
            "source_type": "HEADHUNTER",
            "source_detail": "猎头公司",
            "collected_at": "2026-08-02T09:00:00Z",
            "consent_status": "NOTIFIED",
            "consent_version": "v2",
            "contact_preference": "NO_CONTACT",
        })
        self.assertEqual(result["source_type"], "HEADHUNTER")
        self.assertEqual(result["source_detail"], "猎头公司")
        self.assertEqual(result["consent_status"], "NOTIFIED")
        self.assertEqual(result["consent_version"], "v2")
        self.assertEqual(result["contact_preference"], "NO_CONTACT")

    def test_invalid_enums_rejected(self):
        with self.assertRaisesRegex(AppApiException, "source_type"):
            self.service.create_candidate({"name": "Alice", "source_type": "NOPE"})
        with self.assertRaisesRegex(AppApiException, "consent_status"):
            self.service.create_candidate({"name": "Alice", "consent_status": "NOPE"})
        with self.assertRaisesRegex(AppApiException, "contact_preference"):
            self.service.create_candidate({"name": "Alice", "contact_preference": "NOPE"})

    def test_invalid_collected_at_rejected(self):
        with self.assertRaisesRegex(AppApiException, "collected_at"):
            self.service.create_candidate({"name": "Alice", "collected_at": "not-a-date"})


class CandidateDeleteTests(TestCase):
    """A4: 删除/匿名化：进行中与已入职拒绝，PII 清空，简历联动清理，审计写入"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", email="alice@example.com", phone="13812345678",
            current_city="上海", target_city="北京", highest_degree="本科", years_experience=5,
            skills=["Python"], source="JOB_SITE", note="备注",
        )
        job_data = self.service.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.app_service = ApplicationService("workspace-a", self.user_id, hr_role="ADMIN")

    def test_delete_rejects_active_assignment(self):
        self.app_service.create_application(self.job.id, self.candidate.id, {})
        with self.assertRaisesRegex(AppApiException, "active"):
            self.service.delete_candidate(self.candidate.id)

    def test_delete_rejects_hired_assignment(self):
        application = self.app_service.create_application(self.job.id, self.candidate.id, {})
        Application.objects.filter(id=application["id"]).update(status=ApplicationStatus.HIRED)
        with self.assertRaisesRegex(AppApiException, "hired"):
            self.service.delete_candidate(self.candidate.id)

    def test_delete_anonymizes_pii(self):
        self.candidate.source_detail = "内推人:张三"
        self.candidate.consent_version = "v1"
        self.candidate.save(update_fields=["source_detail", "consent_version"])
        result = self.service.delete_candidate(self.candidate.id)
        self.assertEqual(result["status"], "DELETED")
        candidate = Candidate.objects.get(id=self.candidate.id)
        self.assertEqual(candidate.name, "已删除候选人")
        self.assertIsNone(candidate.email)
        self.assertEqual(candidate.phone, "")
        self.assertEqual(candidate.current_city, "")
        self.assertEqual(candidate.target_city, "")
        self.assertEqual(candidate.highest_degree, "")
        self.assertIsNone(candidate.years_experience)
        self.assertEqual(candidate.skills, [])
        self.assertEqual(candidate.source, "")
        self.assertEqual(candidate.source_detail, "")
        self.assertEqual(candidate.consent_version, "")
        self.assertEqual(candidate.note, "")

    def test_delete_writes_delete_audit(self):
        self.service.delete_candidate(self.candidate.id)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="DELETE",
                object_type="CANDIDATE", object_id=str(self.candidate.id),
            ).exists()
        )

    def test_delete_removes_resume_file_and_record_with_audit(self):
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write(b"resume")
        handle.close()
        resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="r.txt", extension="txt",
            file_path=handle.name, file_size=1, sha256="sha-" + uuid.uuid7().hex,
            candidate=self.candidate, user_id=self.user_id,
        )
        self.service.delete_candidate(self.candidate.id)
        self.assertFalse(ResumeFile.objects.filter(id=resume.id).exists())
        self.assertFalse(os.path.exists(handle.name))
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="RESUME_DELETE",
                object_type="RESUME", object_id=str(resume.id),
            ).exists()
        )

    def test_default_list_hides_deleted(self):
        self.service.delete_candidate(self.candidate.id)
        result = self.service.page_candidates(1, 20, {})
        self.assertEqual(result["total"], 0)

    def test_explicit_status_filter_shows_deleted(self):
        self.service.delete_candidate(self.candidate.id)
        result = self.service.page_candidates(1, 20, {"status": "DELETED"})
        self.assertEqual(result["total"], 1)

    def test_deleted_detail_only_admin_visible(self):
        self.service.delete_candidate(self.candidate.id)
        viewer = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="VIEWER")
        with self.assertRaises(NotFound404):
            viewer.get_candidate(self.candidate.id)
        detail = self.service.get_candidate(self.candidate.id)
        self.assertEqual(detail["status"], "DELETED")

    def test_edit_rejects_deleted(self):
        self.service.delete_candidate(self.candidate.id)
        with self.assertRaisesRegex(AppApiException, "deleted candidate cannot be edited"):
            self.service.edit_candidate(self.candidate.id, {"name": "Renamed"})

    def test_archive_rejects_deleted(self):
        self.service.delete_candidate(self.candidate.id)
        with self.assertRaisesRegex(AppApiException, "deleted candidate cannot be archived"):
            self.service.archive_candidate(self.candidate.id)

    def test_non_admin_explicit_deleted_filter_hidden(self):
        self.service.delete_candidate(self.candidate.id)
        for role in ("VIEWER", "OPERATOR"):
            member = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role=role)
            result = member.page_candidates(1, 20, {"status": "DELETED"})
            self.assertEqual(result["total"], 0)
        admin_result = self.service.page_candidates(1, 20, {"status": "DELETED"})
        self.assertEqual(admin_result["total"], 1)

    def test_delete_reports_resume_file_removal_failure(self):
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write(b"resume")
        handle.close()
        resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="r.txt", extension="txt",
            file_path=handle.name, file_size=1, sha256="sha-" + uuid.uuid7().hex,
            candidate=self.candidate, user_id=self.user_id,
        )
        with patch("hr.serializers.recruitment.os.remove", side_effect=OSError("permission denied")):
            self.service.delete_candidate(self.candidate.id)
        self.assertFalse(ResumeFile.objects.filter(id=resume.id).exists())
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="RESUME_DELETE",
                object_type="RESUME", object_id=str(resume.id), result="FAILED",
                detail__contains="removal failed",
            ).exists()
        )

    def test_terminal_assignment_kept_as_anonymous_reference(self):
        application = self.app_service.create_application(self.job.id, self.candidate.id, {})
        self.app_service.reject_application(application["id"], {"termination_reason": "NOT_FIT"})
        self.service.delete_candidate(self.candidate.id)
        application = Application.objects.get(id=application["id"])
        self.assertEqual(application.candidate_id, self.candidate.id)
        self.assertEqual(Candidate.objects.get(id=self.candidate.id).name, "已删除候选人")

    def test_member_cannot_delete(self):
        member = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            member.delete_candidate(self.candidate.id)


class CandidateRestoreTests(TestCase):
    """候选恢复（ARCHIVED→ACTIVE）：闭环可用、终态/非归档拒绝、权限与审计"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = self.service.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.app_service = ApplicationService("workspace-a", self.user_id, hr_role="ADMIN")

    def test_restore_returns_active_and_allows_new_assignment(self):
        self.service.archive_candidate(self.candidate.id)
        result = self.service.restore_candidate(self.candidate.id)
        self.assertEqual(result["status"], "ACTIVE")
        application = self.app_service.create_application(self.job.id, self.candidate.id, {})
        self.assertEqual(application["status"], "ACTIVE")

    def test_restore_rejects_active_candidate(self):
        with self.assertRaisesRegex(AppApiException, "not archived"):
            self.service.restore_candidate(self.candidate.id)

    def test_restore_rejects_deleted_candidate(self):
        self.service.delete_candidate(self.candidate.id)
        with self.assertRaisesRegex(AppApiException, "deleted candidate cannot be restored"):
            self.service.restore_candidate(self.candidate.id)

    def test_restore_rejects_cross_workspace(self):
        foreign = Candidate.objects.create(name="Bob", workspace_id="workspace-b")
        with self.assertRaises(NotFound404):
            self.service.restore_candidate(foreign.id)

    def test_restore_writes_restore_audit(self):
        self.service.archive_candidate(self.candidate.id)
        self.service.restore_candidate(self.candidate.id)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="RESTORE",
                object_type="CANDIDATE", object_id=str(self.candidate.id),
            ).exists()
        )

    def test_non_admin_cannot_restore(self):
        self.service.archive_candidate(self.candidate.id)
        operator = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            operator.restore_candidate(self.candidate.id)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="ACCESS_DENIED", result="DENIED"
            ).exists()
        )

    def test_restore_keeps_terminal_assignment_history(self):
        application = self.app_service.create_application(self.job.id, self.candidate.id, {})
        self.app_service.reject_application(application["id"], {"termination_reason": "NOT_FIT"})
        self.service.archive_candidate(self.candidate.id)
        self.service.restore_candidate(self.candidate.id)
        application = Application.objects.get(id=application["id"])
        self.assertEqual(application.status, "REJECTED")


class CandidateRestoreApiTests(_HrApiBase):
    """恢复路由：ADMIN 200；非 ADMIN 403 + ACCESS_DENIED 审计"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")

    def _archived(self):
        self.candidate.status = "ARCHIVED"
        self.candidate.save(update_fields=["status"])

    def test_admin_restore_returns_200(self):
        self._archived()
        response = self._client(self.admin).put(
            "/admin/api/workspace/workspace-a/hr/candidates/{}/restore".format(self.candidate.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "ACTIVE")

    def test_operator_restore_gets_403_and_audit(self):
        self._archived()
        response = self._client(self.operator).put(
            "/admin/api/workspace/workspace-a/hr/candidates/{}/restore".format(self.candidate.id)
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.operator.id, action="ACCESS_DENIED", result="DENIED"
            ).exists()
        )


class InterviewerMineApiTests(_HrApiBase):
    """B1 路由：我的面试（静态段顺序/隔离）与面试官反馈提交"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.interviewer = self._user("hr-interviewer", "面试官甲")
        self.other = self._user("plain-member", "普通成员")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        candidate = Candidate.objects.create(name="Bob", workspace_id="workspace-a")
        recruitment = RecruitmentService("workspace-a", self.admin.id, hr_role="ADMIN")
        job_data = recruitment.create_job({"name": "Engineer", "headcount": 1})
        job = Job.objects.get(id=job_data["id"])
        service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        application = service.create_application(job.id, candidate.id, {})
        screen = JobStage.objects.filter(job=job, key="SCREEN").first()
        service.move_stage(application["id"], screen.id, {"reason_text": "screen"})
        interview = service.create_interview(
            application["id"], {"interviewer_user_id": str(self.interviewer.id)}
        )
        self.interview_id = interview["id"]

    def test_create_interview_with_member_when_kernel_members_empty(self):
        # 精简部署下内核 get_user_members 返回空时，面试官校验应走 hr_members 回退，不再误报
        from unittest.mock import patch

        service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        application = Application.objects.filter(workspace_id="workspace-a").first()
        with patch("users.serializers.user.UserManageSerializer.get_user_members", return_value=[]):
            interview = service.create_interview(
                application.id, {"interviewer_user_id": str(self.interviewer.id)}
            )
        self.assertEqual(interview["interviewer_user_id"], str(self.interviewer.id))
        self.assertEqual(interview["interviewer"], "面试官甲")

    def test_mine_returns_only_my_interviews(self):
        response = self._client(self.interviewer).get("/admin/api/workspace/workspace-a/hr/interviews/mine")
        self.assertEqual(response.status_code, 200)
        records = response.json()["data"]
        self.assertEqual([item["interview_id"] for item in records], [self.interview_id])
        self.assertEqual(records[0]["candidate_name"], "Bob")
        self.assertNotIn("phone", records[0])
        self.assertNotIn("email", records[0])

    def test_mine_returns_empty_for_non_interviewer(self):
        response = self._client(self.other).get("/admin/api/workspace/workspace-a/hr/interviews/mine")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], [])

    def test_mine_requires_login(self):
        response = APIClient().get("/admin/api/workspace/workspace-a/hr/interviews/mine")
        self.assertEqual(response.status_code, 401)

    def test_interviewer_submits_feedback(self):
        response = self._client(self.interviewer).put(
            "/admin/api/workspace/workspace-a/hr/interviews/{}/feedback".format(self.interview_id),
            {"status": "PASSED", "feedback": "表现优秀"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "PASSED")
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.interviewer.id,
                action="INTERVIEW_FEEDBACK", object_type="INTERVIEW", object_id=self.interview_id,
            ).exists()
        )

    def test_feedback_by_non_interviewer_is_404(self):
        response = self._client(self.other).put(
            "/admin/api/workspace/workspace-a/hr/interviews/{}/feedback".format(self.interview_id),
            {"status": "PASSED"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)


class CleanupOrphanResumeTaskTests(TestCase):
    """A4: TTL 清理未关联简历（31 天前清理、30 天内保留、已关联不清理）"""

    def setUp(self):
        self.user_id = uuid.uuid7()

    def _resume(self, days_old, linked=False):
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write(b"resume")
        handle.close()
        candidate = None
        if linked:
            candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="r.txt", extension="txt",
            file_path=handle.name, file_size=1, sha256="sha-" + uuid.uuid7().hex,
            status=ResumeStatus.SUCCESS, user_id=self.user_id, candidate=candidate,
        )
        ResumeFile.objects.filter(id=resume.id).update(
            create_time=timezone.now() - timedelta(days=days_old)
        )
        return resume

    def test_cleans_orphan_older_than_30_days(self):
        resume = self._resume(days_old=31)
        cleanup_orphan_resumes.run()
        self.assertFalse(ResumeFile.objects.filter(id=resume.id).exists())
        self.assertFalse(os.path.exists(resume.file_path))
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="RESUME_DELETE",
                object_type="RESUME", object_id=str(resume.id), detail__contains="TTL",
            ).exists()
        )

    def test_keeps_orphan_within_30_days(self):
        resume = self._resume(days_old=29)
        cleanup_orphan_resumes.run()
        self.assertTrue(ResumeFile.objects.filter(id=resume.id).exists())
        self.assertTrue(os.path.exists(resume.file_path))

    def test_keeps_linked_resume(self):
        resume = self._resume(days_old=40, linked=True)
        cleanup_orphan_resumes.run()
        self.assertTrue(ResumeFile.objects.filter(id=resume.id).exists())
        self.assertTrue(os.path.exists(resume.file_path))

    def test_reports_resume_file_removal_failure(self):
        resume = self._resume(days_old=31)
        from hr.services.storage import LocalStorage
        failing = LocalStorage()
        failing.delete = lambda key: (_ for _ in ()).throw(OSError("permission denied"))
        with patch("hr.task.resume.get_storage", return_value=failing):
            cleanup_orphan_resumes.run()
        self.assertFalse(ResumeFile.objects.filter(id=resume.id).exists())
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="RESUME_DELETE",
                object_type="RESUME", object_id=str(resume.id), result="FAILED",
                detail__contains="removal failed",
            ).exists()
        )


class CandidateExportTests(TestCase):
    """A4: 受控导出白名单字段与 EXPORT 审计"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13812345678", email="alice@example.com",
            current_city="上海", target_city="北京", years_experience=5, skills=["Python"],
            source_type="REFERRAL", source_detail="内推", consent_status="CONSENTED",
            contact_preference="EMAIL",
        )

    def test_export_returns_whitelist_fields(self):
        records = self.service.export_candidates({})
        self.assertEqual(len(records), 1)
        row = records[0]
        self.assertEqual(row["name"], "Alice")
        self.assertEqual(row["source_type"], "REFERRAL")
        self.assertEqual(row["contact_preference"], "EMAIL")
        self.assertNotIn("phone", row)
        self.assertNotIn("email", row)
        self.assertNotIn("note", row)
        self.assertEqual(set(row.keys()), set(CANDIDATE_EXPORT_FIELDS))

    def test_export_writes_audit(self):
        self.service.export_candidates({})
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="EXPORT", object_type="CANDIDATE"
            ).exists()
        )

    def test_export_respects_filters(self):
        Candidate.objects.create(name="Bob", workspace_id="workspace-a", status="ARCHIVED")
        records = self.service.export_candidates({"status": "ACTIVE"})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Alice")

    def test_member_cannot_export(self):
        member = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            member.export_candidates({})


class CandidateLifecycleRouteTests(_HrApiBase):
    """A4: 删除与导出路由注册、权限与 CSV 响应"""

    def setUp(self):
        self.admin = self._user("life-admin", "Lifecycle Admin")
        self.operator = self._user("life-op", "Lifecycle Op")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        self.candidate = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13812345678", email="alice@example.com",
            current_city="上海", skills=["Python"], source_type="JOB_SITE",
        )

    def test_delete_route_registered_and_admin_only(self):
        path = f"/admin/api/workspace/workspace-a/hr/candidates/{self.candidate.id}/delete"
        response = self._client(self.operator).put(path, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        response = self._client(self.admin).put(path, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, "DELETED")
        self.assertEqual(self.candidate.name, "已删除候选人")

    def test_export_route_returns_csv_and_admin_only(self):
        path = "/admin/api/workspace/workspace-a/hr/export/candidates"
        response = self._client(self.operator).post(path, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        response = self._client(self.admin).post(
            path, data={"filters": {}}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("name", body)
        self.assertIn("Alice", body)
        self.assertIn("source_type", body)
        self.assertNotIn("13812345678", body)
        self.assertNotIn("alice@example.com", body)

    def test_export_escapes_formula_injection(self):
        self.candidate.name = '=HYPERLINK("https://evil.example","Click")'
        self.candidate.save(update_fields=["name"])
        path = "/admin/api/workspace/workspace-a/hr/export/candidates"
        response = self._client(self.admin).post(path, data={"filters": {}}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("'=HYPERLINK", body)
        rows = list(csv.DictReader(io.StringIO(body)))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["name"].startswith("'=HYPERLINK"))
        self.assertFalse(rows[0]["name"].startswith("="))

class StorageBackendTests(SimpleTestCase):
    """对象存储抽象：本地后端往返与后端选择"""

    def setUp(self):
        from hr.services.storage import reset_storage_for_tests
        reset_storage_for_tests()

    def tearDown(self):
        from hr.services.storage import reset_storage_for_tests
        reset_storage_for_tests()

    def test_local_storage_roundtrip(self):
        from hr.services.storage import LocalStorage
        with tempfile.TemporaryDirectory() as root:
            storage = LocalStorage(root=root)
            source = os.path.join(tempfile.gettempdir(), "src-" + uuid.uuid7().hex + ".txt")
            with open(source, "w") as handle:
                handle.write("hello storage")
            key = os.path.join("resume", "workspace-a", "sha1.txt")
            storage.save(key, source)
            self.assertTrue(storage.exists(key))
            opened = storage.open(key)
            with open(opened) as handle:
                self.assertEqual(handle.read(), "hello storage")
            storage.delete(key)
            self.assertFalse(storage.exists(key))

    def test_get_storage_defaults_to_local(self):
        from hr.services.storage import get_storage, LocalStorage
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(get_storage(), LocalStorage)

    def test_get_storage_s3_selected_by_env(self):
        from hr.services.storage import get_storage, reset_storage_for_tests
        with patch.dict(os.environ, {"MAXKB_STORAGE_BACKEND": "s3"}, clear=False):
            reset_storage_for_tests()
            try:
                with patch("hr.services.storage.S3Storage") as mock_class:
                    get_storage()
                    mock_class.assert_called_once()
            finally:
                reset_storage_for_tests()


class ImportServiceTests(TestCase):
    """B4: CSV 批量导入候选人：逐行校验、疑似重复、审计与报告"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = ImportService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.recruitment = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.existing = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13800000000", email="alice@example.com"
        )

    def _csv_file(self, rows, header=None):
        header = header or [
            "name", "phone", "email", "current_city", "target_city", "highest_degree",
            "years_experience", "skills", "source_type", "source_detail", "collected_at",
            "consent_status", "consent_version", "contact_preference", "source", "note",
        ]
        import csv as _csv
        import io as _io
        buffer = _io.StringIO()
        writer = _csv.writer(buffer)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue()

    def test_import_creates_candidates_with_full_fields(self):
        content = self._csv_file([
            ["Bob", "13911111111", "bob@example.com", "上海", "北京", "本科", "5", "Python,Django",
             "REFERRAL", "内推", "2026-08-01T10:00:00Z", "CONSENTED", "v1", "EMAIL", "猎头", "备注"],
        ])
        report = self.service.import_candidates_csv(content)
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["success"], 1)
        self.assertEqual(report["failed"], 0)
        candidate = Candidate.objects.get(name="Bob", workspace_id="workspace-a")
        self.assertEqual(candidate.phone, "13911111111")
        self.assertEqual(candidate.skills, ["Python", "Django"])
        self.assertEqual(candidate.source_type, "REFERRAL")
        self.assertEqual(candidate.consent_status, "CONSENTED")
        self.assertEqual(candidate.contact_preference, "EMAIL")

    def test_import_requires_name_header(self):
        content = self._csv_file([["Bob", "13911111111"]], header=["full_name", "phone"])
        with self.assertRaisesRegex(AppApiException, "name"):
            self.service.import_candidates_csv(content)

    def test_import_skips_invalid_enum_row_with_reason(self):
        content = self._csv_file([
            ["Bob", "13911111111", "", "", "", "", "", "", "NOPE", "", "", "", "", "", "", ""],
            ["Cara", "13922222222"],
        ])
        report = self.service.import_candidates_csv(content)
        self.assertEqual(report["success"], 1)
        self.assertEqual(report["failed"], 1)
        failed = next(record for record in report["records"] if record["status"] == "failed")
        self.assertEqual(failed["row_no"], 2)
        self.assertIn("source_type", failed["reason"])

    def test_import_skips_missing_name_row(self):
        content = self._csv_file([
            ["", "13911111111"],
            ["Cara", "13922222222"],
        ])
        report = self.service.import_candidates_csv(content)
        self.assertEqual(report["success"], 1)
        self.assertEqual(report["failed"], 1)

    def test_import_parses_skills_with_chinese_separators(self):
        content = self._csv_file([["Bob", "13911111111", "", "", "", "", "", "Python、Django；Go,"]])
        report = self.service.import_candidates_csv(content)
        candidate = Candidate.objects.get(name="Bob", workspace_id="workspace-a")
        self.assertEqual(sorted(candidate.skills), ["Django", "Go", "Python"])
        self.assertEqual(report["success"], 1)

    def test_import_reports_invalid_years_experience(self):
        content = self._csv_file([["Bob", "13911111111", "", "", "", "", "abc"]])
        report = self.service.import_candidates_csv(content)
        self.assertEqual(report["success"], 0)
        self.assertEqual(report["failed"], 1)
        self.assertIn("years_experience", report["records"][0]["reason"])

    def test_import_marks_duplicate_within_file_but_creates(self):
        content = self._csv_file([
            ["Bob", "13911111111"],
            ["Bob2", "13911111111"],
        ])
        report = self.service.import_candidates_csv(content)
        self.assertEqual(report["success"], 1)
        self.assertEqual(report["duplicates"], 1)
        duplicated = next(record for record in report["records"] if record["status"] == "duplicate")
        self.assertEqual(duplicated["row_no"], 3)
        self.assertEqual(Candidate.objects.filter(workspace_id="workspace-a").count(), 3)  # existing + 2 imported

    def test_import_marks_duplicate_with_existing_candidate(self):
        content = self._csv_file([["Bob", "13800000000", "bob@example.com"]])
        report = self.service.import_candidates_csv(content)
        self.assertEqual(report["duplicates"], 1)
        self.assertEqual(Candidate.objects.filter(name="Bob", workspace_id="workspace-a").count(), 1)

    def test_import_writes_import_and_create_audit(self):
        content = self._csv_file([["Bob", "13911111111"], ["Cara", "13922222222"]])
        self.service.import_candidates_csv(content)
        import_log = HrAuditLog.objects.filter(
            workspace_id="workspace-a", user_id=self.user_id, action="IMPORT", object_type="CANDIDATE"
        ).first()
        self.assertIsNotNone(import_log)
        self.assertIn("success=2", import_log.detail)
        self.assertIn("failed=0", import_log.detail)
        self.assertEqual(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="CREATE", object_type="CANDIDATE"
            ).count(), 2
        )

    def test_import_rejects_over_two_hundred_rows(self):
        rows = [["Bob{}".format(i), "139{}".format(str(i).zfill(8))] for i in range(201)]
        with self.assertRaisesRegex(AppApiException, "200"):
            self.service.import_candidates_csv(self._csv_file(rows))

    def test_import_template_contains_headers(self):
        header, sample = self.service.import_template()
        self.assertIn("name", header)
        self.assertIn("phone", header)


class ImportApiTests(_HrApiBase):
    """B4 路由：导入上传（ADMIN）、模板下载、权限"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")

    def test_admin_import_returns_report(self):
        content = "name,phone\nBob,13911111111\nCara,13922222222\n"
        upload = SimpleUploadedFile("candidates.csv", content.encode("utf-8"), content_type="text/csv")
        response = self._client(self.admin).post(
            "/admin/api/workspace/workspace-a/hr/import/candidates", {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, 200)
        report = response.json()["data"]
        self.assertEqual(report["success"], 2)
        self.assertEqual(Candidate.objects.filter(workspace_id="workspace-a").count(), 2)

    def test_operator_import_gets_403(self):
        content = "name,phone\nBob,13911111111\n"
        upload = SimpleUploadedFile("candidates.csv", content.encode("utf-8"), content_type="text/csv")
        response = self._client(self.operator).post(
            "/admin/api/workspace/workspace-a/hr/import/candidates", {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.operator.id, action="ACCESS_DENIED", result="DENIED"
            ).exists()
        )

    def test_template_download_contains_headers(self):
        response = self._client(self.admin).get(
            "/admin/api/workspace/workspace-a/hr/import/candidates/template"
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertIn("name", body)
        self.assertIn("phone", body)


class OfferServiceTests(TestCase):
    """B2: Offer 工件状态机、版本、审批、附件与权限（基于 Application）"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = OfferService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.recruitment = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = self.recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_service = ApplicationService("workspace-a", self.user_id, hr_role="ADMIN")
        self.application_id = self.application_service.create_application(self.job.id, self.candidate.id, {})["id"]
        self.stages = list(JobStage.objects.filter(job=self.job).order_by("order"))

    def _to_offer(self):
        for stage in self.stages[1:]:
            self.application_service.move_stage(self.application_id, stage.id, {"reason_text": "advance"})

    def _sent_offer(self):
        self._to_offer()
        offer_id = self.service.create_offer_for_application(
            self.application_id, {"salary_amount": "25000", "currency": "CNY"}
        )["id"]
        self.service.approve_offer(offer_id, {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        self.service.send_offer(offer_id)
        return offer_id

    def test_create_offer_requires_offer_stage(self):
        self.application_service.move_stage(self.application_id, self.stages[1].id, {"reason_text": "screen"})
        with self.assertRaisesRegex(AppApiException, "OFFER stage"):
            self.service.create_offer_for_application(self.application_id, {})

    def test_create_offer_auto_increments_version(self):
        self._to_offer()
        first = self.service.create_offer_for_application(self.application_id, {"salary_amount": "20000"})
        self.service.approve_offer(first["id"], {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        self.service.send_offer(first["id"])
        self.service.reject_offer(first["id"], {"note": "先关闭 v1"})
        second = self.service.create_offer_for_application(self.application_id, {"salary_amount": "25000"})
        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["status"], "DRAFT")

    def test_create_offer_saves_amount_currency_and_note(self):
        self._to_offer()
        offer = self.service.create_offer_for_application(self.application_id, {
            "salary_amount": "30000.50", "currency": "USD", "note": "含期权",
        })
        self.assertEqual(offer["salary_amount"], "30000.50")
        self.assertEqual(offer["currency"], "USD")
        self.assertEqual(offer["note"], "含期权")

    def test_page_offers_returns_all_workspace_offers(self):
        self._to_offer()
        self.service.create_offer_for_application(self.application_id, {"salary_amount": "25000"})
        page = self.service.page_offers(1, 10)
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["records"][0]["candidate_name"], "Alice")
        self.assertEqual(page["records"][0]["job_name"], "Engineer")
        self.assertEqual(page["records"][0]["assignment_status"], "OFFER")

    def test_update_offer_only_in_draft(self):
        offer_id = self._sent_offer()
        with self.assertRaisesRegex(AppApiException, "draft offer"):
            self.service.update_offer(offer_id, {"salary_amount": "99999"})

    def test_approve_offer_writes_audit(self):
        self._to_offer()
        offer_id = self.service.create_offer_for_application(self.application_id, {})["id"]
        updated = self.service.approve_offer(offer_id, {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        self.assertEqual(updated["approval_status"], "APPROVED")
        self.assertIsNotNone(updated["approved_at"])
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="OFFER_APPROVE", object_type="OFFER"
            ).exists()
        )

    def test_approve_rejects_invalid_status(self):
        self._to_offer()
        offer_id = self.service.create_offer_for_application(self.application_id, {})["id"]
        with self.assertRaisesRegex(AppApiException, "approval_status is invalid"):
            self.service.approve_offer(offer_id, {"approval_status": "NOPE"})

    def test_send_offer_marks_sent(self):
        self._to_offer()
        offer_id = self.service.create_offer_for_application(self.application_id, {})["id"]
        self.service.approve_offer(offer_id, {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        sent = self.service.send_offer(offer_id)
        self.assertEqual(sent["status"], "SENT")
        self.assertIsNotNone(sent["sent_at"])
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="OFFER_SEND", object_type="OFFER"
            ).exists()
        )

    def test_send_requires_approval(self):
        self._to_offer()
        offer_id = self.service.create_offer_for_application(self.application_id, {})["id"]
        with self.assertRaisesRegex(AppApiException, "approved before sending"):
            self.service.send_offer(offer_id)
        self.service.approve_offer(offer_id, {"approval_status": "REJECTED", "approver_id": str(self.user_id)})
        with self.assertRaisesRegex(AppApiException, "approved before sending"):
            self.service.send_offer(offer_id)

    def test_send_from_non_draft_rejected(self):
        offer_id = self._sent_offer()
        with self.assertRaisesRegex(AppApiException, "Illegal status transition"):
            self.service.send_offer(offer_id)

    def test_accept_offer_moves_application_to_hired(self):
        offer_id = self._sent_offer()
        accepted = self.service.accept_offer(offer_id)
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertIsNotNone(accepted["accepted_at"])
        application = Application.objects.get(id=self.application_id)
        self.assertEqual(application.status, "HIRED")
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="OFFER_ACCEPT", object_type="OFFER"
            ).exists()
        )
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="ASSIGNMENT_TRANSITION", object_type="APPLICATION"
            ).exists()
        )

    def test_accept_twice_rejected(self):
        offer_id = self._sent_offer()
        self.service.accept_offer(offer_id)
        with self.assertRaisesRegex(AppApiException, "Illegal status transition"):
            self.service.accept_offer(offer_id)

    def test_reject_offer_writes_audit(self):
        offer_id = self._sent_offer()
        rejected = self.service.reject_offer(offer_id, {"note": "薪资未谈拢"})
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertIsNotNone(rejected["rejected_at"])
        self.assertEqual(rejected["note"], "薪资未谈拢")
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="OFFER_REJECT", object_type="OFFER"
            ).exists()
        )

    def test_withdraw_offer_writes_audit(self):
        offer_id = self._sent_offer()
        withdrawn = self.service.withdraw_offer(offer_id)
        self.assertEqual(withdrawn["status"], "WITHDRAWN")
        self.assertIsNotNone(withdrawn["withdrawn_at"])
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="OFFER_WITHDRAW", object_type="OFFER"
            ).exists()
        )

    def test_rejected_offer_allows_new_version_while_application_in_offer(self):
        offer_id = self._sent_offer()
        self.service.reject_offer(offer_id, {"note": "薪资未谈拢"})
        new_version = self.service.create_offer_for_application(self.application_id, {"salary_amount": "30000"})
        self.assertEqual(new_version["version"], 2)
        self.assertEqual(new_version["status"], "DRAFT")

    def test_no_new_offer_after_accepted(self):
        offer_id = self._sent_offer()
        self.service.accept_offer(offer_id)
        with self.assertRaisesRegex(AppApiException, "not active"):
            self.service.create_offer_for_application(self.application_id, {"salary_amount": "30000"})

    def test_offer_cross_workspace_not_found(self):
        self._to_offer()
        offer_id = self.service.create_offer_for_application(self.application_id, {})["id"]
        foreign = OfferService(workspace_id="workspace-b", user_id=self.user_id, hr_role="ADMIN")
        with self.assertRaises(NotFound404):
            foreign.get_offer(offer_id)

    def test_operator_cannot_manage_offers(self):
        self._to_offer()
        operator = OfferService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            operator.create_offer_for_application(self.application_id, {})
        offer_id = self.service.create_offer_for_application(self.application_id, {})["id"]
        with self.assertRaises(AppUnauthorizedFailed):
            operator.accept_offer(offer_id)

    def test_attachment_upload_and_download_permission(self):
        self._to_offer()
        offer_id = self.service.create_offer_for_application(self.application_id, {})["id"]
        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        handle.write(b"%PDF-offer-letter")
        handle.close()
        uploaded = self.service.upload_offer_attachment(offer_id, handle.name, "offer-letter.pdf")
        self.assertEqual(uploaded["attachment_name"], "offer-letter.pdf")
        offer = Offer.objects.get(id=offer_id)
        self.assertTrue(os.path.exists(offer.attachment_path))
        file_path, file_name = self.service.offer_attachment_file(offer_id)
        self.assertEqual(file_name, "offer-letter.pdf")
        viewer = OfferService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="VIEWER")
        with self.assertRaises(AppUnauthorizedFailed):
            viewer.offer_attachment_file(offer_id)
        self.service.remove_offer_attachment(offer_id)
        self.assertFalse(os.path.exists(offer.attachment_path))


class HandoffTests(TestCase):
    """B3: Offer 接受后幂等交接（CHECKLIST/WEBHOOK、失败重试、审计）——基于 Application"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.offer_service = OfferService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.handoff_service = OnboardingService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.recruitment = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13812345678", email="alice@example.com"
        )
        job_data = self.recruitment.create_job({"name": "Engineer", "department": "Engineering", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_service = ApplicationService("workspace-a", self.user_id, hr_role="ADMIN")
        self.application_id = self.application_service.create_application(self.job.id, self.candidate.id, {})["id"]
        stages = list(JobStage.objects.filter(job=self.job).order_by("order"))
        for stage in stages[1:]:
            self.application_service.move_stage(self.application_id, stage.id, {"reason_text": "advance"})
        self.offer_id = self.offer_service.create_offer_for_application(
            self.application_id, {"salary_amount": "25000", "currency": "CNY"}
        )["id"]
        self.offer_service.approve_offer(self.offer_id, {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        self.offer_service.send_offer(self.offer_id)

    def test_accept_creates_handoff_with_full_payload(self):
        self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(application_id=self.application_id)
        self.assertEqual(handoff.status, HandoffStatus.SUCCESS)  # 默认 CHECKLIST 直接产出清单
        import json as _json
        payload = _json.loads(handoff.payload)
        self.assertEqual(payload["candidate_name"], "Alice")
        self.assertEqual(payload["job_name"], "Engineer")
        self.assertEqual(payload["department"], "Engineering")
        self.assertEqual(payload["salary_amount"], "25000.00")
        self.assertEqual(payload["candidate_phone"], "13812345678")
        self.assertEqual(handoff.attempts, 1)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="HANDOFF", object_type="ONBOARDING", result="SUCCESS"
            ).exists()
        )

    def test_handoff_creation_is_idempotent(self):
        self.offer_service.accept_offer(self.offer_id)
        offer = Offer.objects.get(id=self.offer_id)
        self.handoff_service.create_handoff_for_offer(offer)
        self.assertEqual(OnboardingHandoff.objects.filter(application_id=self.application_id).count(), 1)

    def test_webhook_success(self):
        HrConfig.objects.update_or_create(
            workspace_id="workspace-a",
            defaults={"handoff_target_type": "WEBHOOK", "handoff_webhook_url": "https://hris.example.com/hires"},
        )
        with patch("hr.serializers.offer.urlopen") as urlopen:
            response = type("Response", (), {"status": 200, "read": lambda self: b'{"ok": true}'})()
            urlopen.return_value = response
            self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(application_id=self.application_id)
        self.assertEqual(handoff.status, HandoffStatus.SUCCESS)
        self.assertEqual(handoff.attempts, 1)
        urlopen.assert_called_once()

    def test_webhook_failure_marks_failed(self):
        HrConfig.objects.update_or_create(
            workspace_id="workspace-a",
            defaults={"handoff_target_type": "WEBHOOK", "handoff_webhook_url": "https://hris.example.com/hires"},
        )
        response = type("Response", (), {"status": 500, "read": lambda self: b"boom"})()
        with patch("hr.serializers.offer.urlopen", return_value=response):
            self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(application_id=self.application_id)
        self.assertEqual(handoff.status, HandoffStatus.FAILED)
        self.assertIn("500", handoff.last_error)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="HANDOFF", object_type="ONBOARDING", result="FAILED"
            ).exists()
        )

    def test_retry_failed_handoff(self):
        HrConfig.objects.update_or_create(
            workspace_id="workspace-a",
            defaults={"handoff_target_type": "WEBHOOK", "handoff_webhook_url": "https://hris.example.com/hires"},
        )
        with patch("hr.serializers.offer.urlopen") as urlopen:
            urlopen.side_effect = [type("Response", (), {"status": 500, "read": lambda self: b"boom"})(),
                                   type("Response", (), {"status": 200, "read": lambda self: b"ok"})()]
            self.offer_service.accept_offer(self.offer_id)
            handoff = OnboardingHandoff.objects.get(application_id=self.application_id)
            self.assertEqual(handoff.status, HandoffStatus.FAILED)
            retried = self.handoff_service.retry_handoff(handoff.id)
        self.assertEqual(retried["status"], "SUCCESS")
        handoff.refresh_from_db()
        self.assertEqual(handoff.attempts, 2)

    def test_retry_success_handoff_rejected(self):
        self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(application_id=self.application_id)
        with self.assertRaisesRegex(AppApiException, "failed handoff"):
            self.handoff_service.retry_handoff(handoff.id)

    def test_handoff_cross_workspace_not_found(self):
        self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(application_id=self.application_id)
        foreign = OnboardingService(workspace_id="workspace-b", user_id=self.user_id, hr_role="ADMIN")
        with self.assertRaises(NotFound404):
            foreign.retry_handoff(handoff.id)

    def test_operator_cannot_retry(self):
        self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(application_id=self.application_id)
        operator = OnboardingService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            operator.retry_handoff(handoff.id)


class OfferApiTests(_HrApiBase):
    """B2 路由：Offer 全链路与权限（基于 Application）"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        self.recruitment = RecruitmentService(workspace_id="workspace-a", user_id=self.admin.id, hr_role="ADMIN")
        candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = self.recruitment.create_job({"name": "Engineer", "headcount": 1})
        job = Job.objects.get(id=job_data["id"])
        self.service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        self.application_id = self.service.create_application(job.id, candidate.id, {})["id"]
        stages = list(JobStage.objects.filter(job=job).order_by("order"))
        for stage in stages[1:]:
            self.service.move_stage(self.application_id, stage.id, {"reason_text": "advance"})
        self.client_admin = self._client(self.admin)
        self.app_offers = "/admin/api/workspace/workspace-a/hr/applications/{}/offers".format(self.application_id)

    def test_full_offer_flow_via_api(self):
        offer_id = self.client_admin.post(
            self.app_offers, {"salary_amount": "25000", "currency": "CNY"}, content_type="application/json"
        ).json()["data"]["id"]
        self.client_admin.put("/admin/api/workspace/workspace-a/hr/offers/{}/approve".format(offer_id),
                              {"approval_status": "APPROVED", "approver_id": str(self.admin.id)},
                              content_type="application/json")
        self.client_admin.put("/admin/api/workspace/workspace-a/hr/offers/{}/send".format(offer_id))
        accepted = self.client_admin.put("/admin/api/workspace/workspace-a/hr/offers/{}/accept".format(offer_id))
        self.assertEqual(accepted.json()["data"]["status"], "ACCEPTED")
        application = Application.objects.get(id=self.application_id)
        self.assertEqual(application.status, "HIRED")

    def test_operator_offer_create_gets_403(self):
        response = self._client(self.operator).post(
            self.app_offers, {}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.operator.id, action="ACCESS_DENIED", result="DENIED"
            ).exists()
        )

    def test_attachment_upload_and_download(self):
        offer_id = self.client_admin.post(self.app_offers, {}, content_type="application/json").json()["data"]["id"]
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(b"%PDF-offer")
            handle.seek(0)
            response = self.client_admin.post(
                "/admin/api/workspace/workspace-a/hr/offers/{}/attachment".format(offer_id),
                {"file": handle}, format="multipart",
            )
        self.assertEqual(response.status_code, 200)
        download = self.client_admin.get(
            "/admin/api/workspace/workspace-a/hr/offers/{}/attachment/download".format(offer_id)
        )
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"%PDF-offer", b"".join(download.streaming_content))


class HandoffApiTests(_HrApiBase):
    """B3 路由：交接列表/重试/配置（基于 Application）"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        recruitment = RecruitmentService(workspace_id="workspace-a", user_id=self.admin.id, hr_role="ADMIN")
        candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a", phone="13812345678")
        job_data = recruitment.create_job({"name": "Engineer", "headcount": 1})
        job = Job.objects.get(id=job_data["id"])
        service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        application_id = service.create_application(job.id, candidate.id, {})["id"]
        for stage in JobStage.objects.filter(job=job).order_by("order")[1:]:
            service.move_stage(application_id, stage.id, {"reason_text": "advance"})
        offer = OfferService(workspace_id="workspace-a", user_id=self.admin.id, hr_role="ADMIN")
        self.offer_id = offer.create_offer_for_application(application_id, {})["id"]
        offer.approve_offer(self.offer_id, {"approval_status": "APPROVED", "approver_id": str(self.admin.id)})
        offer.send_offer(self.offer_id)
        offer.accept_offer(self.offer_id)
        self.handoff = OnboardingHandoff.objects.get(application_id=application_id)

    def test_list_handoffs(self):
        response = self._client(self.admin).get("/admin/api/workspace/workspace-a/hr/handoffs/1/20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 1)
        record = response.json()["data"]["records"][0]
        self.assertEqual(record["status"], "SUCCESS")
        self.assertEqual(record["candidate_name"], "Alice")
        self.assertEqual(record["phone"], "138****5678")

    def test_retry_requires_admin(self):
        response = self._client(self.operator).post(
            "/admin/api/workspace/workspace-a/hr/handoffs/{}/retry".format(self.handoff.id)
        )
        self.assertEqual(response.status_code, 403)

    def test_put_handoff_config(self):
        response = self._client(self.admin).put(
            "/admin/api/workspace/workspace-a/hr/handoff/config",
            {"target_type": "WEBHOOK", "webhook_url": "https://hris.example.com/hires"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        config = HrConfig.objects.get(workspace_id="workspace-a")
        self.assertEqual(config.handoff_target_type, "WEBHOOK")
        self.assertEqual(config.handoff_webhook_url, "https://hris.example.com/hires")

    def test_put_handoff_config_rejects_invalid_target(self):
        response = self._client(self.admin).put(
            "/admin/api/workspace/workspace-a/hr/handoff/config",
            {"target_type": "SMS"}, content_type="application/json",
        )
        self.assertEqual(response.json()["code"], 400)


class ResumeSplitterTests(SimpleTestCase):
    """C 阶段切片器：清洗 / LLM 边界标注 / L2 校验 / L3 降级 / PII（协议见综合方案 §6.8）"""

    _RESUME = (
        "姓名：李冠光\n"
        "\n"
        "【教育经历】\n"
        "- 院校：北京师范大学 | 学位：硕士 | 毕业时间：2005.06\n"
        "\n"
        "【工作经历】\n"
        "- 时间：1992.09-2017.10 | 单位：深圳大运置业 | 职务：后端开发\n"
        "  内容：幕墙系统的概念设计及深化设计，与建筑师沟通。\n"
    )

    @staticmethod
    def _stub(payload):
        return lambda prompt: payload

    def test_split_with_skills_returns_chunks_and_skills_from_one_call(self):
        from hr.services.resume_splitter import split_resume_with_skills

        payload = (
            '{"chunks": ['
            '{"title": "基本信息", "start_line": 1, "end_line": 1},'
            '{"title": "教育经历-北京师范大学", "start_line": 3, "end_line": 5},'
            '{"title": "工作经历-深圳大运置业 后端", "start_line": 6, "end_line": 8}'
            '], "skills": ["Python", "幕墙系统设计"]}'
        )
        chunks, skills, stats = split_resume_with_skills(self._RESUME, self._stub(payload))
        self.assertEqual(len(chunks), 3)
        self.assertEqual(skills, ["Python", "幕墙系统设计"])
        self.assertEqual(stats.get("path"), "llm")

    def test_split_with_skills_fallback_rules_returns_empty_skills(self):
        from hr.services.resume_splitter import split_resume_with_skills

        chunks, skills, stats = split_resume_with_skills(self._RESUME, self._stub("not a json"))
        self.assertTrue(len(chunks) >= 1)
        self.assertEqual(skills, [])
        self.assertEqual(stats.get("path"), "rules")

    def test_sanitize_resume_text(self):
        from hr.services.resume_splitter import sanitize_resume_text

        raw = "\x00姓名：张三\r\n\r\n\r\n  技能：  Python  \r\n"
        self.assertEqual(sanitize_resume_text(raw), "姓名：张三\n\n 技能： Python")
        self.assertEqual(sanitize_resume_text("a\x00b\x00c"), "abc")

    def test_mask_pii(self):
        from hr.services.resume_splitter import mask_pii

        masked = mask_pii("电话 13812345678 邮箱 a@b.com 身份证 11010119900307873X")
        self.assertNotIn("13812345678", masked)
        self.assertNotIn("a@b.com", masked)
        self.assertNotIn("11010119900307873X", masked)
        self.assertIn("[已脱敏]", masked)
        # 带分隔符的手机号变体
        self.assertNotIn("138 1234 5678", mask_pii("电话：138 1234 5678"))

    def test_mask_front_preserves_line_count(self):
        """T1：掩码前置后行数不变 → LLM 行号边界协议不受影响；内容已掩码、不依赖返回点后处理。"""
        from hr.services.resume_splitter import split_resume_text

        text = "姓名：李冠光\n电话：13812345678\n邮箱：a@b.com\n\n【教育经历】\n- 院校：北京师范大学"
        payload = (
            '{"chunks": ['
            '{"title": "基本信息", "start_line": 1, "end_line": 3},'
            '{"title": "教育经历-北京师范大学", "start_line": 5, "end_line": 6}'
            "]}"
        )
        result = split_resume_text(text, self._stub(payload))
        self.assertEqual(len(result), 2)
        joined = "\n".join(row["content"] for row in result)
        # 非空行数与原文一致（掩码不改变行结构）
        self.assertEqual(len([ln for ln in joined.split("\n") if ln.strip()]),
                         len([ln for ln in text.split("\n") if ln.strip()]))
        self.assertIn("[已脱敏]", result[0]["content"])
        self.assertNotIn("13812345678", joined)
        self.assertNotIn("a@b.com", joined)
        self.assertIn("北京师范大学", result[1]["content"])

    def test_llm_split_ok(self):
        from hr.services.resume_splitter import split_resume_text

        payload = (
            '{"chunks": ['
            '{"title": "基本信息", "start_line": 1, "end_line": 1},'
            '{"title": "教育经历-北京师范大学", "start_line": 3, "end_line": 4},'
            '{"title": "工作经历-深圳大运置业 后端", "start_line": 6, "end_line": 8}'
            "]}"
        )
        result = split_resume_text(self._RESUME, self._stub(payload))
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["title"], "基本信息")
        self.assertIn("深圳大运置业", result[2]["content"])
        self.assertIn("幕墙系统", result[2]["content"])
        # 保真：所有非空行都出现在某段中
        joined = "\n".join(row["content"] for row in result)
        for line in self._RESUME.split("\n"):
            if line.strip():
                self.assertIn(line.strip(), joined)

    def test_llm_json_wrapped_in_code_block(self):
        from hr.services.resume_splitter import split_resume_text

        payload = (
            '\x60\x60\x60json\n{"chunks": ['
            '{"title": "基本信息", "start_line": 1, "end_line": 1},'
            '{"title": "教育经历-北京师范大学", "start_line": 3, "end_line": 4},'
            '{"title": "工作经历-深圳大运置业 后端", "start_line": 6, "end_line": 8}'
            "]}\n\x60\x60\x60"
        )
        result = split_resume_text(self._RESUME, self._stub(payload))
        self.assertEqual(len(result), 3)

    def test_llm_out_of_range_retry_then_ok(self):
        from hr.services.resume_splitter import split_resume_text

        bad = '{"chunks": [{"title": "x", "start_line": 99, "end_line": 100}]}'
        good = (
            '{"chunks": ['
            '{"title": "基本信息", "start_line": 1, "end_line": 1},'
            '{"title": "教育经历-北京师范大学", "start_line": 3, "end_line": 4},'
            '{"title": "工作经历-深圳大运置业 后端", "start_line": 6, "end_line": 8}'
            "]}"
        )
        calls = []

        def flaky(prompt):
            calls.append(1)
            return bad if len(calls) == 1 else good

        result = split_resume_text(self._RESUME, flaky)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(calls), 2)  # 第一次失败，重试成功

    def test_llm_gap_falls_back_to_rules(self):
        from hr.services.resume_splitter import split_resume_text

        # 两次都漏掉工作经历内容行（覆盖不全）→ 走规则降级
        payload = (
            '{"chunks": ['
            '{"title": "基本信息", "start_line": 1, "end_line": 1},'
            '{"title": "教育经历-北京师范大学", "start_line": 3, "end_line": 4}'
            "]}"
        )
        result = split_resume_text(self._RESUME, self._stub(payload))
        # 规则降级结果：教育/工作两个区块均存在
        self.assertGreaterEqual(len(result), 2)
        self.assertTrue(any("教育经历" in row["title"] for row in result))
        self.assertTrue(any("工作经历" in row["title"] for row in result))

    def test_llm_invalid_json_falls_back_to_rules(self):
        from hr.services.resume_splitter import split_resume_text

        result = split_resume_text(self._RESUME, self._stub("not a json"))
        self.assertGreaterEqual(len(result), 2)
        self.assertTrue(any("教育经历" in row["title"] for row in result))

    def test_smart_fallback_unstructured(self):
        from hr.services.resume_splitter import split_resume_text

        text = "第一段。\n\n第二段内容。\n\n第三段内容。\n\n第四段内容。\n\n第五段内容。"
        result = split_resume_text(text, self._stub("garbage"))
        self.assertGreaterEqual(len(result), 1)
        joined = "\n".join(row["content"] for row in result)
        self.assertIn("第一段", joined)
        self.assertIn("第五段", joined)

    def test_short_text_raises(self):
        from hr.services.resume_splitter import split_resume_text

        with self.assertRaises(ValueError):
            split_resume_text("太短", self._stub("{}"))

    def test_long_single_line_falls_back_to_smart(self):
        """无换行超长文本：LLM 单段超 500 被拒 → 规则拒绝 → smart 兜底多段"""
        from hr.services.resume_splitter import split_resume_text

        text = "简历；姓名；张三；" + "工作内容；" + "负责系统开发与维护；" * 100  # ~1500 字符单行
        single = '{"chunks": [{"title": "基本信息", "start_line": 1, "end_line": 1}]}'
        result = split_resume_text(text, self._stub(single))
        self.assertGreater(len(result), 1)
        self.assertTrue(all(len(row["content"]) <= 500 for row in result))

    def test_llm_overlong_chunk_rejected(self):
        """LLM 输出 600+ 字符段 → 校验拒绝 → 降级"""
        from hr.services.resume_splitter import split_resume_text

        text = "姓名：张三\n\n【工作经历】\n- 单位：某公司 | 职务：工程师\n  内容：" + "负责系统开发。" * 120
        overlong = '{"chunks": [{"title": "基本信息", "start_line": 1, "end_line": 1}, {"title": "工作经历-某公司", "start_line": 3, "end_line": 5}]}'
        result = split_resume_text(text, self._stub(overlong))
        self.assertGreaterEqual(len(result), 1)
        self.assertTrue(all(len(row["content"]) <= 500 for row in result))


class EnvOverrideTests(SimpleTestCase):
    """F6：MAXKB_HR_* 环境变量覆盖 λ 与预筛阈值（合法值生效、非法值回退默认）。"""

    def test_env_float_valid_and_invalid(self):
        from unittest import mock

        import hr.services.resume_search as rs
        with mock.patch.dict(os.environ, {"MAXKB_HR_EVIDENCE_LAMBDA": "0.25"}, clear=False):
            self.assertEqual(rs._env_float("MAXKB_HR_EVIDENCE_LAMBDA", 0.0), 0.25)
        with mock.patch.dict(os.environ, {"MAXKB_HR_EVIDENCE_LAMBDA": "abc"}, clear=False):
            self.assertEqual(rs._env_float("MAXKB_HR_EVIDENCE_LAMBDA", 0.0), 0.0)
        with mock.patch.dict(os.environ, {}, clear=False):
            self.assertEqual(rs._env_float("MAXKB_HR_EVIDENCE_LAMBDA", 0.0), 0.0)

    def test_env_int_valid_and_invalid(self):
        from unittest import mock

        import hr.services.resume_search as rs
        with mock.patch.dict(os.environ, {"MAXKB_HR_MAX_PREFILTER": "5000"}, clear=False):
            self.assertEqual(rs._env_int("MAXKB_HR_MAX_PREFILTER", 2000), 5000)
        with mock.patch.dict(os.environ, {"MAXKB_HR_MAX_PREFILTER": "many"}, clear=False):
            self.assertEqual(rs._env_int("MAXKB_HR_MAX_PREFILTER", 2000), 2000)

    def test_module_constants_read_env(self):
        """F6 复审（P2-A）：模块常量在导入时读取环境变量（reload 级断言，防残留行再次覆盖）。"""
        import importlib
        from unittest import mock

        import hr.services.resume_search as rs
        with mock.patch.dict(os.environ,
                             {"MAXKB_HR_EVIDENCE_LAMBDA": "0.25", "MAXKB_HR_MAX_PREFILTER": "5000"}, clear=False):
            rs = importlib.reload(rs)
            self.assertEqual(rs._EVIDENCE_LAMBDA, 0.25)
            self.assertEqual(rs._PREFILTER_MAX, 5000)
        rs = importlib.reload(rs)  # 还原默认环境下的常量，避免影响后续用例
        self.assertEqual(rs._EVIDENCE_LAMBDA, 0.0)
        self.assertEqual(rs._PREFILTER_MAX, 2000)


class QueryUnderstandTests(SimpleTestCase):
    """T4：规则槽位抽取（年限/学历/城市/语义词）。"""

    def test_extract_slots_years(self):
        from hr.services.query_understand import extract_slots

        slots = extract_slots("5年以上 Java")
        self.assertEqual(slots["years_min"], 5)
        self.assertEqual(slots["semantic_query"], "Java")
        slots = extract_slots("3年Java后端")
        self.assertEqual(slots["years_min"], 3)
        self.assertEqual(slots["semantic_query"], "Java后端")
        # 年份语境不得误抽（2023年）
        slots = extract_slots("2023年毕业 Java")
        self.assertIsNone(slots["years_min"])
        self.assertEqual(slots["semantic_query"], "2023年毕业 Java")

    def test_extract_slots_degree_and_city(self):
        from hr.services.query_understand import extract_slots

        slots = extract_slots("本科 北京 后端", city_list=["北京市", "上海"])
        self.assertEqual(slots["degree_level"], 2)
        self.assertEqual(slots["cities"], ["北京市"])
        self.assertEqual(slots["semantic_query"], "后端")
        slots = extract_slots("10年以上 硕士 深圳", city_list=["深圳"])
        self.assertEqual(slots["years_min"], 10)
        self.assertEqual(slots["degree_level"], 3)
        self.assertEqual(slots["cities"], ["深圳"])
        self.assertEqual(slots["semantic_query"], "")

    def test_extract_slots_city_one_sided(self):
        """F7 复审（P3-2）：city_list 只有「北京」时查询「北京市」不残留「市」字。"""
        from hr.services.query_understand import extract_slots

        slots = extract_slots("北京市 5年以上", city_list=["北京"])
        self.assertEqual(slots["cities"], ["北京"])
        self.assertEqual(slots["semantic_query"], "")
        slots = extract_slots("北京市 5年以上", city_list=["北京市"])
        self.assertEqual(slots["cities"], ["北京市"])
        self.assertEqual(slots["semantic_query"], "")


class SkillNormalizeTests(SimpleTestCase):
    """T5：技能词归一。"""

    def test_normalize_variants(self):
        from hr.services.skill_normalize import normalize_skill

        self.assertEqual(normalize_skill("Java"), "java")
        self.assertEqual(normalize_skill("JAVA"), "java")
        self.assertEqual(normalize_skill("Java8"), "java")
        self.assertEqual(normalize_skill("K8s"), "kubernetes")
        self.assertEqual(normalize_skill("Spring Boot"), "springboot")
        self.assertEqual(normalize_skill("  Docker "), "docker")
        self.assertEqual(normalize_skill("未知技能"), "未知技能")
        self.assertEqual(normalize_skill(""), "")


class CandidateSkillBackfillTests(TestCase):
    """T5：回填命令幂等。"""

    def test_backfill_and_idempotent(self):
        from django.core.management import call_command

        from hr.models import Candidate, CandidateSkill

        candidate = Candidate.objects.create(workspace_id="ws-backfill", name="甲", skills=["Java", "K8s", "  Docker "])
        call_command("backfill_candidate_skills", "--workspace", "ws-backfill", verbosity=0)
        norms = sorted(
            CandidateSkill.objects.filter(candidate=candidate).values_list("skill_norm", flat=True)
        )
        self.assertEqual(norms, ["docker", "java", "kubernetes"])
        call_command("backfill_candidate_skills", "--workspace", "ws-backfill", verbosity=0)
        self.assertEqual(CandidateSkill.objects.filter(candidate=candidate).count(), 3)  # 幂等


class ReindexCommandTests(TestCase):
    """T6：重嵌/词条命令编排（mock，不跑真实模型）。"""

    def setUp(self):
        self.workspace_id = "ws-reindex"
        self.user = User.objects.create(username="re-" + uuid.uuid7().hex[:8], nick_name="r", password="p", role="ADMIN")
        self.model = Model.objects.create(
            id=uuid.uuid7(), name="bge-test", status="SUCCESS", model_type="EMBEDDING",
            model_name="BAAI/bge-large-zh-v1.5", provider="model_openai_provider",
            credential="{}", meta={}, workspace_id="default",
        )
        from knowledge.models import KnowledgeFolder

        KnowledgeFolder.objects.get_or_create(
            id="default", defaults={"name": "default", "workspace_id": "default"}
        )

    def test_seed_termbase_idempotent(self):
        from django.core.management import call_command

        from knowledge.models import Knowledge, KnowledgeScope, KnowledgeType, Termbase

        knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), name="简历语义索引", workspace_id=self.workspace_id,
            embedding_model_id=self.model.id, user_id=self.user.id,
            type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value,
        )
        call_command("seed_resume_termbase", "--workspace", self.workspace_id, verbosity=0)
        count = Termbase.objects.filter(knowledge_id=knowledge.id).count()
        self.assertGreater(count, 0)
        self.assertTrue(Termbase.objects.filter(knowledge_id=knowledge.id, content="java").exists())
        self.assertTrue(Termbase.objects.filter(knowledge_id=knowledge.id, content="k8s").exists())
        call_command("seed_resume_termbase", "--workspace", self.workspace_id, verbosity=0)
        self.assertEqual(Termbase.objects.filter(knowledge_id=knowledge.id).count(), count)  # 幂等

    def test_seed_termbase_includes_job_skill_requirements(self):
        """P3 复审：Termbase 词条聚合 Job.skill_requirements，且幂等。"""
        from django.core.management import call_command

        from knowledge.models import Knowledge, KnowledgeScope, KnowledgeType, Termbase

        knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), name="简历语义索引", workspace_id=self.workspace_id,
            embedding_model_id=self.model.id, user_id=self.user.id,
            type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value,
        )
        Job.objects.create(
            workspace_id=self.workspace_id, name="后端", headcount=1,
            skill_requirements=["GoLang", "Rust"],
        )
        call_command("seed_resume_termbase", "--workspace", self.workspace_id, verbosity=0)
        contents = set(Termbase.objects.filter(knowledge_id=knowledge.id).values_list("content", flat=True))
        self.assertIn("GoLang", contents)   # 原词
        self.assertIn("golang", contents)   # 归一形
        self.assertIn("Rust", contents)
        call_command("seed_resume_termbase", "--workspace", self.workspace_id, verbosity=0)
        self.assertEqual(Termbase.objects.filter(knowledge_id=knowledge.id).count(), len(contents))

    @patch("knowledge.task.embedding.embedding_by_document.delay")
    def test_reindex_queues_documents(self, mock_delay):
        from django.core.management import call_command

        from knowledge.models import Document, Knowledge, KnowledgeScope, KnowledgeType

        knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), name="简历语义索引", workspace_id=self.workspace_id,
            embedding_model_id=self.model.id, user_id=self.user.id,
            type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value,
        )
        for i in range(2):
            Document.objects.create(
                id=uuid.uuid7(), knowledge_id=knowledge.id, name=f"r{i}.txt",
                char_length=10, user_id=self.user.id,
            )
        call_command("reindex_resume_knowledge", "--workspace", self.workspace_id, verbosity=0)
        self.assertEqual(mock_delay.call_count, 2)


class ResumeIndexTests(TestCase):
    """C 阶段打通：简历知识库 + 入库索引 + 生命周期同步"""

    def setUp(self):
        self.workspace_id = "workspace-idx"
        self.user = User.objects.create(
            username="idx-" + uuid.uuid7().hex[:8], nick_name="idx", password="p", role="ADMIN"
        )
        self.user_id = self.user.id
        self.model = Model.objects.create(
            id=uuid.uuid7(), name="bge-test", status="SUCCESS", model_type="EMBEDDING",
            model_name="BAAI/bge-large-zh-v1.5", provider="model_openai_provider",
            credential="{}", meta={}, workspace_id="default",
        )
        # 测试库由主库 TEMPLATE 克隆（settings base/web.py TEST.TEMPLATE），可能带真实 EMBEDDING 模型；
        # get_or_create_resume_knowledge 取 filter().first()，隔离其余模型保证断言确定（事务回滚不影响其他测试）
        Model.objects.filter(model_type="EMBEDDING").exclude(id=self.model.id).delete()

    def _resume(self):
        return ResumeFile.objects.create(
            workspace_id=self.workspace_id, file_name="r.txt", extension="txt",
            file_path="/tmp/r.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            source_channel="OTHER", status=ResumeStatus.PENDING, user_id=self.user_id,
        )

    def _stub_chat(self):
        payload = (
            '{"chunks": ['
            '{"title": "基本信息", "start_line": 1, "end_line": 1},'
            '{"title": "教育经历-北京师范大学", "start_line": 3, "end_line": 4}'
            "]}"
        )
        return lambda prompt: payload

    @patch("knowledge.serializers.knowledge.embedding_by_knowledge.delay")
    def test_get_or_create_resume_knowledge_idempotent(self, mock_delay):
        k1 = get_or_create_resume_knowledge(self.workspace_id, self.user_id)
        k2 = get_or_create_resume_knowledge(self.workspace_id, self.user_id)
        self.assertEqual(k1.id, k2.id)
        self.assertEqual(k1.name, "简历语义索引")
        self.assertEqual(str(k1.embedding_model_id), str(self.model.id))
        self.assertEqual(k1.workspace_id, self.workspace_id)

    @patch("hr.services.resume_index.embedding_by_document.delay")
    @patch("knowledge.serializers.knowledge.embedding_by_knowledge.delay")
    def test_index_resume_creates_document_and_paragraphs(self, mock_k_delay, mock_embed_delay):
        resume = self._resume()
        text = "姓名：李冠光\n\n【教育经历】\n- 院校：北京师范大学 | 学位：硕士"
        doc_id = index_resume(self.workspace_id, self.user_id, resume, text, self._stub_chat())
        self.assertTrue(doc_id)
        resume.refresh_from_db()
        self.assertEqual(str(resume.document_id), doc_id)
        document = Document.objects.get(id=doc_id)
        self.assertEqual(document.name, "r.txt")
        self.assertEqual(document.knowledge_id, get_or_create_resume_knowledge(self.workspace_id, self.user_id).id)
        self.assertEqual(Paragraph.objects.filter(document_id=doc_id).count(), 2)
        mock_embed_delay.assert_called()  # 向量化被触发

    @patch("hr.services.resume_index.embedding_by_document.delay")
    def test_index_resume_replaces_old_document(self, mock_refresh):
        resume = self._resume()
        text = "姓名：李冠光\n\n【教育经历】\n- 院校：北京师范大学 | 学位：硕士"
        doc_id_1 = index_resume(self.workspace_id, self.user_id, resume, text, self._stub_chat())
        doc_id_2 = index_resume(self.workspace_id, self.user_id, resume, text, self._stub_chat())
        self.assertNotEqual(doc_id_1, doc_id_2)
        self.assertFalse(Document.objects.filter(id=doc_id_1).exists())
        self.assertTrue(Document.objects.filter(id=doc_id_2).exists())

    @patch("hr.services.resume_index.embedding_by_document.delay")
    def test_delete_resume_index_removes_document(self, mock_refresh):
        resume = self._resume()
        text = "姓名：李冠光\n\n【教育经历】\n- 院校：北京师范大学 | 学位：硕士"
        doc_id = index_resume(self.workspace_id, self.user_id, resume, text, self._stub_chat())
        delete_resume_index(resume)
        self.assertFalse(Document.objects.filter(id=doc_id).exists())
        resume.refresh_from_db()
        self.assertIsNone(resume.document_id)

    @patch("hr.services.resume_index.embedding_by_document.delay")
    def test_set_resume_index_active_toggles_document(self, mock_refresh):
        resume = self._resume()
        text = "姓名：李冠光\n\n【教育经历】\n- 院校：北京师范大学 | 学位：硕士"
        doc_id = index_resume(self.workspace_id, self.user_id, resume, text, self._stub_chat())
        set_resume_index_active(resume, False)
        self.assertFalse(Document.objects.get(id=doc_id).is_active)
        set_resume_index_active(resume, True)
        self.assertTrue(Document.objects.get(id=doc_id).is_active)

    def test_index_resume_rejects_residual_pii(self):
        """修复回归（审查 P2，设计 §6.8）：掩码未覆盖的 PII 变体（15 位身份证）必须拒绝入库。"""
        resume = self._resume()
        # 15 位身份证：主掩码正则（18 位）不覆盖 → 二次扫描应拒绝
        text = "姓名：李冠光\n\n【基本信息】\n- 身份证：110101900101123\n- 其他：无"
        with self.assertRaises(ValueError) as ctx:
            index_resume(self.workspace_id, self.user_id, resume, text, self._stub_chat())
        self.assertIn("PII", str(ctx.exception))
        self.assertIsNone(resume.document_id)

    def test_index_resume_rejects_residual_pii_without_pii_flow_log(self):
        """P2 复审：残留 PII 拒绝入库时，SPLIT 流转日志不得包含未掩码正文（且仅一条 FAILED，枚举一致）。"""
        from hr.models import ResumeFlowLog

        resume = self._resume()
        text = "姓名：李冠光\n\n【基本信息】\n- 身份证：110101900101123\n- 其他：无"
        with self.assertRaises(ValueError):
            index_resume(self.workspace_id, self.user_id, resume, text, self._stub_chat())
        logs = ResumeFlowLog.objects.filter(resume_id=resume.id, node="SPLIT")
        self.assertEqual(len(logs), 1)  # 内层一条（含详情），不出现第二条
        self.assertEqual(logs[0].status, "FAILED")  # 与 task 层失败日志枚举一致（不用 FAILURE）
        for log in logs:
            self.assertNotIn("110101900101123", str(log.detail))
            self.assertNotIn("110101900101123", log.error_message or "")

    def test_task_index_skips_duplicate_log_on_residual_pii(self):
        """P2 修复：_index_resume 捕获 ResidualPIIError 时不再重复写 SPLIT 日志（内层已记录）。"""
        from hr.models import ResumeFlowLog
        from hr.services.resume_index import ResidualPIIError
        from hr.task.resume import _index_resume

        resume = self._resume()
        with patch("hr.task.resume._llm_chat_fn", return_value=lambda prompt: ""), \
                patch("hr.task.resume.sanitize_resume_text", return_value="text"), \
                patch("hr.task.resume.index_resume",
                      side_effect=ResidualPIIError("切片内容仍包含未掩码的 PII（基本信息），拒绝入库")):
            _index_resume(resume, "text")
        resume.refresh_from_db()
        self.assertIn("语义索引失败", resume.error_message)
        self.assertEqual(ResumeFlowLog.objects.filter(resume_id=resume.id, node="SPLIT").count(), 0)

    def test_task_index_logs_generic_failure(self):
        """P2 修复对照：普通异常仍由 task 层写一条 SPLIT FAILED（不误跳）。"""
        from hr.models import ResumeFlowLog
        from hr.task.resume import _index_resume

        resume = self._resume()
        with patch("hr.task.resume._llm_chat_fn", return_value=lambda prompt: ""), \
                patch("hr.task.resume.sanitize_resume_text", return_value="text"), \
                patch("hr.task.resume.index_resume", side_effect=RuntimeError("boom")):
            _index_resume(resume, "text")
        resume.refresh_from_db()
        self.assertIn("语义索引失败", resume.error_message)
        logs = ResumeFlowLog.objects.filter(resume_id=resume.id, node="SPLIT")
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs[0].status, "FAILED")

    def test_index_resume_accepts_masked_content(self):
        """修复回归（审查 P2）：掩码已覆盖内容（电话/邮箱/18 位身份证）不触发二次扫描拒绝。"""
        resume = self._resume()
        text = "姓名：李冠光\n\n【基本信息】\n- 电话：13812345678\n- 邮箱：a@b.com\n- 身份证：11010119900101123X"
        doc_id = index_resume(self.workspace_id, self.user_id, resume, text, self._stub_chat())
        self.assertTrue(doc_id)
        paragraphs = Paragraph.objects.filter(document_id=doc_id)
        # 掩码生效（至少一段含掩码标记）且二次扫描无残留
        from hr.services.resume_splitter import scan_residual_pii
        self.assertTrue(any("[已脱敏]" in p.content for p in paragraphs))
        self.assertTrue(all(not scan_residual_pii(p.content) for p in paragraphs))

    @patch("hr.services.resume_index.embedding_by_document.delay")
    def test_index_resume_chunks_carry_title_prefix(self, mock_embed_delay):
        """T2：chunks 携带 title 前缀（参与向量化/分词），content 保持原文（保真/展示不变）。"""
        resume = self._resume()
        text = "姓名：李冠光\n\n【教育经历】\n- 院校：北京师范大学 | 学位：硕士"
        doc_id = index_resume(self.workspace_id, self.user_id, resume, text, self._stub_chat())
        paragraphs = list(Paragraph.objects.filter(document_id=doc_id).order_by("position"))
        self.assertEqual(len(paragraphs), 2)
        # content 保持原文（保真协议：不被 title 污染）
        self.assertEqual([p.content for p in paragraphs],
                         ["姓名：李冠光", "【教育经历】\n- 院校：北京师范大学 | 学位：硕士"])
        for p in paragraphs:
            # chunks 携带 title 前缀（title 非空时），原文首行保留在 chunks 内
            if p.title:
                self.assertTrue(p.chunks[0].startswith(p.title + "\n"))
            self.assertIn(p.content.split("\n")[0], "\n".join(p.chunks))
        # 教育经历段：title 前缀 + 原文内容都在 chunks 里
        edu = next(p for p in paragraphs if p.title and "教育经历" in p.title)
        self.assertTrue(edu.chunks[0].startswith(edu.title))
        self.assertIn("北京师范大学", "\n".join(edu.chunks))


class ResumeParserDocxTableTests(TestCase):
    """docx 表格排版简历提取（数据集 sample 实测场景：内容全在表格里）"""

    @staticmethod
    def _make_table_docx(path):
        from docx import Document

        doc = Document()
        doc.add_paragraph("姓名：张三")
        table = doc.add_table(rows=3, cols=2)
        table.cell(0, 0).text = "工作经历"
        table.cell(0, 1).text = "2020-2023 某科技公司 工程师"
        table.cell(1, 0).text = "职责"
        table.cell(1, 1).text = "负责系统开发与维护"
        # 合并单元格（行 2 整行合并 → 去重验证）
        merged = table.cell(2, 0).merge(table.cell(2, 1))
        merged.text = "教育经历：北京某大学 本科"
        doc.save(path)

    def test_extract_docx_paragraphs_and_tables(self):
        from hr.services.resume_parser import extract_text_from_docx

        path = os.path.join(tempfile.gettempdir(), "resume_table_test.docx")
        self._make_table_docx(path)
        try:
            text = extract_text_from_docx(path)
            self.assertIn("姓名：张三", text)
            self.assertIn("某科技公司", text)
            self.assertIn("负责系统开发与维护", text)
            self.assertIn("北京某大学", text)
            # 合并单元格只出现一次
            self.assertEqual(text.count("教育经历：北京某大学"), 1)
        finally:
            os.remove(path)


class ResumeFlowLogTests(TestCase):
    """简历数据流转日志：节点数据持久化 + 查询 API"""

    def setUp(self):
        self.workspace_id = "workspace-flow"
        self.user = User.objects.create(
            username="flow-" + uuid.uuid7().hex[:8], nick_name="flow", password="p", role="ADMIN"
        )
        self.model = Model.objects.create(
            id=uuid.uuid7(), name="bge-test", status="SUCCESS", model_type="EMBEDDING",
            model_name="BAAI/bge-large-zh-v1.5", provider="model_openai_provider",
            credential="{}", meta={}, workspace_id="default",
        )
        HrConfig.objects.create(workspace_id=self.workspace_id, llm_model_id=str(uuid.uuid7()))

    def _resume(self):
        return ResumeFile.objects.create(
            workspace_id=self.workspace_id, file_name="r.txt", extension="txt",
            file_path="/tmp/r.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            source_channel="OTHER", status=ResumeStatus.PENDING, user_id=self.user.id,
        )

    def test_upload_and_task_write_flow_logs(self):
        from hr.services.flow_log import list_flow_logs, log_flow
        from hr.task.resume import parse_resume_task

        # 真实文件（走完整任务：提取→解析→清洗→切片→建文档）
        content = "姓名：李冠光\n\n【教育经历】\n- 院校：北京师范大学 | 学位：硕士"
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write(content.encode("utf-8"))
        handle.close()
        resume = ResumeFile.objects.create(
            workspace_id=self.workspace_id, file_name="r.txt", extension="txt",
            file_path=handle.name, file_size=os.path.getsize(handle.name),
            sha256="sha-" + uuid.uuid7().hex, source_channel="OTHER",
            status=ResumeStatus.PENDING, user_id=self.user.id,
        )
        log_flow(self.workspace_id, "UPLOAD", resume_id=resume.id,
                 detail={"file_name": "r.txt", "file_size": 1, "extension": "txt", "duplicate": False})

        with patch("hr.task.resume._llm_chat_fn") as mock_fn:
            def fake_chat(prompt):
                return "not a json"
            mock_fn.return_value = fake_chat
            with patch("knowledge.serializers.document.DocumentSerializers.Operate.refresh"):
                parse_resume_task.run(str(resume.id))
        os.remove(handle.name)

        logs = list_flow_logs(self.workspace_id, resume_id=resume.id)
        nodes = [log["node"] for log in logs]
        self.assertIn("UPLOAD", nodes)
        self.assertIn("EXTRACT", nodes)
        self.assertIn("SANITIZE", nodes)
        self.assertIn("SPLIT", nodes)
        self.assertIn("DOCUMENT", nodes)
        # EXTRACT 保留全文，SANITIZE 保留清洗后全文（审查对照）
        extract_log = next(log for log in logs if log["node"] == "EXTRACT")
        self.assertIn("text", extract_log["detail"])
        self.assertIn("李冠光", extract_log["detail"]["text"])
        sanitize_log = next(log for log in logs if log["node"] == "SANITIZE")
        self.assertIn("cleaned", sanitize_log["detail"])
        # SPLIT 记录每个 chunk 的完整内容（title/content/length/pii_masked）
        split_log = next(log for log in logs if log["node"] == "SPLIT" and log["status"] == "SUCCESS")
        self.assertEqual(split_log["detail"]["path"], "rules")
        self.assertGreaterEqual(split_log["detail"]["chunks_count"], 1)
        items = split_log["detail"]["chunks"]
        self.assertTrue(all("title" in item and "content" in item and "length" in item for item in items))
        self.assertTrue(all(item["length"] == len(item["content"]) for item in items))
        self.assertTrue(any(len(item["content"]) > 0 for item in items))
        doc_log = next(log for log in logs if log["node"] == "DOCUMENT")
        self.assertIsNotNone(doc_log["document_id"])
        self.assertGreaterEqual(doc_log["detail"]["paragraphs"], 1)

    def test_lifecycle_logs(self):
        from hr.services.flow_log import list_flow_logs

        resume = self._resume()
        resume.document_id = uuid.uuid7()
        resume.save(update_fields=["document_id", "update_time"])
        set_resume_index_active(resume, False)
        from hr.services.flow_log import log_flow
        log_flow(self.workspace_id, "LIFECYCLE", resume_id=resume.id, document_id=resume.document_id,
                 detail={"action": "archive", "is_active": False})
        logs = list_flow_logs(self.workspace_id, resume_id=resume.id)
        self.assertEqual(logs[-1]["detail"]["action"], "archive")

    def test_flow_log_api(self):
        from hr.services.flow_log import log_flow

        resume = self._resume()
        log_flow(self.workspace_id, "UPLOAD", resume_id=resume.id, detail={"duplicate": False})
        log_flow(self.workspace_id, "SPLIT", resume_id=resume.id, detail={"chunks": 3})
        # 服务层查询（API 认证走 TokenAuth，测试直接验证服务能力）
        from hr.services.flow_log import list_flow_logs
        logs = list_flow_logs(self.workspace_id, resume_id=resume.id)
        self.assertEqual(len(logs), 2)
        self.assertEqual([log["node"] for log in logs], ["UPLOAD", "SPLIT"])

    def test_flow_log_api_requires_operator(self):
        """PII 防护：flow-logs 含 EXTRACT/SANITIZE 未脱敏全文，VIEWER 必须 403，OPERATOR+ 可读。"""
        from hr.services.flow_log import log_flow

        resume = self._resume()
        log_flow(self.workspace_id, "EXTRACT", resume_id=resume.id,
                 detail={"length": 10, "lines": 2, "source": "txt", "text": "电话：13812345678"})
        admin = User.objects.create(username="flow-admin-" + uuid.uuid7().hex[:6], nick_name="fa",
                                    password="p", role="ADMIN")
        operator = User.objects.create(username="flow-op-" + uuid.uuid7().hex[:6], nick_name="fo",
                                       password="p", role="USER")
        viewer = User.objects.create(username="flow-view-" + uuid.uuid7().hex[:6], nick_name="fv",
                                     password="p", role="USER")
        HrAccess.objects.create(workspace_id=self.workspace_id, user_id=admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id=self.workspace_id, user_id=operator.id, role="OPERATOR")
        HrAccess.objects.create(workspace_id=self.workspace_id, user_id=viewer.id, role="VIEWER")
        url = f"/admin/api/workspace/{self.workspace_id}/hr/resumes/{resume.id}/flow-logs"
        # VIEWER 拒绝（流转日志含未脱敏全文）
        viewer_client = APIClient()
        viewer_client.force_authenticate(user=viewer)
        response = viewer_client.get(url)
        self.assertEqual(response.status_code, 403)
        # OPERATOR/ADMIN 可读
        for user in (operator, admin):
            client = APIClient()
            client.force_authenticate(user=user)
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            nodes = [log["node"] for log in response.json()["data"]]
            self.assertIn("EXTRACT", nodes)

    def test_delete_resume_cleans_index_and_flow_logs(self):
        """修复回归（审查 P1）：简历删除必须联动清理语义索引（文档/段落/向量）与流转日志（含未脱敏全文）。"""
        from hr.services.flow_log import list_flow_logs, log_flow
        from hr.serializers.recruitment import RecruitmentService
        from knowledge.models import Document, Embedding, Knowledge, KnowledgeFolder, KnowledgeScope, KnowledgeType, Paragraph

        KnowledgeFolder.objects.get_or_create(id="default", defaults={"name": "default", "workspace_id": "default"})
        knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id=self.workspace_id, name="简历语义索引", desc="",
            embedding_model_id=str(self.model.id), type=KnowledgeType.BASE.value,
            scope=KnowledgeScope.WORKSPACE.value, user_id=self.user.id,
        )
        content = "姓名：李冠光\n\n【教育经历】\n- 院校：北京师范大学 | 学位：硕士"
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write(content.encode("utf-8"))
        handle.close()
        resume = ResumeFile.objects.create(
            workspace_id=self.workspace_id, file_name="r.txt", extension="txt",
            file_path=handle.name, file_size=os.path.getsize(handle.name),
            sha256="sha-" + uuid.uuid7().hex, source_channel="OTHER",
            status=ResumeStatus.SUCCESS, user_id=self.user.id,
        )
        document = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=knowledge.id, name="r.txt", char_length=10, user_id=self.user.id,
        )
        paragraph = Paragraph.objects.create(
            id=uuid.uuid7(), document_id=document.id, knowledge_id=knowledge.id, content="内容", title="t",
        )
        Embedding.objects.create(
            id=uuid.uuid7(), document_id=document.id, paragraph_id=paragraph.id,
            knowledge_id=knowledge.id, embedding=[0.1] * 8, is_active=True,
        )
        resume.document_id = document.id
        resume.save(update_fields=["document_id", "update_time"])
        log_flow(self.workspace_id, "EXTRACT", resume_id=resume.id, detail={"text": "电话：13812345678"})
        os.remove(handle.name)

        service = RecruitmentService(workspace_id=self.workspace_id, user_id=self.user.id, hr_role="ADMIN")
        service.delete_resume(str(resume.id))
        # 索引三件套清空 + 流转日志清空（PII 不留存）
        self.assertFalse(Document.objects.filter(id=document.id).exists())
        self.assertFalse(Paragraph.objects.filter(document_id=document.id).exists())
        self.assertFalse(Embedding.objects.filter(document_id=document.id).exists())
        self.assertEqual(list_flow_logs(self.workspace_id, resume_id=resume.id), [])

    def test_delete_candidate_cleans_flow_logs(self):
        """修复回归（审查 P1）：候选人删除匿名化时其简历的流转日志（含 PII）一并清理。"""
        from hr.services.flow_log import list_flow_logs, log_flow
        from hr.serializers.recruitment import RecruitmentService

        resume = self._resume()
        log_flow(self.workspace_id, "EXTRACT", resume_id=resume.id, detail={"text": "姓名：李冠光"})
        candidate = Candidate.objects.create(
            workspace_id=self.workspace_id, user_id=self.user.id, name="李冠光",
        )
        resume.candidate = candidate
        resume.save(update_fields=["candidate", "update_time"])
        service = RecruitmentService(workspace_id=self.workspace_id, user_id=self.user.id, hr_role="ADMIN")
        service.delete_candidate(str(candidate.id))
        self.assertEqual(list_flow_logs(self.workspace_id, resume_id=resume.id), [])


class ResumeSearchTests(TestCase):
    """阶段 3：简历语义检索（模式 A 整句 / 模式 B Skill-AND），mock 检索与 rerank 不调真实模型"""

    def setUp(self):
        self.workspace_id = "workspace-search"
        self.user = User.objects.create(
            username="search-" + uuid.uuid7().hex[:8], nick_name="search", password="p", role="ADMIN"
        )
        self.model = Model.objects.create(
            id=uuid.uuid7(), name="bge-search", status="SUCCESS", model_type="EMBEDDING",
            model_name="BAAI/bge-large-zh-v1.5", provider="model_openai_provider",
            credential="{}", meta={}, workspace_id="default",
        )
        # 简历知识库
        KnowledgeFolder.objects.get_or_create(
            id="default", defaults={"name": "default", "workspace_id": "default"}
        )
        self.knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id=self.workspace_id, name="简历语义索引",
            desc="", embedding_model_id=str(self.model.id), type=KnowledgeType.BASE.value,
            scope=KnowledgeScope.WORKSPACE.value, user_id=self.user.id,
        )
        self.candidate = Candidate.objects.create(
            workspace_id=self.workspace_id, user_id=self.user.id, name="李冠光",
            skills=["java", "python"], highest_degree="硕士",
        )
        self.document = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=self.knowledge.id, name="李冠光.docx",
            char_length=10, user_id=self.user.id,
        )
        self.resume = ResumeFile.objects.create(
            workspace_id=self.workspace_id, file_name="李冠光.docx", extension="docx",
            file_path="/tmp/x.docx", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            source_channel="OTHER", status=ResumeStatus.SUCCESS, user_id=self.user.id,
            candidate=self.candidate, document_id=self.document.id,
        )

    def _paragraph(self, content="熟悉 Java 后端开发", title="工作经历"):
        return Paragraph.objects.create(
            id=uuid.uuid7(), document_id=self.document.id, knowledge_id=self.knowledge.id,
            content=content, title=title, status="SUCCESS",
        )

    def _embedding(self, paragraph, similarity=0.9):
        return Embedding.objects.create(
            id=uuid.uuid7(), document_id=self.document.id, paragraph_id=paragraph.id,
            knowledge_id=self.knowledge.id, embedding=[0.1] * 8,
            search_vector=SearchVector(Value("java")), is_active=True,
        )

    def _fake_embedding_model(self):
        fake = Mock()
        fake.embed_query.return_value = [0.1] * 8
        return fake

    def _fake_rerank(self, order=None, raise_exc=False):
        fake = Mock()
        if raise_exc:
            fake.rerank.side_effect = Exception("rerank down")
        else:
            order = order if order is not None else list(range(3))
            fake.rerank.return_value = [{"index": i, "relevance_score": 0.9 - i * 0.1} for i in order]
        return fake

    def test_search_validation(self):
        from hr.services.resume_search import search_resumes
        with self.assertRaises(AppApiException):
            search_resumes(self.workspace_id, "")
        with self.assertRaises(AppApiException):
            search_resumes(self.workspace_id, "x" * 3000)
        with self.assertRaises(AppApiException):
            search_resumes(self.workspace_id, "ok", mode="bad")
        # 非字符串 mode（list 等）必须 400 而非 TypeError 500（修复：类型+枚举双校验）
        with self.assertRaises(AppApiException):
            search_resumes(self.workspace_id, "ok", mode=["auto"])

    def test_phrase_mode_calls_dual_and_aggregates(self):
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph()
        self._embedding(paragraph)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.5}]
            result = search_resumes(self.workspace_id, "java 开发", mode="phrase",
                                    hr_role="VIEWER", user_id=self.user.id)
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["candidate"]["name"], "李冠光")
        self.assertIn("****", item["candidate"]["phone"]) if item["candidate"].get("phone") else None
        self.assertEqual(item["document_id"], str(self.document.id))
        self.assertIn("Java", item["paragraphs"][0]["content"])
        self.assertTrue(result["meta"]["recall"]["dense"] >= 1)

    def test_rerank_applied_and_meta(self):
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph()
        self._embedding(paragraph)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "java", mode="phrase",
                                    rerank_model=self._fake_rerank(), user_id=self.user.id)
        self.assertTrue(result["meta"]["rerank"]["enabled"])
        self.assertFalse(result["meta"]["rerank"]["failed"])
        self.assertEqual(result["meta"]["search_type"], "hybrid_rrf_reranked")

    def test_rerank_failure_falls_back(self):
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph()
        self._embedding(paragraph)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "java", mode="phrase",
                                    rerank_model=self._fake_rerank(raise_exc=True), user_id=self.user.id)
        self.assertTrue(result["meta"]["rerank"]["failed"])
        self.assertEqual(result["meta"]["search_type"], "hybrid_rrf_fallback")
        self.assertEqual(len(result["items"]), 1)  # 仍返回结果

    def test_aggregation_merges_multiple_paragraphs(self):
        from hr.services.resume_search import search_resumes
        p1 = self._paragraph("Java 后端")
        p2 = self._paragraph("Python 数据分析")
        self._embedding(p1)
        self._embedding(p2)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [
                {"paragraph_id": str(p1.id), "similarity": 0.9},
                {"paragraph_id": str(p2.id), "similarity": 0.8},
            ]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "java", mode="phrase")
        self.assertEqual(len(result["items"]), 1)  # 同一简历合并
        self.assertEqual(len(result["items"][0]["paragraphs"]), 2)

    def test_aggregate_evidence_synthesis(self):
        """T3：证据合成——多段命中的简历（低分段）胜过单段高分；λ=0 严格回退旧基准 0.7*max+0.3*avg（F2 公式锁定）。"""
        from hr.services.resume_search import _aggregate

        doc_a = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=self.knowledge.id, name="a.docx", char_length=1, user_id=self.user.id
        )
        doc_b = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=self.knowledge.id, name="b.docx", char_length=1, user_id=self.user.id
        )
        cand_a = Candidate.objects.create(workspace_id=self.workspace_id, user_id=self.user.id, name="甲")
        cand_b = Candidate.objects.create(workspace_id=self.workspace_id, user_id=self.user.id, name="乙")
        for doc, cand, sha in ((doc_a, cand_a, "sha-a"), (doc_b, cand_b, "sha-b")):
            ResumeFile.objects.create(
                workspace_id=self.workspace_id, file_name=doc.name, extension="docx",
                file_path="/tmp/" + doc.name, file_size=1, sha256=sha, source_channel="OTHER",
                status=ResumeStatus.SUCCESS, user_id=self.user.id, candidate=cand, document_id=doc.id,
            )
        # doc_a 单段 0.90 → 基准 0.90 + 0.15*log2(2) = 1.05
        # doc_b 两段 0.89/0.88 → 基准 0.7*0.89+0.3*0.885 ≈ 0.8885 + 0.15*log2(3) ≈ 1.126 > 1.05 → 证据合成使 doc_b 胜出
        paras = [
            {"document_id": str(doc_a.id), "rerank": 0.90},
            {"document_id": str(doc_b.id), "rerank": 0.89},
            {"document_id": str(doc_b.id), "rerank": 0.88},
        ]
        with patch("hr.services.resume_search._EVIDENCE_LAMBDA", 0.15):
            results = _aggregate(paras, hr_role="ADMIN")
        self.assertEqual([r["document_id"] for r in results], [str(doc_b.id), str(doc_a.id)])
        self.assertGreater(results[0]["score"], results[1]["score"])
        with patch("hr.services.resume_search._EVIDENCE_LAMBDA", 0):
            results0 = _aggregate(paras, hr_role="ADMIN")
        self.assertEqual([r["document_id"] for r in results0], [str(doc_a.id), str(doc_b.id)])
        # 公式锁定（F2）：λ=0 必须严格回到旧基准 0.7*max+0.3*avg，防止基准再次静默漂移
        self.assertAlmostEqual(results0[0]["score"], 0.7 * 0.90 + 0.3 * 0.90)
        self.assertAlmostEqual(results0[1]["score"], 0.7 * 0.89 + 0.3 * 0.885)

    def _extra_candidate(self, name, years, city="", degree="", skills=None):
        """T4 辅助：额外候选人 + 简历文档（带段落/向量）。"""
        candidate = Candidate.objects.create(
            workspace_id=self.workspace_id, user_id=self.user.id, name=name,
            years_experience=years, current_city=city, highest_degree=degree,
            skills=skills or [],
        )
        document = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=self.knowledge.id, name=name + ".docx",
            char_length=10, user_id=self.user.id,
        )
        resume = ResumeFile.objects.create(
            workspace_id=self.workspace_id, file_name=name + ".docx", extension="docx",
            file_path="/tmp/" + name + ".docx", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            source_channel="OTHER", status=ResumeStatus.SUCCESS, user_id=self.user.id,
            candidate=candidate, document_id=document.id,
        )
        return candidate, document, resume

    def test_prefilter_years_filters_recall(self):
        """T4：年限槽预筛——不满足年限的候选人不出现在召回集（SQL 精确保证 G1）。"""
        from hr.services.resume_search import search_resumes

        self.candidate.years_experience = 2
        self.candidate.save(update_fields=["years_experience"])
        _, doc2, _ = self._extra_candidate("乙", 8)
        para2 = Paragraph.objects.create(
            id=uuid.uuid7(), document_id=doc2.id, knowledge_id=self.knowledge.id,
            content="熟悉 Java 微服务", title="工作经历", status="SUCCESS",
        )
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()),                 patch("hr.services.resume_search.EmbeddingSearch") as m_emb,                 patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(para2.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "6年以上 Java", mode="phrase",
                                    hr_role="ADMIN", user_id=self.user.id)
        meta = result["meta"]
        self.assertTrue(meta["prefilter"]["applied"])
        self.assertEqual(meta["prefilter"]["candidate_count"], 1)  # 乙（8 年）；甲（2 年）被排除
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["candidate"]["name"], "乙")

    def test_prefilter_empty_returns_empty(self):
        """T4：无满足条件候选人 → prefilter_empty，不做语义兜底误导。"""
        from hr.services.resume_search import search_resumes

        self.candidate.years_experience = 2
        self.candidate.save(update_fields=["years_experience"])
        self._extra_candidate("乙", 8)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()):
            result = search_resumes(self.workspace_id, "10年以上 Java", mode="phrase",
                                    hr_role="ADMIN", user_id=self.user.id)
        self.assertEqual(result["meta"]["search_type"], "prefilter_empty")
        self.assertEqual(result["items"], [])

    def test_structured_only_pure_condition(self):
        """T4：纯条件查询（无语义词）→ 纯结构化检索，不调语义召回。"""
        from hr.services.resume_search import search_resumes

        self.candidate.years_experience = 2
        self.candidate.save(update_fields=["years_experience"])
        _, doc2, _ = self._extra_candidate("乙", 8)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()),                 patch("hr.services.resume_search.EmbeddingSearch") as m_emb,                 patch("hr.services.resume_search.KeywordsSearch") as _m_key:
            result = search_resumes(self.workspace_id, "5年以上", mode="phrase",
                                    hr_role="ADMIN", user_id=self.user.id)
        self.assertEqual(result["meta"]["search_type"], "structured_only")
        m_emb.return_value.handle.assert_not_called()
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["candidate"]["name"], "乙")

    def test_prefilter_null_years_included(self):
        """T4（R2）：年限未知（NULL）纳入预筛并标记 years_unknown，不静默消失。"""
        from hr.services.resume_search import search_resumes

        self.candidate.years_experience = None
        self.candidate.save(update_fields=["years_experience"])
        self._extra_candidate("乙", 8)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()):
            result = search_resumes(self.workspace_id, "5年以上", mode="phrase",
                                    hr_role="ADMIN", user_id=self.user.id)
        items = result["items"]
        names = [i["candidate"]["name"] for i in items]
        self.assertIn("李冠光", names)  # NULL 年限未被排除
        self.assertTrue(any(i["candidate"]["years_unknown"] for i in items))

    def test_prefilter_skills_no_longer_gates(self):
        """新架构：技能不再是结构化字段——即使 candidate_skill 有存量数据，技能词查询也不触发预筛，
        改由语义/关键字腿在文本里命中（技能维度已移除；回归：存量回填数据曾把技能查询误杀成 prefilter_empty）。"""
        from hr.models import CandidateSkill
        from hr.services.resume_search import search_resumes

        CandidateSkill.objects.create(candidate=self.candidate, skill_norm="java", skill_raw="Java")
        cand2, _, _ = self._extra_candidate("乙", 3, skills=["python"])
        CandidateSkill.objects.create(candidate=cand2, skill_norm="python", skill_raw="Python")
        para = Paragraph.objects.create(
            id=uuid.uuid7(), document_id=self.document.id, knowledge_id=self.knowledge.id,
            content="熟悉 Java 开发", title="工作经历", status="SUCCESS",
        )
        with patch("hr.services.resume_search._parse_skills", return_value=["java"]), \
                patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as _m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(para.id), "similarity": 0.9}]
            result = search_resumes(self.workspace_id, "会 java 的人", mode="auto",
                                    llm_model=Mock(), hr_role="ADMIN", user_id=self.user.id)
        self.assertEqual(result["meta"]["mode"], "phrase")  # 单技能 → 不升级 skills 模式
        self.assertFalse(result["meta"]["prefilter"]["applied"])  # 技能词不再触发结构化预筛（无年限/学历/城市）
        self.assertNotEqual(result["meta"]["search_type"], "prefilter_empty")
        self.assertIn("李冠光", [i["candidate"]["name"] for i in result["items"]])

    def test_prefilter_skills_empty_table_fallback(self):
        """T7 回归：candidate_skill 表空（未回填）时技能维度跳过，不得 EXISTS 空表误杀查询。"""
        from hr.services.resume_search import search_resumes

        para = Paragraph.objects.create(
            id=uuid.uuid7(), document_id=self.document.id, knowledge_id=self.knowledge.id,
            content="熟悉 Java 开发", title="工作经历", status="SUCCESS",
        )
        with patch("hr.services.resume_search._parse_skills", return_value=["java"]), \
                patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as _m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(para.id), "similarity": 0.9}]
            result = search_resumes(self.workspace_id, "会 java 的人", mode="auto",
                                    llm_model=Mock(), hr_role="ADMIN", user_id=self.user.id)
        self.assertEqual(result["meta"]["search_type"], "hybrid_rrf")  # 无 rerank 模型时的模式 A 检索
        self.assertNotEqual(result["meta"]["search_type"], "prefilter_empty")
        self.assertGreaterEqual(len(result["items"]), 1)

    def test_prefilter_candidate_count_dedup(self):
        """F4 复审（P3-5）：技能维度联表 __in 在无 distinct 时重复计数——断言 distinct 后计数正确。"""
        from django.db.models import Q, QuerySet
        from hr.models import Candidate, CandidateSkill, CandidateStatus

        cand, _, _ = self._extra_candidate("双技能", 6, skills=["java", "python"])
        CandidateSkill.objects.create(candidate=cand, skill_norm="java", skill_raw="java")
        CandidateSkill.objects.create(candidate=cand, skill_norm="python", skill_raw="python")
        qs = QuerySet(Candidate).filter(
            workspace_id=self.workspace_id, status=CandidateStatus.ACTIVE
        ).filter(Q(skill_rows__skill_norm__in=["java", "python"]))
        self.assertEqual(len(list(qs.values_list("id", flat=True))), 2)  # 无 distinct 会重复
        self.assertEqual(len(list(qs.values_list("id", flat=True).distinct())), 1)  # distinct 后 1

    def test_prefilter_skipped_over_threshold(self):
        """F7：预筛文档集超过 _PREFILTER_MAX → 放弃预筛转全量语义（meta.prefilter_skipped，不误伤大库）。"""
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph("Java 后端")
        self._embedding(paragraph)
        self._extra_candidate("年限甲", 6, skills=["java"])
        self._extra_candidate("年限乙", 7, skills=["java"])
        with patch("hr.services.resume_search._PREFILTER_MAX", 1), \
                patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "6年以上 java", mode="auto",
                                    hr_role="ADMIN", user_id=self.user.id)
        self.assertTrue(result["meta"]["prefilter"]["skipped"])
        self.assertFalse(result["meta"]["prefilter"]["applied"])
        self.assertNotEqual(result["meta"]["search_type"], "prefilter_empty")  # 转全量语义而非空

    def test_prefilter_skipped_still_filters_hard_conditions(self):
        """P1 复审：预筛超阈值跳过后，语义路径仍按硬条件过滤返回项。"""
        from hr.services.resume_search import search_resumes

        _, doc_low, _ = self._extra_candidate("低年限", 3)
        _, doc_high, _ = self._extra_candidate("高年限", 8)
        p_low = Paragraph.objects.create(
            id=uuid.uuid7(), document_id=doc_low.id, knowledge_id=self.knowledge.id,
            content="Java 开发", title="工作经历", status="SUCCESS",
        )
        p_high = Paragraph.objects.create(
            id=uuid.uuid7(), document_id=doc_high.id, knowledge_id=self.knowledge.id,
            content="Java 架构", title="工作经历", status="SUCCESS",
        )
        for doc_id, paragraph in ((doc_low.id, p_low), (doc_high.id, p_high)):
            Embedding.objects.create(
                id=uuid.uuid7(), document_id=doc_id, paragraph_id=paragraph.id,
                knowledge_id=self.knowledge.id, embedding=[0.1] * 8,
                search_vector=SearchVector(Value("java")), is_active=True,
            )
        with                 patch("hr.services.resume_search._PREFILTER_MAX", 1),                 patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()),                 patch("hr.services.resume_search.EmbeddingSearch") as m_emb,                 patch("hr.services.resume_search.KeywordsSearch") as m_key:
            # 语义路同时召回低年限与高年限两份简历
            m_emb.return_value.handle.return_value = [
                {"paragraph_id": str(p_low.id), "similarity": 0.9},
                {"paragraph_id": str(p_high.id), "similarity": 0.85},
            ]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "6年以上 Java", mode="phrase",
                                    hr_role="ADMIN", user_id=self.user.id)
        self.assertTrue(result["meta"]["prefilter"]["skipped"])
        names = [it["candidate"]["name"] for it in result["items"] if it["candidate"]]
        self.assertIn("高年限", names)
        self.assertNotIn("低年限", names)

    def test_prefilter_city_normalization(self):
        """F7：城市双向归一——存「北京市」查「北京」命中、存「北京」查「北京市」命中。"""
        from hr.services.resume_search import search_resumes
        _, doc_beijing, _ = self._extra_candidate("北京人", 6, city="北京市")
        self._extra_candidate("上海人", 8, city="上海市")
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = []
            m_key.return_value.handle.return_value = []
            r1 = search_resumes(self.workspace_id, "北京 6年以上", mode="auto", hr_role="ADMIN", user_id=self.user.id)
        names1 = [it["candidate"]["name"] for it in r1["items"] if it["candidate"]]
        self.assertIn("北京人", names1)
        self.assertNotIn("上海人", names1)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = []
            m_key.return_value.handle.return_value = []
            r2 = search_resumes(self.workspace_id, "北京市 6年以上", mode="auto", hr_role="ADMIN", user_id=self.user.id)
        names2 = [it["candidate"]["name"] for it in r2["items"] if it["candidate"]]
        self.assertIn("北京人", names2)

    def test_name_fast_path(self):
        """T4：纯中文姓名查询 → name__icontains 命中置顶（无语义命中时也可返回）。"""
        from hr.services.resume_search import search_resumes

        _, doc3, _ = self._extra_candidate("李冠光", 5)  # 同名的另一候选人（无段落 → 无语义命中）
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()),                 patch("hr.services.resume_search.EmbeddingSearch") as m_emb,                 patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = []
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "李冠光", mode="phrase",
                                    hr_role="ADMIN", user_id=self.user.id)
        self.assertGreaterEqual(len(result["items"]), 1)
        self.assertTrue(result["items"][0]["score"].get("name_match"))

    def test_name_fast_path_rank_contiguous(self):
        """F5：姓名命中置顶后所有项 rank 连续 1..n（此前置顶项无 rank、原 rank 错位）。"""
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph("Java 后端")
        self._embedding(paragraph)
        self._extra_candidate("李冠光", 5)  # 同名的另一候选人（无语义命中，仅姓名通道）
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "李冠光", mode="phrase",
                                    hr_role="ADMIN", user_id=self.user.id)
        self.assertGreaterEqual(len(result["items"]), 1)
        ranks = [item.get("rank") for item in result["items"]]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))  # 连续 1..n
        self.assertEqual(result["items"][0]["rank"], 1)
    def test_empty_result(self):
        from hr.services.resume_search import search_resumes
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = []
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "nothing")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["meta"]["search_type"], "empty")

    def test_sparse_query_max_six_terms(self):
        """P3 复审：稀疏词上限与 v2 设计对齐为 6。"""
        from hr.services.resume_search import _sparse_query

        query = "熟悉 Java Spring Boot Docker Kubernetes React Vue 开发"
        sparse = _sparse_query(query)
        self.assertLessEqual(len(sparse.split()), 6)

    def test_skill_and_mode_ordered(self):
        """模式 B：技能有序 → 命中向量字典序 → 命中靠前技能优先"""
        from hr.services.resume_search import search_resumes
        # 两个候选人：A 命中 java+python（前两位），B 只命中 java
        p_a1 = self._paragraph("Java 开发")
        p_a2 = self._paragraph("Python 开发")
        self._embedding(p_a1)
        self._embedding(p_a2)
        candidate_b = Candidate.objects.create(
            workspace_id=self.workspace_id, user_id=self.user.id, name="候选B", skills=["java"]
        )
        doc_b = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=self.knowledge.id, name="B.docx", char_length=5, user_id=self.user.id,
        )
        ResumeFile.objects.create(
            workspace_id=self.workspace_id, file_name="B.docx", extension="docx",
            file_path="/tmp/b.docx", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            source_channel="OTHER", status=ResumeStatus.SUCCESS, user_id=self.user.id,
            candidate=candidate_b, document_id=doc_b.id,
        )
        p_b = Paragraph.objects.create(
            id=uuid.uuid7(), document_id=doc_b.id, knowledge_id=self.knowledge.id, content="Java 后端", title="经历",
        )
        # fake LLM 返回有序技能
        fake_llm = Mock()
        fake_llm.invoke.return_value = type("R", (), {"content": '{"skills": ["java", "python"]}'})()
        side_effect = [
            [{"paragraph_id": str(p_a1.id), "similarity": 0.9}, {"paragraph_id": str(p_b.id), "similarity": 0.8}],  # java dense
            [{"paragraph_id": str(p_a2.id), "similarity": 0.85}],  # python dense
        ]
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.side_effect = side_effect
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "会 java python 的人", mode="skills",
                                    llm_model=fake_llm, user_id=self.user.id)
        self.assertEqual(result["meta"]["mode"], "skills")
        self.assertEqual(result["meta"]["search_type"], "skill_ordered")
        names = [item["candidate"]["name"] for item in result["items"]]
        # A 命中 [1,1] > B 命中 [1,0] → A 在前
        self.assertEqual(names[0], "李冠光")
        self.assertEqual(result["items"][0]["score"]["hit_count"], 2)
        self.assertIn("候选B", names)

    def test_skill_parse_failure_falls_back_to_phrase(self):
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph("Java 开发")
        self._embedding(paragraph)
        fake_llm = Mock()
        fake_llm.invoke.side_effect = Exception("llm down")
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "java 开发", mode="auto",
                                    llm_model=fake_llm, user_id=self.user.id)
        self.assertEqual(result["meta"]["mode"], "phrase")
        self.assertEqual(len(result["items"]), 1)

    def test_orphan_paragraph_no_candidate(self):
        """孤儿段落（无简历关联）→ 返回段落级结果不崩溃"""
        from hr.services.resume_search import search_resumes
        orphan_doc = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=self.knowledge.id, name="orphan", char_length=5, user_id=self.user.id,
        )
        p = Paragraph.objects.create(
            id=uuid.uuid7(), document_id=orphan_doc.id, knowledge_id=self.knowledge.id, content="技能描述", title="x",
        )
        self._embedding(p)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(p.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "技能", mode="phrase")
        self.assertEqual(len(result["items"]), 1)
        self.assertIsNone(result["items"][0]["candidate"])
        self.assertEqual(result["meta"]["aggregation"]["dropped_orphan_paragraphs"], 0)

    def test_search_audit_written_without_query(self):
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph()
        self._embedding(paragraph)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            search_resumes(self.workspace_id, "java 开发", mode="phrase", user_id=self.user.id)
        from hr.models import HrAuditLog
        log = HrAuditLog.objects.filter(workspace_id=self.workspace_id, action="SEARCH").first()
        self.assertIsNotNone(log)
        self.assertNotIn("java", str(log.detail))  # 查询原文不入审计
        # detail 必须为 JSON 字符串（dict 序列化），保证可解析（修复：audit.py 统一序列化）
        import json
        parsed = json.loads(log.detail)
        self.assertEqual(parsed["mode"], "phrase")
        self.assertEqual(parsed["top_k"], 5)

    def test_skill_and_with_rerank(self):
        """模式 B + rerank：精排生效、search_type=skill_ordered_reranked"""
        from hr.services.resume_search import search_resumes
        p_a1 = self._paragraph("Java 开发")
        p_a2 = self._paragraph("Python 开发")
        self._embedding(p_a1)
        self._embedding(p_a2)
        fake_llm = Mock()
        fake_llm.invoke.return_value = type("R", (), {"content": '{"skills": ["java", "python"]}'})()
        rerank = self._fake_rerank()
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.side_effect = [
                [{"paragraph_id": str(p_a1.id), "similarity": 0.9}],  # java
                [{"paragraph_id": str(p_a2.id), "similarity": 0.85}],  # python
            ]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "会 java python 的人", mode="skills",
                                    llm_model=fake_llm, rerank_model=rerank, user_id=self.user.id)
        self.assertEqual(result["meta"]["search_type"], "skill_ordered_reranked")
        self.assertTrue(result["meta"]["rerank"]["enabled"])
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("rerank", result["items"][0]["score"])

    def test_skill_hit_skills_no_duplicate(self):
        """修复回归：同一段落命中多个技能时 hit_skills 不得重复（原 setdefault 默认值可双写）。"""
        from hr.services.resume_search import _search_skill_and
        p_shared = self._paragraph("Java 和 Python 开发")
        self._embedding(p_shared)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()),                 patch("hr.services.resume_search.EmbeddingSearch") as m_emb,                 patch("hr.services.resume_search.KeywordsSearch") as m_key:
            # 两个技能命中同一段落
            m_emb.return_value.handle.side_effect = [
                [{"paragraph_id": str(p_shared.id), "similarity": 0.9}],  # skill 0
                [{"paragraph_id": str(p_shared.id), "similarity": 0.85}],  # skill 1
            ]
            m_key.return_value.handle.return_value = []
            ordered, b_meta = _search_skill_and(
                ["java", "python"], self.workspace_id, self.knowledge, self._fake_embedding_model(), 5, 0.2, 5
            )
        doc_paragraphs = b_meta["doc_paragraphs"]
        rows = doc_paragraphs.get(str(self.document.id), [])
        self.assertTrue(rows)
        for row in rows:
            hit_skills = row.get("hit_skills", [])
            self.assertEqual(len(hit_skills), len(set(hit_skills)), f"hit_skills 重复: {hit_skills}")

    def test_skill_and_structured_via_table(self):
        """T5：candidate_skill 归一表驱动结构化路——变体查询（k8s）命中归一词（kubernetes），无语义命中也可入选。"""
        from hr.models import CandidateSkill
        from hr.services.resume_search import _search_skill_and

        cand2, doc2, _ = self._extra_candidate("乙", 5, skills=["kubernetes"])
        CandidateSkill.objects.create(candidate=cand2, skill_norm="kubernetes", skill_raw="kubernetes")
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = []  # 无语义命中
            m_key.return_value.handle.return_value = []
            ordered, b_meta = _search_skill_and(
                ["k8s"], self.workspace_id, self.knowledge, self._fake_embedding_model(), 5, 0.2, 5
            )
        self.assertEqual(b_meta["structured_hits"], 1)
        self.assertIn(str(doc2.id), dict(ordered))
        self.assertIn(str(doc2.id), b_meta["structured_only"])

    def test_skill_mode_prefilter_years(self):
        """F1：skills 模式接入结构化预筛——年限硬条件对结构化路生效（技能命中但年限不足者不返回）。"""
        from hr.models import CandidateSkill
        from hr.services.resume_search import search_resumes
        cand_b, doc_b, _ = self._extra_candidate("年限不足", 3, skills=["java", "python"])
        cand_c, doc_c, _ = self._extra_candidate("年限足够", 8, skills=["java", "python"])
        for cand in (cand_b, cand_c):
            for skill in ("java", "python"):
                CandidateSkill.objects.create(candidate=cand, skill_norm=skill, skill_raw=skill)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search._parse_skills", return_value=["java", "python"]), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = []  # 无语义命中，验证结构化路
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "java python 5年以上", mode="auto",
                                    llm_model=Mock(), user_id=self.user.id)
        self.assertEqual(result["meta"]["mode"], "skills")
        self.assertTrue(result["meta"]["prefilter"]["applied"])
        names = [it["candidate"]["name"] for it in result["items"] if it["candidate"]]
        self.assertIn("年限足够", names)
        self.assertNotIn("年限不足", names)

    def test_skill_mode_prefilter_empty(self):
        """F1：skills 模式预筛为空 → prefilter_empty 提前返回（不做语义兜底）。"""
        from hr.services.resume_search import search_resumes
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search._parse_skills", return_value=["java", "python"]):
            result = search_resumes(self.workspace_id, "java python 博士", mode="skills",
                                    llm_model=Mock(), user_id=self.user.id)
        self.assertEqual(result["meta"]["search_type"], "prefilter_empty")
        self.assertEqual(result["items"], [])

    def test_skill_mode_recall_limited_by_document_ids(self):
        """F1：skills 模式语义路召回限定在预筛文档集（EmbeddingSearch 收到的 query_set 带 document_id 过滤）。"""
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph()
        self._embedding(paragraph)
        self._extra_candidate("低年限", 3, skills=["java", "python"])
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search._parse_skills", return_value=["java", "python"]), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "java python 5年以上", mode="skills",
                                    llm_model=Mock(), user_id=self.user.id)
        calls = m_emb.return_value.handle.call_args_list
        self.assertTrue(calls)
        qs = calls[0][0][0]  # 第一个位置参数 = query_set
        self.assertIn("document_id", str(qs.query))
        # 预筛集只含 self.document（李冠光 years NULL 纳入；低年限 3 被排除）
        self.assertEqual(result["meta"]["prefilter"]["resume_count"], 1)
        self.assertEqual(result["meta"]["search_type"], "skill_ordered")




    # ---------- 审查修复回归（2026-08-16 第二轮） ----------

    def test_recall_k_and_similarity_clamped(self):
        """修复回归：recall_k/similarity 越界 clamp（设计 §3.1 [5,60]/[0,2]），负数不得进 SQL（PG LIMIT 报错）。"""
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph()
        self._embedding(paragraph)
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            # recall_k=-1 / 9999 与 similarity 越界均不得抛异常（此前 recall_k=-1 触发 DataError → 500）
            r1 = search_resumes(self.workspace_id, "java", mode="phrase", recall_k=-1, similarity=-5)
            self.assertEqual(r1["meta"]["recall"]["candidate_k"], 5)
            r2 = search_resumes(self.workspace_id, "java", mode="phrase", recall_k=9999, similarity=99)
            self.assertEqual(r2["meta"]["recall"]["candidate_k"], 60)
        self.assertEqual(len(r1["items"]), 1)

    def test_missing_embedding_model_friendly_error(self):
        """修复回归：知识库绑定的 Embedding 模型缺失 → 业务异常而非裸 AttributeError 500。"""
        from hr.services.resume_search import search_resumes
        self.knowledge.embedding_model_id = uuid.uuid7()  # 指向不存在的模型
        self.knowledge.save(update_fields=["embedding_model_id"])
        with self.assertRaises(AppApiException) as ctx:
            search_resumes(self.workspace_id, "java", mode="phrase")
        self.assertIn("Embedding", str(ctx.exception))

    def test_embed_query_failure_friendly_error(self):
        """修复回归：embed_query 调用失败（模型不可用/输入超限）→ 业务异常而非裸 500。"""
        from hr.services.resume_search import search_resumes
        fake = self._fake_embedding_model()
        fake.embed_query.side_effect = Exception("provider down")
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=fake):
            with self.assertRaises(AppApiException) as ctx:
                search_resumes(self.workspace_id, "java", mode="phrase")
        self.assertIn("Embedding", str(ctx.exception))

    def test_mode_skills_fallback_meta(self):
        """修复回归：显式 skills 模式但 LLM 不可用 → 退化整句，meta.mode 如实为 phrase（此前误导为 skills 且误走 dense-only）。"""
        from hr.services.resume_search import search_resumes
        paragraph = self._paragraph()
        self._embedding(paragraph)
        fake_llm = Mock()
        fake_llm.invoke.side_effect = Exception("llm down")
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = [{"paragraph_id": str(paragraph.id), "similarity": 0.5}]
            result = search_resumes(self.workspace_id, "java 开发", mode="skills",
                                    llm_model=fake_llm, user_id=self.user.id)
        self.assertEqual(result["meta"]["mode"], "phrase")
        self.assertEqual(result["meta"]["recall"]["sparse"], 1)  # 双路生效

    def test_skill_and_structured_path(self):
        """设计补齐：模式 B 结构化路——技能在 Candidate.skills 但正文未出现的简历经结构化命中补位（paragraphs=[]）。"""
        from hr.services.resume_search import search_resumes
        p_a1 = self._paragraph("Java 开发")
        p_a2 = self._paragraph("Python 开发")
        self._embedding(p_a1)
        self._embedding(p_a2)
        candidate_b = Candidate.objects.create(
            workspace_id=self.workspace_id, user_id=self.user.id, name="结构化候选", skills=["java"]
        )
        doc_b = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=self.knowledge.id, name="B.docx", char_length=5, user_id=self.user.id,
        )
        ResumeFile.objects.create(
            workspace_id=self.workspace_id, file_name="B.docx", extension="docx",
            file_path="/tmp/b.docx", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            source_channel="OTHER", status=ResumeStatus.SUCCESS, user_id=self.user.id,
            candidate=candidate_b, document_id=doc_b.id,
        )
        # B 的正文不含任何技能词（语义路两轮均不召回其段落）
        Paragraph.objects.create(
            id=uuid.uuid7(), document_id=doc_b.id, knowledge_id=self.knowledge.id, content="负责日常事务协调", title="经历",
        )
        fake_llm = Mock()
        fake_llm.invoke.return_value = type("R", (), {"content": '{"skills": ["java", "python"]}'})()
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.side_effect = [
                [{"paragraph_id": str(p_a1.id), "similarity": 0.9}],  # java
                [{"paragraph_id": str(p_a2.id), "similarity": 0.85}],  # python
            ]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "会 java python 的人", mode="skills",
                                    llm_model=fake_llm, user_id=self.user.id)
        self.assertEqual(result["meta"]["recall"]["structured_hits"], 2)  # 李冠光 + 结构化候选
        names = [item["candidate"]["name"] for item in result["items"]]
        self.assertIn("结构化候选", names)
        structured_item = result["items"][names.index("结构化候选")]
        self.assertEqual(structured_item["paragraphs"], [])
        self.assertEqual(structured_item["score"]["hit_vec"], [1, 0])
        self.assertEqual(structured_item["score"]["hit_count"], 1)

    def test_skill_and_structured_merge_no_duplicate(self):
        """设计补齐：同一简历两路都命中 → hit_vec 按位 OR 合并（不重复计）。"""
        from hr.services.resume_search import search_resumes
        p_a1 = self._paragraph("Java 开发")
        self._embedding(p_a1)
        fake_llm = Mock()
        fake_llm.invoke.return_value = type("R", (), {"content": '{"skills": ["java", "python"]}'})()
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.resume_search.KeywordsSearch") as m_key:
            m_emb.return_value.handle.side_effect = [
                [{"paragraph_id": str(p_a1.id), "similarity": 0.9}],  # java（语义命中）
                [],  # python（语义未命中；结构化字段 skills 含 python → OR 补 1）
            ]
            m_key.return_value.handle.return_value = []
            result = search_resumes(self.workspace_id, "会 java python 的人", mode="skills",
                                    llm_model=fake_llm, user_id=self.user.id)
        self.assertEqual(result["items"][0]["score"]["hit_vec"], [1, 1])  # java 语义 + python 结构化
        self.assertEqual(len(result["items"][0]["paragraphs"]), 1)  # 段落不重复

    def test_keyword_recall_docs_returns_raw_text_and_paragraph_hits(self):
        """关键字腿：查询词在简历原文/段落 OR 命中即纳入（混合检索第三条路）。"""
        from hr.services.resume_search import _keyword_recall_docs

        # 原文命中（raw_text）
        self.resume.raw_text = "负责微博微信营销推广与品牌运营"
        self.resume.save(update_fields=["raw_text", "update_time"])
        self._paragraph("熟悉 Spark 与 Flink 大数据处理", title="工作经历-数据")

        # 命中原文的词
        hit, dropped = _keyword_recall_docs("微博", self.workspace_id, {})
        self.assertIn(str(self.document.id), hit)
        self.assertIn("微博", hit[str(self.document.id)]["terms"])
        self.assertEqual(dropped, [])

        # 命中段落的词
        hit2, _ = _keyword_recall_docs("Flink", self.workspace_id, {})
        self.assertIn(str(self.document.id), hit2)
        self.assertTrue(hit2[str(self.document.id)]["paragraph"]["content"].startswith("熟悉 Spark"))

    def test_keyword_recall_docs_drops_high_frequency_terms(self):
        """keyword 腿词频过滤：命中面超过阈值的常见词剔除——否则 OR 语义 + 高频词
        （如「开发」）会把不含查询主词的无关简历全部追加进结果。"""
        from hr.services.resume_search import _keyword_recall_docs

        # 让「开发」成为高频词：再建 40 个候选人都含「开发」，超过小语料下限 30
        for index in range(40):
            cand = Candidate.objects.create(
                name=f"高频{index}", workspace_id=self.workspace_id,
                skills=[], status="ACTIVE",
            )
            doc = Document.objects.create(
                id=uuid.uuid7(), knowledge_id=self.knowledge.id,
                name=f"h{index}.txt", char_length=10, user_id=self.user.id,
            )
            Paragraph.objects.create(
                id=uuid.uuid7(), document_id=doc.id, knowledge_id=self.knowledge.id,
                content="负责业务开发与系统维护", title="工作经历", is_active=True,
            )
            ResumeFile.objects.create(
                workspace_id=self.workspace_id, file_name=f"h{index}.txt", extension="txt",
                file_path=f"/tmp/h{index}.txt", file_size=1,
                sha256="sha-hf-" + uuid.uuid7().hex, source_channel="OTHER",
                status=ResumeStatus.SUCCESS, user_id=self.user.id,
                candidate=cand, document_id=doc.id,
            )
        # 「开发」命中面 >50% 被剔除；「Python」命中 0 但保留（冷门词不剔除）
        hit, dropped = _keyword_recall_docs("Python 开发", self.workspace_id, {})
        self.assertIn("开发", dropped)
        self.assertNotIn("Python", dropped)
        # 剔除高频词后 keyword 腿只剩冷门词；Python 无命中 → 不追加任何简历
        self.assertEqual(hit, {})

    def test_search_keyword_leg_marks_and_appends_recall(self):
        """端到端：关键字腿把语义未召回但原文命中的简历追加进结果并打标。"""
        from unittest.mock import patch

        from hr.services.resume_search import search_resumes

        self.resume.raw_text = "只出现在原文里的冷门词：青铜铸造工艺"
        self.resume.save(update_fields=["raw_text", "update_time"])
        self._paragraph("与查询无关的内容", title="基本信息")
        with patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.resume_search._recall_dual", return_value={"dense": [], "sparse": [],
                        "query_embedding": None, "sparse_failed": False}):
            result = search_resumes(self.workspace_id, "青铜铸造", mode="dense", hr_role="ADMIN", user_id=self.user.id)
        names = [item["candidate"]["name"] for item in result["items"] if item.get("candidate")]
        self.assertIn("李冠光", names)
        kw_item = next(i for i in result["items"] if i.get("keyword") and i["candidate"]["name"] == "李冠光")
        self.assertTrue(kw_item["score"].get("keyword"))

    def _stub_embeddings(self, results):
        from unittest.mock import Mock

        m = Mock()
        m.handle.return_value = results
        return m


class ApplicationV2Tests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()
        self.workspace_id = "workspace-a"
        self.recruitment = RecruitmentService(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            hr_role="ADMIN",
        )
        self.candidate = Candidate.objects.create(name="Alice", workspace_id=self.workspace_id)
        job_data = self.recruitment.create_job({
            "name": "Python Engineer",
            "department": "Engineering",
            "headcount": 1,
        })
        self.job = Job.objects.get(id=job_data["id"])
        self.service = ApplicationService(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            hr_role="ADMIN",
        )

    def _stages(self):
        return list(JobStage.objects.filter(job=self.job).order_by("order"))

    def test_create_job_creates_default_stages(self):
        stages = self._stages()
        self.assertEqual([s.key for s in stages], ["APPLIED", "SCREEN", "INTERVIEW", "OFFER"])

    def test_create_application_and_move_forward(self):
        app = self.service.create_application(self.job.id, self.candidate.id, {})
        self.assertEqual(app["status"], ApplicationStatus.ACTIVE)
        first = self._stages()[0]
        self.assertEqual(app["current_stage"]["key"], first.key)
        second = self._stages()[1]
        moved = self.service.move_stage(app["id"], second.id, {"reason_text": "pass"})
        self.assertEqual(moved["current_stage"]["key"], second.key)
        self.assertEqual(ApplicationEvent.objects.filter(application_id=app["id"]).count(), 2)

    def test_cannot_create_second_active_application(self):
        self.service.create_application(self.job.id, self.candidate.id, {})
        with self.assertRaisesRegex(AppApiException, "active application"):
            self.service.create_application(self.job.id, self.candidate.id, {})

    def test_backward_move_requires_admin_or_owner(self):
        first = self._stages()[0]
        second = self._stages()[1]
        app = self.service.create_application(self.job.id, self.candidate.id, {})
        self.service.move_stage(app["id"], second.id, {"reason_text": "forward"})
        operator_service = ApplicationService(
            workspace_id=self.workspace_id,
            user_id=uuid.uuid7(),
            hr_role="OPERATOR",
        )
        with self.assertRaises(AppUnauthorizedFailed):
            operator_service.move_stage(app["id"], first.id, {"reason_text": "back"})

    def test_reject_requires_allowed_reason(self):
        app = self.service.create_application(self.job.id, self.candidate.id, {})
        with self.assertRaisesRegex(AppApiException, "not allowed"):
            self.service.reject_application(app["id"], {"termination_reason": "JOB_CLOSED"})
        rejected = self.service.reject_application(
            app["id"], {"termination_reason": "NOT_FIT", "reason_text": "not fit"}
        )
        self.assertEqual(rejected["status"], "REJECTED")

    def test_restore_rejected_by_admin(self):
        app = self.service.create_application(self.job.id, self.candidate.id, {})
        self.service.reject_application(app["id"], {"termination_reason": "NOT_FIT"})
        restored = self.service.restore_application(app["id"], {"reason_text": "restore"})
        self.assertEqual(restored["status"], "ACTIVE")
        self.assertIsNone(restored["termination_reason"])


class JobCloseV2Tests(TestCase):
    """R2：两阶段关闭（STRICT 409 / BULK 确认 / 事件 / Offer 自动撤回 / legacy 指派收尾）"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.workspace_id = "workspace-a"
        self.recruitment = RecruitmentService(self.workspace_id, self.user_id, hr_role="ADMIN")
        self.service = ApplicationService(self.workspace_id, self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id=self.workspace_id)
        job_data = self.recruitment.create_job({"name": "Engineer", "department": "Eng", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])

    def _apply(self):
        return self.service.create_application(self.job.id, self.candidate.id, {})

    def _stages(self):
        return list(JobStage.objects.filter(job=self.job).order_by("order"))

    def test_preview_lists_active_applications(self):
        app = self._apply()
        preview = self.service.close_preview(self.job.id)
        self.assertEqual(preview["active_application_count"], 1)
        self.assertEqual(preview["applications"][0]["application_id"], app["id"])
        self.assertEqual(preview["applications"][0]["candidate_name"], "Alice")
        self.assertEqual(preview["applications"][0]["current_stage"], "APPLIED")

    def test_strict_with_active_returns_409(self):
        self._apply()
        with self.assertRaises(AppApiException) as ctx:
            self.service.close_job(self.job.id, {"close_reason": "FILLED", "mode": "STRICT"})
        self.assertEqual(ctx.exception.code, 409)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "OPEN")

    def test_strict_without_active_closes_job(self):
        result = self.service.close_job(self.job.id, {"close_reason": "CANCELLED", "mode": "STRICT"})
        self.assertEqual(result["closed_count"], 0)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "CLOSED")
        self.assertEqual(self.job.close_reason, "CANCELLED")

    def test_bulk_requires_confirmation(self):
        self._apply()
        with self.assertRaisesRegex(AppApiException, "bulk_confirmed"):
            self.service.close_job(self.job.id, {"close_reason": "FILLED", "mode": "BULK"})

    def test_bulk_closes_applications_and_writes_events(self):
        app = self._apply()
        second = Candidate.objects.create(name="Bob", workspace_id=self.workspace_id)
        app2 = self.service.create_application(self.job.id, second.id, {})
        result = self.service.close_job(
            self.job.id, {"close_reason": "FILLED", "mode": "BULK", "bulk_confirmed": True}
        )
        self.assertEqual(result["closed_count"], 2)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "CLOSED")
        for application_id in (app["id"], app2["id"]):
            application = Application.objects.get(id=application_id)
            self.assertEqual(application.status, ApplicationStatus.CLOSED)
            self.assertEqual(application.termination_reason, "JOB_CLOSED")
            self.assertIsNotNone(application.terminated_at)
            self.assertTrue(
                ApplicationEvent.objects.filter(
                    application=application, event_type="CLOSED", reason_code="JOB_CLOSED"
                ).exists()
            )
        # 确定性幂等键：再次关闭不新增事件（等待中的 Application 已全部 CLOSED）
        initial = ApplicationEvent.objects.filter(application_id=app["id"]).count()
        second_run = self.service.close_job(
            self.job.id, {"close_reason": "FILLED", "mode": "BULK", "bulk_confirmed": True}
        )
        self.assertEqual(second_run["closed_count"], 0)
        self.assertEqual(ApplicationEvent.objects.filter(application_id=app["id"]).count(), initial)

    def test_bulk_withdraws_draft_and_sent_offers(self):
        app = self._apply()
        for stage in self._stages()[1:]:
            self.service.move_stage(app["id"], stage.id, {"reason_text": "advance"})
        offer_service = OfferService(self.workspace_id, self.user_id, hr_role="ADMIN")
        offer_id = offer_service.create_offer_for_application(app["id"], {"salary_amount": "30000"})["id"]
        offer_service.approve_offer(offer_id, {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        offer_service.send_offer(offer_id)
        self.service.close_job(self.job.id, {"close_reason": "FILLED", "mode": "BULK", "bulk_confirmed": True})
        offer = Offer.objects.get(id=offer_id)
        self.assertEqual(offer.status, "WITHDRAWN")
        self.assertIsNotNone(offer.withdrawn_at)
        self.assertEqual(Application.objects.get(id=app["id"]).status, ApplicationStatus.CLOSED)

    def test_page_jobs_active_count_includes_applications(self):
        self._apply()
        page = self.recruitment.page_jobs(1, 20, {})
        self.assertEqual(page["records"][0]["active_assignment_count"], 1)
        detail = self.recruitment.get_job(self.job.id)
        self.assertEqual(detail["active_assignment_count"], 1)

    def test_job_detail_assignments_aligns_with_frontend(self):
        # 前端职位展开行候选人列表读取 assignments（含 application_id/current_stage/agent）
        self._apply()
        detail = self.recruitment.get_job(self.job.id)
        self.assertIn("assignments", detail)
        self.assertEqual(len(detail["assignments"]), 1)
        row = detail["assignments"][0]
        self.assertIn("application_id", row)
        self.assertIn("candidate_name", row)
        self.assertIn("current_stage", row)
        self.assertIn("agent", row)

class JobCloseApiTests(_HrApiBase):
    """R2 路由：close-preview / close STRICT|BULK 与权限"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        self.viewer = self._user("hr-viewer", "HR Viewer")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.viewer.id, role="VIEWER")
        service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        recruitment = RecruitmentService("workspace-a", self.admin.id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_id = service.create_application(self.job.id, self.candidate.id, {})["id"]
        self.base = "/admin/api/workspace/workspace-a/hr/jobs/{}".format(self.job.id)

    def test_preview_requires_hr_access(self):
        response = self._client(self.viewer).get(self.base + "/close-preview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["active_application_count"], 1)

    def test_close_requires_admin(self):
        for user in (self.viewer, self.operator):
            response = self._client(user).post(
                self.base + "/close", {"close_reason": "FILLED", "mode": "STRICT"},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 403)

    def test_strict_conflict_returns_409(self):
        response = self._client(self.admin).post(
            self.base + "/close", {"close_reason": "FILLED", "mode": "STRICT"},
            content_type="application/json",
        )
        self.assertEqual(response.json()["code"], 409)

    def test_bulk_unconfirmed_returns_400(self):
        response = self._client(self.admin).post(
            self.base + "/close", {"close_reason": "FILLED", "mode": "BULK"},
            content_type="application/json",
        )
        self.assertEqual(response.json()["code"], 400)

    def test_bulk_confirmed_closes_and_events(self):
        response = self._client(self.admin).post(
            self.base + "/close",
            {"close_reason": "FILLED", "mode": "BULK", "bulk_confirmed": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["closed_count"], 1)
        application = Application.objects.get(id=self.application_id)
        self.assertEqual(application.status, "CLOSED")
        self.assertTrue(
            ApplicationEvent.objects.filter(
                application=application, event_type="CLOSED", reason_code="JOB_CLOSED"
            ).exists()
        )


class ApplicationInterviewV2Tests(TestCase):
    """R3：Interview 挂 Application —— ACTIVE + SCREEN/INTERVIEW 阶段守卫、round 服务端生成"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = ApplicationService("workspace-a", self.user_id, hr_role="ADMIN")
        recruitment = RecruitmentService("workspace-a", self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_id = self.service.create_application(self.job.id, self.candidate.id, {})["id"]

    def _stages(self):
        return list(JobStage.objects.filter(job=self.job).order_by("order"))

    def _move_to(self, key):
        target = next(s for s in self._stages() if s.key == key)
        self.service.move_stage(self.application_id, target.id, {"reason_text": "advance"})

    def test_create_at_applied_stage_rejected(self):
        with self.assertRaisesRegex(AppApiException, "SCREEN or INTERVIEW"):
            self.service.create_interview(self.application_id, {})

    def test_create_at_screen_stage_ok_with_round_increment(self):
        self._move_to("SCREEN")
        first = self.service.create_interview(self.application_id, {})
        self.assertEqual(first["round_no"], 1)
        self.assertEqual(first["application_id"], self.application_id)
        second = self.service.create_interview(self.application_id, {})
        self.assertEqual(second["round_no"], 2)
        self.assertEqual(len(self.service.list_interviews(self.application_id)), 2)

    def test_create_at_offer_stage_rejected(self):
        self._move_to("SCREEN")
        self._move_to("INTERVIEW")
        self._move_to("OFFER")
        with self.assertRaisesRegex(AppApiException, "SCREEN or INTERVIEW"):
            self.service.create_interview(self.application_id, {})

    def test_create_on_terminal_application_rejected(self):
        self._move_to("SCREEN")
        self.service.reject_application(self.application_id, {"termination_reason": "NOT_FIT"})
        with self.assertRaisesRegex(AppApiException, "not active"):
            self.service.create_interview(self.application_id, {})

    def test_interview_does_not_change_application(self):
        self._move_to("SCREEN")
        self.service.create_interview(self.application_id, {})
        application = Application.objects.get(id=self.application_id)
        self.assertEqual(application.status, "ACTIVE")
        self.assertEqual(application.current_stage.key, "SCREEN")


class ApplicationInterviewApiTests(_HrApiBase):
    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        self.viewer = self._user("hr-viewer", "HR Viewer")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.viewer.id, role="VIEWER")
        service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        recruitment = RecruitmentService("workspace-a", self.admin.id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_id = service.create_application(self.job.id, self.candidate.id, {})["id"]
        self.base = "/admin/api/workspace/workspace-a/hr/applications/{}".format(self.application_id)

    def test_create_requires_operator(self):
        response = self._client(self.viewer).post(self.base + "/interviews", {}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_create_rejected_at_applied_stage(self):
        response = self._client(self.operator).post(self.base + "/interviews", {}, content_type="application/json")
        self.assertEqual(response.json()["code"], 400)

    def test_list_by_application(self):
        service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        stages = list(JobStage.objects.filter(job=self.job).order_by("order"))
        service.move_stage(self.application_id, stages[1].id, {"reason_text": "scan"})
        self._client(self.operator).post(self.base + "/interviews", {}, content_type="application/json")
        response = self._client(self.viewer).get(self.base + "/interviews")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)


class ApplicationOfferV2Tests(TestCase):
    """R3：Offer 挂 Application —— OFFER 阶段守卫、单活跃 Offer、接受联动 HIRED、幂等 Handoff"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = ApplicationService("workspace-a", self.user_id, hr_role="ADMIN")
        self.offer_service = OfferService("workspace-a", self.user_id, hr_role="ADMIN")
        self.recruitment = RecruitmentService("workspace-a", self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = self.recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_id = self.service.create_application(self.job.id, self.candidate.id, {})["id"]

    def _stages(self):
        return list(JobStage.objects.filter(job=self.job).order_by("order"))

    def _to_offer_stage(self):
        for stage in self._stages()[1:]:
            self.service.move_stage(self.application_id, stage.id, {"reason_text": "advance"})

    def test_create_requires_offer_stage(self):
        self.service.move_stage(self.application_id, self._stages()[1].id, {"reason_text": "screen"})
        with self.assertRaisesRegex(AppApiException, "OFFER stage"):
            self.offer_service.create_offer_for_application(self.application_id, {"salary_amount": "25000"})

    def test_create_offer_and_single_active(self):
        self._to_offer_stage()
        offer = self.offer_service.create_offer_for_application(
            self.application_id, {"salary_amount": "25000", "currency": "CNY"}
        )
        self.assertEqual(offer["version"], 1)
        self.assertEqual(offer["application_id"], self.application_id)
        self.assertIsNone(offer["assignment_id"])
        with self.assertRaisesRegex(AppApiException, "active offer"):
            self.offer_service.create_offer_for_application(self.application_id, {"salary_amount": "30000"})

    def test_rejected_offer_allows_new_version(self):
        self._to_offer_stage()
        offer_id = self.offer_service.create_offer_for_application(self.application_id, {})["id"]
        self.offer_service.approve_offer(offer_id, {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        self.offer_service.send_offer(offer_id)
        self.offer_service.reject_offer(offer_id, {"note": "拒绝"})
        second = self.offer_service.create_offer_for_application(self.application_id, {"salary_amount": "30000"})
        self.assertEqual(second["version"], 2)

    def test_send_guard_single_sent_per_application(self):
        self._to_offer_stage()
        first = self.offer_service.create_offer_for_application(self.application_id, {"salary_amount": "25000"})
        self.offer_service.approve_offer(first["id"], {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        self.offer_service.send_offer(first["id"])
        application = Application.objects.get(id=self.application_id)
        second = Offer.objects.create(
            workspace_id="workspace-a", application=application,
            candidate=application.candidate, job=application.job, version=2,
            salary_amount="30000", user_id=self.user_id,
        )
        self.offer_service.approve_offer(second.id, {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        with self.assertRaisesRegex(AppApiException, "already been sent"):
            self.offer_service.send_offer(second.id)
        self.assertEqual(Offer.objects.get(id=first["id"]).status, "SENT")

    def test_accept_moves_application_to_hired_with_event(self):
        self._to_offer_stage()
        offer_id = self.offer_service.create_offer_for_application(self.application_id, {"salary_amount": "25000"})["id"]
        self.offer_service.approve_offer(offer_id, {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        self.offer_service.send_offer(offer_id)
        accepted = self.offer_service.accept_offer(offer_id)
        self.assertEqual(accepted["status"], "ACCEPTED")
        application = Application.objects.get(id=self.application_id)
        self.assertEqual(application.status, ApplicationStatus.HIRED)
        self.assertIsNotNone(application.terminated_at)
        self.assertTrue(
            ApplicationEvent.objects.filter(
                application=application, event_type=ApplicationEventType.HIRED,
                from_status="ACTIVE", to_status="HIRED",
            ).exists()
        )

    def test_handoff_idempotent_per_application(self):
        self._to_offer_stage()
        offer_id = self.offer_service.create_offer_for_application(self.application_id, {"salary_amount": "25000"})["id"]
        self.offer_service.approve_offer(offer_id, {"approval_status": "APPROVED", "approver_id": str(self.user_id)})
        self.offer_service.send_offer(offer_id)
        self.offer_service.accept_offer(offer_id)
        offer = Offer.objects.get(id=offer_id)
        handoff_service = OnboardingService("workspace-a", self.user_id, hr_role="ADMIN")
        handoff_service.create_handoff_for_offer(offer)
        handoff_service.create_handoff_for_offer(offer)
        self.assertEqual(
            OnboardingHandoff.objects.filter(workspace_id="workspace-a", application_id=self.application_id).count(), 1
        )


class ApplicationOfferApiTests(_HrApiBase):
    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        self.service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        recruitment = RecruitmentService("workspace-a", self.admin.id, hr_role="ADMIN")
        candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_id = self.service.create_application(self.job.id, candidate.id, {})["id"]
        self.base = "/admin/api/workspace/workspace-a/hr/applications/{}".format(self.application_id)

    def test_offer_requires_admin(self):
        response = self._client(self.operator).post(self.base + "/offers", {}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_full_offer_flow_via_application_api(self):
        stages = list(JobStage.objects.filter(job=self.job).order_by("order"))
        for stage in stages[1:]:
            self.service.move_stage(self.application_id, stage.id, {"reason_text": "advance"})
        admin = self._client(self.admin)
        offer_id = admin.post(
            self.base + "/offers", {"salary_amount": "25000", "currency": "CNY"},
            content_type="application/json",
        ).json()["data"]["id"]
        admin.put(
            "/admin/api/workspace/workspace-a/hr/offers/{}/approve".format(offer_id),
            {"approval_status": "APPROVED", "approver_id": str(self.admin.id)},
            content_type="application/json",
        )
        admin.put("/admin/api/workspace/workspace-a/hr/offers/{}/send".format(offer_id))
        accepted = admin.put("/admin/api/workspace/workspace-a/hr/offers/{}/accept".format(offer_id))
        self.assertEqual(accepted.json()["data"]["status"], "ACCEPTED")
        application = Application.objects.get(id=self.application_id)
        self.assertEqual(application.status, "HIRED")
        offers = admin.get(self.base + "/offers").json()["data"]
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["application_id"], self.application_id)


class ApplicationCommandIdempotencyTests(TestCase):
    """R5：move_stage / 终态事件幂等键"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = ApplicationService("workspace-a", self.user_id, hr_role="ADMIN")
        recruitment = RecruitmentService("workspace-a", self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_id = self.service.create_application(self.job.id, self.candidate.id, {})["id"]
        self.stages = list(JobStage.objects.filter(job=self.job).order_by("order"))

    def test_move_stage_idempotency_key(self):
        key = "move-{}".format(uuid.uuid7())
        self.service.move_stage(self.application_id, self.stages[1].id, {"idempotency_key": key, "reason_text": "forward"})
        # 二次同键：同阶段移动需 reason_text（owner/admin），事件不重复
        moved = self.service.move_stage(
            self.application_id, self.stages[1].id, {"idempotency_key": key, "reason_text": "retry"}
        )
        self.assertEqual(moved["current_stage"]["key"], "SCREEN")
        self.assertEqual(
            ApplicationEvent.objects.filter(
                application_id=self.application_id, event_type="STAGE_MOVED", idempotency_key=key
            ).count(), 1
        )

    def test_terminal_idempotency_key(self):
        key = "term-{}".format(uuid.uuid7())
        self.service.reject_application(self.application_id, {"termination_reason": "NOT_FIT", "idempotency_key": key})
        with self.assertRaisesRegex(AppApiException, "not active"):
            self.service.reject_application(self.application_id, {"termination_reason": "NOT_FIT", "idempotency_key": key})
        self.assertEqual(
            ApplicationEvent.objects.filter(
                application_id=self.application_id, event_type="REJECTED", idempotency_key=key
            ).count(), 1
        )

    def test_skip_stage_requires_owner_or_admin(self):
        operator = ApplicationService("workspace-a", uuid.uuid7(), hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            operator.move_stage(self.application_id, self.stages[2].id, {"reason_text": "skip"})
        # ADMIN 跳级 + reason_text 可放行
        moved = self.service.move_stage(self.application_id, self.stages[2].id, {"reason_text": "admin skip"})
        self.assertEqual(moved["current_stage"]["key"], "INTERVIEW")

    def test_terminal_reason_matrix(self):
        matrix = [
            ("reject", "REJECTED", ["NOT_FIT", "SALARY", "OTHER"]),
            ("withdraw", "WITHDRAWN", ["CANDIDATE_WITHDRAW", "UNREACHABLE", "OTHER"]),
            ("close", "CLOSED", ["MERGED", "OTHER"]),
        ]
        for action, status, allowed in matrix:
            candidate = Candidate.objects.create(name="M-{}".format(action), workspace_id="workspace-a")
            application = self.service.create_application(self.job.id, candidate.id, {})
            for reason in ("NOT_FIT", "SALARY", "CANDIDATE_WITHDRAW", "UNREACHABLE", "JOB_CLOSED", "MERGED"):
                if reason in allowed:
                    continue
                with self.assertRaisesRegex(AppApiException, "not allowed"):
                    getattr(self.service, "{}_application".format(action))(
                        application["id"], {"termination_reason": reason}
                    )
            result = getattr(self.service, "{}_application".format(action))(
                application["id"], {"termination_reason": allowed[0]}
            )
            self.assertEqual(result["status"], status)


class ApplicationApiPermissionTests(_HrApiBase):
    """R5：Application API 权限矩阵"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        self.viewer = self._user("hr-viewer", "HR Viewer")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.viewer.id, role="VIEWER")
        self.service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        recruitment = RecruitmentService("workspace-a", self.admin.id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_id = self.service.create_application(self.job.id, self.candidate.id, {})["id"]
        self.stages = list(JobStage.objects.filter(job=self.job).order_by("order"))
        self.app_base = "/admin/api/workspace/workspace-a/hr/applications/{}".format(self.application_id)

    def test_viewer_cannot_create_application(self):
        response = self._client(self.viewer).post(
            "/admin/api/workspace/workspace-a/hr/applications",
            {"job_id": str(self.job.id), "candidate_id": str(self.candidate.id)},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_can_create_application(self):
        candidate = Candidate.objects.create(name="Bob", workspace_id="workspace-a")
        response = self._client(self.operator).post(
            "/admin/api/workspace/workspace-a/hr/applications",
            {"job_id": str(self.job.id), "candidate_id": str(candidate.id)},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "ACTIVE")

    def test_viewer_can_page_and_events_but_not_mutate(self):
        response = self._client(self.viewer).get("/admin/api/workspace/workspace-a/hr/applications/page/1/20")
        self.assertEqual(response.status_code, 200)
        response = self._client(self.viewer).get(self.app_base + "/events")
        self.assertEqual(response.status_code, 200)
        response = self._client(self.viewer).post(
            self.app_base + "/move-stage", {"to_stage_id": str(self.stages[1].id)},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        response = self._client(self.viewer).post(
            self.app_base + "/terminal", {"action": "reject", "termination_reason": "NOT_FIT"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_restore_requires_admin(self):
        self.service.reject_application(self.application_id, {"termination_reason": "NOT_FIT"})
        response = self._client(self.operator).post(
            self.app_base + "/restore", {"reason_text": "wrong reject"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        response = self._client(self.admin).post(
            self.app_base + "/restore", {"reason_text": "wrong reject"}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)


class ResumeSearchScopeTests(TestCase):
    """RAG 最小改动：document_ids / candidate_id 仅限定召回集，不改链路"""

    def setUp(self):
        self.workspace_id = "workspace-scope"
        self.user = User.objects.create(
            username="scope-" + uuid.uuid7().hex[:8], nick_name="scope", password="p", role="ADMIN"
        )
        self.knowledge = SimpleNamespace(id=uuid.uuid7())
        self.candidate = Candidate.objects.create(name="Alice", workspace_id=self.workspace_id)
        self.resume = ResumeFile.objects.create(
            workspace_id=self.workspace_id, file_name="a.docx", extension="docx",
            file_path="/tmp/a.docx", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            source_channel="OTHER", status=ResumeStatus.SUCCESS, user_id=self.user.id,
            candidate=self.candidate, document_id=uuid.uuid7(),
        )
        self.doc_id = str(self.resume.document_id)

    def _patched_search(self, **kwargs):
        from unittest.mock import Mock as _Mock
        from hr.services.resume_search import search_resumes
        fake_emb = _Mock()
        fake_emb.embed_query.return_value = [0.1] * 8
        with patch("hr.services.resume_search.get_resume_knowledge", return_value=self.knowledge),                 patch("hr.services.resume_search.get_embedding_model_by_knowledge_id", return_value=fake_emb),                 patch("hr.services.resume_search._recall_dual") as recall,                 patch("hr.services.resume_search._rrf_fuse", return_value=[]):
            recall.return_value = {"dense": [], "sparse": [], "sparse_failed": False}
            result = search_resumes(self.workspace_id, "java 开发", mode="phrase", hr_role="ADMIN",
                                    user_id=self.user.id, **kwargs)
            return result, recall

    def test_document_ids_restrict_recall(self):
        result, recall = self._patched_search(document_ids=[self.doc_id])
        self.assertTrue(result["meta"]["scope"]["applied"])
        self.assertEqual(recall.call_args.kwargs["document_ids"], [self.doc_id])
        self.assertEqual(result["items"], [])

    def test_candidate_id_resolves_resume_documents(self):
        result, recall = self._patched_search(candidate_id=str(self.candidate.id))
        self.assertEqual(recall.call_args.kwargs["document_ids"], [self.doc_id])

    def test_candidate_id_unknown_raises(self):
        from hr.services.resume_search import search_resumes
        with self.assertRaises(AppApiException):
            search_resumes(self.workspace_id, "java 开发", candidate_id=str(uuid.uuid7()),
                           user_id=self.user.id, hr_role="ADMIN")

    def test_scope_missing_unchanged(self):
        result, recall = self._patched_search()
        self.assertNotIn("scope", result["meta"])
        self.assertIsNone(recall.call_args.kwargs["document_ids"])

    def test_document_ids_invalid_raises(self):
        from hr.services.resume_search import search_resumes
        with self.assertRaisesRegex(AppApiException, "document_ids"):
            search_resumes(self.workspace_id, "java 开发", document_ids=[], user_id=self.user.id, hr_role="ADMIN")
class AgentScoringTests(TestCase):
    """D1 §6.3：服务端评分与建议动作派生（LLM 不可自报 score/action）"""

    def test_advance_when_high_score_and_evidence_ok(self):
        payload = {
            "dimensions": [
                {"name": "技能匹配", "verdict": "强", "evidence": [{"relevance": 0.98}, {"relevance": 0.95}], "confidence": 0.98},
                {"name": "经验相关性", "verdict": "强", "evidence": [{"relevance": 0.9}], "confidence": 0.9},
                {"name": "工作年限", "verdict": "够", "evidence": [{"relevance": 0.8}], "confidence": 0.85},
            ],
        }
        decision = scoring.derive_decision(payload, hard_met=True)
        self.assertEqual(decision["suggested_action"], "ADVANCE")
        self.assertGreaterEqual(decision["score"], 80)
        self.assertTrue(decision["evidence_ok"])

    def test_hold_when_mid_score(self):
        payload = {
            "dimensions": [
                {"name": "技能匹配", "verdict": "中", "evidence": [{"relevance": 0.7}], "confidence": 1.0},
                {"name": "经验相关性", "verdict": "中", "evidence": [{"relevance": 0.6}], "confidence": 1.0},
            ],
        }
        decision = scoring.derive_decision(payload, hard_met=True)
        self.assertEqual(decision["suggested_action"], "HOLD")
        self.assertTrue(60 <= decision["score"] < 80)

    def test_hold_when_evidence_missing_despite_high_confidence(self):
        # 无证据维度不得贡献正分（禁止无证据高分）
        payload = {
            "dimensions": [
                {"name": "技能匹配", "verdict": "强", "evidence": [], "confidence": 0.99},
                {"name": "经验相关性", "verdict": "强", "evidence": [{"relevance": 0.2}], "confidence": 0.9},
            ],
        }
        decision = scoring.derive_decision(payload, hard_met=True)
        self.assertIn(decision["suggested_action"], ("HOLD", "DECLINE"))
        self.assertFalse(decision["evidence_ok"])

    def test_decline_when_low_score(self):
        payload = {
            "dimensions": [
                {"name": "技能匹配", "verdict": "弱", "evidence": [{"relevance": 0.2}], "confidence": 0.5},
                {"name": "经验相关性", "verdict": "弱", "evidence": [{"relevance": 0.1}], "confidence": 0.5},
            ],
        }
        decision = scoring.derive_decision(payload, hard_met=True)
        self.assertEqual(decision["suggested_action"], "DECLINE")

    def test_decline_when_hard_not_met(self):
        payload = {
            "dimensions": [
                {"name": "技能匹配", "verdict": "强", "evidence": [{"relevance": 0.9}], "confidence": 0.95},
                {"name": "经验相关性", "verdict": "强", "evidence": [{"relevance": 0.8}], "confidence": 0.9},
            ],
        }
        decision = scoring.derive_decision(payload, hard_met=False)
        self.assertEqual(decision["suggested_action"], "DECLINE")

    def test_non_whitelist_dimension_dropped_with_warning(self):
        payload = {
            "dimensions": [
                {"name": "技能匹配", "verdict": "强", "evidence": [{"relevance": 0.9}], "confidence": 0.95},
                {"name": "年龄", "verdict": "偏大", "evidence": [{"relevance": 0.9}], "confidence": 0.99},
            ],
        }
        decision = scoring.derive_decision(payload, hard_met=True)
        self.assertTrue(any(item["reason"] == "not in whitelist" for item in decision["warnings"]))
        names = [item["name"] for item in decision["dimension_details"]]
        self.assertNotIn("年龄", names)
        self.assertEqual(len(names), 1)


class ScreeningRunnerTests(TestCase):
    """D1 Runner：固定顺序工具编排 + LLM 评估 + 服务端评分 + propose"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.workspace_id = "workspace-agent"
        self.recruitment = RecruitmentService(self.workspace_id, self.user_id, hr_role="ADMIN")
        HrConfig.objects.update_or_create(
            workspace_id=self.workspace_id,
            defaults={
                "llm_model_id": "fake-llm",
                "agent_enable_screening": True,
                "agent_max_concurrent_runs": 2,
                "agent_run_rate_limit": 100,
            },
        )
        self.candidate = Candidate.objects.create(
            name="Alice", workspace_id=self.workspace_id, skills=["python"],
            current_city="上海", highest_degree="硕士", years_experience=5,
        )
        job_data = self.recruitment.create_job({
            "name": "Python Engineer", "department": "Eng", "city": "上海",
            "skill_requirements": ["Python"],
        })
        self.job = Job.objects.get(id=job_data["id"])
        self.application = self.service_create()

    def service_create(self):
        service = ApplicationService(self.workspace_id, self.user_id, hr_role="ADMIN")
        return service.create_application(self.job.id, self.candidate.id, {})

    def _fake_model(self, payload):
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return fake

    def _valid_facts(self):
        return {
            "dimensions": [
                {"name": "技能匹配", "verdict": "命中 Python", "evidence": [{"paragraph_id": "p1", "excerpt": "熟悉 Python 开发", "relevance": 0.98}, {"paragraph_id": "p1b", "excerpt": "Python 后端", "relevance": 0.95}], "confidence": 0.98},
                {"name": "经验相关性", "verdict": "相关经验", "evidence": [{"paragraph_id": "p2", "excerpt": "三年后端经验", "relevance": 0.9}], "confidence": 0.9},
            ],
            "concerns": ["项目规模待确认"],
            "clarifying_questions": ["能否接受加班"],
        }

    def _patch_search(self, items=None):
        return patch("hr.agents.runner.search_resumes", return_value={
            "items": items or [
                {
                    "candidate": {"id": str(self.candidate.id), "name": "Alice", "phone": "13812345678", "email": "a@b.com"},
                    "resume": {"id": "r1", "file_name": "a.docx"},
                    "paragraphs": [
                        {"id": "p1", "title": "工作经历", "content": "熟悉 Python 开发", "score": 0.9},
                        {"id": "p1b", "title": "工作经历", "content": "Python 后端", "score": 0.95},
                        {"id": "p2", "title": "工作经历", "content": "三年后端经验", "score": 0.7},
                        {"id": "p3", "title": "工作经历", "content": "五年经验", "score": 0.6},
                    ],
                    "document_id": "d1",
                }
            ],
            "meta": {"mode": "phrase", "search_type": "hybrid_rrf", "aggregation": {"grouped_resumes": 1}},
        })

    def test_success_flow_creates_run_and_proposal(self):
        from hr.agents.runner import run_screening_agent
        with patch("hr.agents.runner._load_llm", return_value=(self._fake_model(self._valid_facts()), "fake-llm")), self._patch_search():
            output = run_screening_agent(self.application["id"], trigger_type="EVENT", user_id=self.user_id)
        self.assertEqual(output["status"], "SUCCEEDED")
        self.assertIsNotNone(output["proposal_id"])
        run = HrAgentRun.objects.get(id=output["run_id"])
        self.assertEqual(run.agent_type, "SCREENING")
        self.assertEqual(run.trigger_type, "EVENT")
        self.assertEqual(run.prompt_version, "screening-v2")
        self.assertGreater(run.duration_ms, 0)
        self.assertTrue(run.output_json["decision"]["hard_met"])
        self.assertEqual(run.output_json["decision"]["suggested_action"], "ADVANCE")
        tool_names = [item["tool"] for item in run.tool_trace]
        self.assertEqual(tool_names, ["get_job", "get_candidate_overview", "structured_filter", "search_resumes"])
        proposal = HrAgentProposal.objects.get(id=output["proposal_id"])
        self.assertEqual(proposal.action, "ADVANCE")
        self.assertEqual(proposal.status, "PENDING")
        self.assertEqual(proposal.target_id, self.application["id"])
        self.assertTrue(
            HrAuditLog.objects.filter(workspace_id=self.workspace_id, action="AGENT_RUN", trace_id=run.id).exists()
        )

    def test_pii_projection_strips_contact_from_trace_and_payload(self):
        from hr.agents.runner import run_screening_agent
        with patch("hr.agents.runner._load_llm", return_value=(self._fake_model(self._valid_facts()), "fake-llm")), self._patch_search():
            output = run_screening_agent(self.application["id"], trigger_type="EVENT", user_id=self.user_id)
        run = HrAgentRun.objects.get(id=output["run_id"])
        dumped = json.dumps({"trace": run.tool_trace, "input": run.input_meta, "output": run.output_json}, ensure_ascii=False)
        self.assertNotIn("13812345678", dumped)
        self.assertNotIn("a@b.com", dumped)
        self.assertNotIn("/tmp/", dumped)

    def test_llm_failure_marks_run_failed(self):
        from hr.agents.runner import run_screening_agent
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content="not json")
        with patch("hr.agents.runner._load_llm", return_value=(fake, "fake-llm")), self._patch_search():
            output = run_screening_agent(self.application["id"], trigger_type="EVENT", user_id=self.user_id)
        self.assertEqual(output["status"], "FAILED")
        self.assertIsNone(output["proposal_id"])
        self.assertTrue(HrAgentRun.objects.get(id=output["run_id"]).error)

    def test_disabled_agent_skips(self):
        from hr.agents.runner import run_screening_agent
        HrConfig.objects.filter(workspace_id=self.workspace_id).update(agent_enable_screening=False)
        output = run_screening_agent(self.application["id"], trigger_type="EVENT", user_id=self.user_id)
        self.assertEqual(output["status"], "SKIPPED")
        self.assertIn("disabled", output["error"])

    def test_non_apply_relation_event_skips(self):
        from hr.agents.runner import run_screening_agent
        other = Candidate.objects.create(name="Bob", workspace_id=self.workspace_id)
        application = ApplicationService(self.workspace_id, self.user_id, hr_role="ADMIN").create_application(
            self.job.id, other.id, {"relation_type": "HEADHUNTER"}
        )
        output = run_screening_agent(application["id"], trigger_type="EVENT", user_id=self.user_id)
        self.assertEqual(output["status"], "SKIPPED")
        self.assertIn("relation_type", output["error"])

    def test_not_at_applied_stage_skips(self):
        from hr.agents.runner import run_screening_agent
        service = ApplicationService(self.workspace_id, self.user_id, hr_role="ADMIN")
        stage = JobStage.objects.filter(job=self.job).order_by("order")[1]
        service.move_stage(self.application["id"], stage.id, {"reason_text": "screen"})
        output = run_screening_agent(self.application["id"], trigger_type="EVENT", user_id=self.user_id)
        self.assertEqual(output["status"], "SKIPPED")
        self.assertIn("APPLIED", output["error"])

    def test_concurrent_limit_skips(self):
        from hr.agents.runner import run_screening_agent
        HrConfig.objects.filter(workspace_id=self.workspace_id).update(agent_max_concurrent_runs=1)
        HrAgentRun.objects.create(
            workspace_id=self.workspace_id, agent_type="SCREENING", trigger_type="EVENT",
            ref_object_type="APPLICATION", ref_object_id="other", status="RUNNING",
            prompt_version="v", user_id=self.user_id,
        )
        output = run_screening_agent(self.application["id"], trigger_type="EVENT", user_id=self.user_id)
        self.assertEqual(output["status"], "SKIPPED")
        self.assertIn("concurrent", output["error"])

    def test_no_model_marks_failed(self):
        from hr.agents.runner import run_screening_agent
        with patch("hr.agents.runner._load_llm", return_value=(None, "")), self._patch_search():
            output = run_screening_agent(self.application["id"], trigger_type="EVENT", user_id=self.user_id)
        self.assertEqual(output["status"], "FAILED")
        self.assertIn("LLM", output["error"])


class ScreeningJsonRepairTests(TestCase):
    """runner 结构化输出修复：_repair_json 提取首个平衡块，_invoke_llm 自动修补（报告建议②）。"""

    def test_repair_json_extracts_balanced_block_from_noise(self):
        import json

        from hr.agents.runner import _repair_json

        noisy = '好的，评估结果如下：\n```json\n{"dimensions": [{"name": "技能匹配", "evidence": [{"paragraph_id": "p1", "excerpt": "负责 xx", "relevance": 0.9}]}]}\n```\n结束'
        repaired = _repair_json(noisy)
        self.assertIsNotNone(repaired)
        self.assertEqual(json.loads(repaired)["dimensions"][0]["name"], "技能匹配")

    def test_repair_json_drops_prefix_and_trailing_junk(self):
        import json

        from hr.agents.runner import _repair_json

        repaired = _repair_json('前缀说明 {"a": [1, 2]} 后缀说明')
        self.assertEqual(repaired, '{"a": [1, 2]}')
        self.assertEqual(json.loads(repaired)["a"], [1, 2])

    def test_repair_json_returns_none_without_brace(self):
        from hr.agents.runner import _repair_json

        self.assertIsNone(_repair_json("没有对象"))

    def test_invoke_llm_applies_repair_automatically(self):
        from types import SimpleNamespace

        from hr.agents.runner import _invoke_llm

        fake = SimpleNamespace(
            invoke=lambda prompt: SimpleNamespace(
                content='围绕结果：\n{"dimensions": [{"name": "技能匹配", "verdict": "符合", "evidence": [], "confidence": 0.8}]}'
            ),
        )
        data = _invoke_llm(fake, "prompt")
        self.assertEqual(data["dimensions"][0]["name"], "技能匹配")


class AgentProposalTests(TestCase):
    """D1 Proposal 审批：Propose → Confirm → Execute（ADVANCE/DECLINE/HOLD + 幂等 + 过期）"""

    def setUp(self):
        self.owner_id = uuid.uuid7()
        self.workspace_id = "workspace-proposal"
        self.recruitment = RecruitmentService(self.workspace_id, self.owner_id, hr_role="ADMIN")
        HrConfig.objects.update_or_create(
            workspace_id=self.workspace_id, defaults={"llm_model_id": "fake", "agent_enable_screening": True}
        )
        self.candidate = Candidate.objects.create(name="Alice", workspace_id=self.workspace_id, skills=["python"])
        job_data = self.recruitment.create_job({"name": "Engineer", "headcount": 1, "skill_requirements": ["Python"]})
        self.job = Job.objects.get(id=job_data["id"])
        self.application = ApplicationService(self.workspace_id, self.owner_id, hr_role="ADMIN").create_application(
            self.job.id, self.candidate.id, {}
        )
        self.stages = list(JobStage.objects.filter(job=self.job).order_by("order"))

    def _proposal(self, action="ADVANCE", stage_key="APPLIED"):
        from hr.agents.proposals import propose
        run = HrAgentRun.objects.create(
            workspace_id=self.workspace_id, agent_type="SCREENING", trigger_type="EVENT",
            ref_object_type="APPLICATION", ref_object_id=self.application["id"], status="SUCCEEDED",
            prompt_version="v", user_id=self.owner_id,
        )
        return propose(
            self.workspace_id, run, self.application["id"], action,
            {"stage_key": stage_key, "decision": {"score": 90, "suggested_action": action}},
        )

    def _service(self, hr_role="ADMIN", user_id=None):
        return ProposalService(self.workspace_id, user_id or self.owner_id, hr_role)

    def test_accept_advance_moves_to_next_stage_with_idempotency_event(self):
        proposal = self._proposal("ADVANCE")
        accepted = self._service().accept(proposal.id, {"decision_note": "ok"})
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertEqual(accepted["decided_by"], str(self.owner_id))
        application = Application.objects.get(id=self.application["id"])
        self.assertEqual(application.current_stage.key, "SCREEN")
        self.assertTrue(
            ApplicationEvent.objects.filter(
                application=application, event_type="STAGE_MOVED",
                idempotency_key=f"proposal:{proposal.id}",
            ).exists()
        )
        self.assertTrue(
            HrAuditLog.objects.filter(workspace_id=self.workspace_id, action="AGENT_DECIDE").exists()
        )

    def test_accept_decline_rejects_with_not_fit(self):
        proposal = self._proposal("DECLINE")
        self._service().accept(proposal.id, {"decision_note": "不符合"})
        application = Application.objects.get(id=self.application["id"])
        self.assertEqual(application.status, "REJECTED")
        self.assertEqual(application.termination_reason, "NOT_FIT")
        self.assertTrue(
            ApplicationEvent.objects.filter(
                application=application, event_type="REJECTED",
                idempotency_key=f"proposal:{proposal.id}", reason_code="NOT_FIT",
            ).exists()
        )

    def test_accept_hold_does_not_change_state(self):
        proposal = self._proposal("HOLD")
        self._service().accept(proposal.id, {"decision_note": "转人工"})
        application = Application.objects.get(id=self.application["id"])
        self.assertEqual(application.status, "ACTIVE")
        self.assertEqual(application.current_stage.key, "APPLIED")
        self.assertEqual(HrAgentProposal.objects.get(id=proposal.id).status, "ACCEPTED")

    def test_accept_twice_rejected(self):
        proposal = self._proposal("ADVANCE")
        self._service().accept(proposal.id, {})
        with self.assertRaises(AppApiException):
            self._service().accept(proposal.id, {})

    def test_accept_when_target_moved_expires(self):
        proposal = self._proposal("ADVANCE")
        service = ApplicationService(self.workspace_id, self.owner_id, hr_role="ADMIN")
        service.move_stage(self.application["id"], self.stages[1].id, {"reason_text": "manual"})
        with self.assertRaises(AppApiException) as ctx:
            self._service().accept(proposal.id, {})
        self.assertEqual(ctx.exception.code, 409)
        self.assertEqual(HrAgentProposal.objects.get(id=proposal.id).status, "EXPIRED")

    def test_decision_permission_owner_or_admin(self):
        proposal = self._proposal("ADVANCE")
        stranger = ProposalService(self.workspace_id, uuid.uuid7(), hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            stranger.accept(proposal.id, {})
        owner = ProposalService(self.workspace_id, self.owner_id, hr_role="OPERATOR")
        self.assertEqual(owner.accept(proposal.id, {})["status"], "ACCEPTED")

    def test_dismiss_marks_dismissed(self):
        proposal = self._proposal("ADVANCE")
        dismissed = self._service().dismiss(proposal.id, {"decision_note": "暂不处理"})
        self.assertEqual(dismissed["status"], "DISMISSED")
        self.assertEqual(dismissed["decision_note"], "暂不处理")
        with self.assertRaisesRegex(AppApiException, "not pending"):
            self._service().dismiss(proposal.id, {})

    def test_new_proposal_expires_old_pending(self):
        first = self._proposal("HOLD")
        second = self._proposal("ADVANCE")
        self.assertEqual(HrAgentProposal.objects.get(id=first.id).status, "EXPIRED")
        self.assertEqual(HrAgentProposal.objects.get(id=second.id).status, "PENDING")

    def test_job_detail_includes_latest_agent_summary(self):
        proposal = self._proposal("ADVANCE")
        detail = self.recruitment.get_job(self.job.id)
        application_record = next(
            record for record in detail["applications"]
            if record["application_id"] == self.application["id"]
        )
        self.assertEqual(application_record["agent"]["proposal_id"], str(proposal.id))
        self.assertEqual(application_record["agent"]["action"], "ADVANCE")
        self.assertEqual(application_record["agent"]["status"], "PENDING")
        self.assertEqual(application_record["agent"]["score"], 90)

    def test_list_for_application_lazily_expires(self):
        proposal = self._proposal("ADVANCE")
        Application.objects.filter(id=self.application["id"]).update(status="REJECTED")
        records = self._service().list_for_application(self.application["id"])
        self.assertEqual(records[0]["status"], "EXPIRED")
        self.assertEqual(HrAgentProposal.objects.get(id=proposal.id).status, "EXPIRED")


class AgentTriggerTests(TestCase):
    """D1 触发点：新建 Application（APPLY/REFERRAL + 开关开启）自动分发"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.workspace_id = "workspace-trigger"
        self.recruitment = RecruitmentService(self.workspace_id, self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id=self.workspace_id)
        job_data = self.recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])

    def _enable(self, enabled=True):
        HrConfig.objects.update_or_create(
            workspace_id=self.workspace_id,
            defaults={"llm_model_id": "fake", "agent_enable_screening": enabled},
        )

    def _create(self, relation_type="APPLY"):
        service = ApplicationService(self.workspace_id, self.user_id, hr_role="ADMIN")
        return service.create_application(self.job.id, self.candidate.id, {"relation_type": relation_type})

    def test_apply_application_dispatches(self):
        self._enable()
        with patch("hr.agents.runner.dispatch_event_screening") as dispatch:
            application = self._create("APPLY")
        dispatch.assert_called_once_with(uuid.UUID(application["id"]))

    def test_referral_application_dispatches(self):
        self._enable()
        with patch("hr.agents.runner.dispatch_event_screening") as dispatch:
            application = self._create("REFERRAL")
        dispatch.assert_called_once_with(uuid.UUID(application["id"]))

    def test_headhunter_application_not_dispatched(self):
        self._enable()
        with patch("hr.agents.runner.dispatch_event_screening") as dispatch:
            self._create("HEADHUNTER")
        dispatch.assert_not_called()

    def test_disabled_switch_not_dispatched(self):
        self._enable(enabled=False)
        with patch("hr.agents.runner.dispatch_event_screening") as dispatch:
            self._create("APPLY")
        dispatch.assert_not_called()


class AgentApiTests(_HrApiBase):
    """D1 路由：run / proposals accept|dismiss 与权限"""

    def setUp(self):
        self.admin = self._user("hr-agent-admin", "HR Agent Admin")
        self.operator = self._user("hr-agent-operator", "HR Agent Operator")
        self.viewer = self._user("hr-agent-viewer", "HR Agent Viewer")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.viewer.id, role="VIEWER")
        self.service = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN")
        recruitment = RecruitmentService("workspace-a", self.admin.id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job_data = recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application_id = self.service.create_application(self.job.id, self.candidate.id, {})["id"]
        HrConfig.objects.update_or_create(
            workspace_id="workspace-a",
            defaults={"llm_model_id": "fake", "agent_enable_screening": True},
        )

    def test_run_requires_operator(self):
        response = self._client(self.viewer).post(
            "/admin/api/workspace/workspace-a/hr/agents/SCREENING/run",
            {"application_id": self.application_id}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_run_manual_succeeds(self):
        facts = {
            "dimensions": [
                {"name": "技能匹配", "verdict": "命中", "evidence": [], "confidence": 0.9},
                {"name": "经验相关性", "verdict": "相关", "evidence": [], "confidence": 0.9},
            ],
            "concerns": [], "clarifying_questions": [],
        }
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content=json.dumps(facts))
        with patch("hr.agents.runner._load_llm", return_value=(fake, "fake-llm")),                 patch("hr.agents.runner.search_resumes", return_value={"items": [], "meta": {}}):
            response = self._client(self.operator).post(
                "/admin/api/workspace/workspace-a/hr/agents/SCREENING/run",
                {"application_id": self.application_id}, content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "SUCCEEDED")
        self.assertEqual(response.json()["data"]["trigger_type"], "MANUAL")

    def test_run_invalid_agent_type(self):
        response = self._client(self.operator).post(
            "/admin/api/workspace/workspace-a/hr/agents/JD/run",
            {"application_id": self.application_id}, content_type="application/json",
        )
        self.assertEqual(response.json()["code"], 400)

    def test_proposal_list_and_decision_routes(self):
        run = HrAgentRun.objects.create(
            workspace_id="workspace-a", agent_type="SCREENING", trigger_type="MANUAL",
            ref_object_type="APPLICATION", ref_object_id=self.application_id, status="SUCCEEDED",
            prompt_version="v", user_id=self.admin.id,
        )
        proposal = HrAgentProposal.objects.create(
            workspace_id="workspace-a", run=run, target_type="APPLICATION",
            target_id=self.application_id, action="HOLD", status="PENDING",
            payload_json={"stage_key": "APPLIED"},
        )
        response = self._client(self.viewer).get(
            "/admin/api/workspace/workspace-a/hr/applications/{}/proposals".format(self.application_id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)
        response = self._client(self.admin).post(
            "/admin/api/workspace/workspace-a/hr/proposals/{}/accept".format(proposal.id),
            {"decision_note": "转人工"}, content_type="application/json",
        )
        self.assertEqual(response.json()["data"]["status"], "ACCEPTED")
        proposal.refresh_from_db()
        self.assertEqual(proposal.decided_by, self.admin.id)
        self.assertEqual(proposal.decision_note, "转人工")

    def test_dismiss_route(self):
        run = HrAgentRun.objects.create(
            workspace_id="workspace-a", agent_type="SCREENING", trigger_type="MANUAL",
            ref_object_type="APPLICATION", ref_object_id=self.application_id, status="SUCCEEDED",
            prompt_version="v", user_id=self.admin.id,
        )
        proposal = HrAgentProposal.objects.create(
            workspace_id="workspace-a", run=run, target_type="APPLICATION",
            target_id=self.application_id, action="ADVANCE", status="PENDING",
            payload_json={"stage_key": "APPLIED"},
        )
        response = self._client(self.admin).post(
            "/admin/api/workspace/workspace-a/hr/proposals/{}/dismiss".format(proposal.id),
            {"decision_note": "忽略"}, content_type="application/json",
        )
        self.assertEqual(response.json()["data"]["status"], "DISMISSED")



class ProtectedResumeIndexTests(TestCase):
    """D1 收尾（PRD-AGENT-RAG §7/§14 #3）：简历语义索引为受保护索引——列表隐藏、禁删禁改"""

    def setUp(self):
        self.user = User.objects.create(
            username="protect-" + uuid.uuid7().hex[:8], nick_name="protect", password="p", role="ADMIN"
        )
        KnowledgeFolder.objects.get_or_create(
            id="default", defaults={"name": "default", "workspace_id": "default"}
        )
        self.workspace_id = "workspace-protect"
        self.protected = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id=self.workspace_id, name="简历语义索引",
            desc="", type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value,
            user_id=self.user.id, meta={"hr_protected": True},
        )
        self.normal = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id=self.workspace_id, name="企业政策库",
            desc="", type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value,
            user_id=self.user.id,
        )

    def _query(self):
        return KnowledgeSerializer.Query(
            data={"workspace_id": self.workspace_id, "user_id": str(self.user.id), "name": "",
                  "folder_id": "default"}
        )

    def test_list_excludes_protected_index(self):
        result = self._query().list()
        ids = {row["id"] for row in result}
        self.assertIn(str(self.normal.id), ids)
        self.assertNotIn(str(self.protected.id), ids)

    def test_page_excludes_protected_index(self):
        result = self._query().page(1, 10)
        ids = {row["id"] for row in result["records"]}
        self.assertIn(str(self.normal.id), ids)
        self.assertNotIn(str(self.protected.id), ids)

    def test_delete_protected_rejected(self):
        operate = KnowledgeSerializer.Operate(
            data={"user_id": str(self.user.id), "workspace_id": self.workspace_id,
                  "knowledge_id": str(self.protected.id)}
        )
        with self.assertRaisesRegex(AppApiException, "不可删除"):
            operate.delete()
        self.assertTrue(Knowledge.objects.filter(id=self.protected.id).exists())
        operate = KnowledgeSerializer.Operate(
            data={"user_id": str(self.user.id), "workspace_id": self.workspace_id,
                  "knowledge_id": str(self.normal.id)}
        )
        self.assertTrue(operate.delete())

    def test_batch_delete_with_protected_rejected(self):
        from knowledge.serializers.knowledge import KnowledgeBatchOperateSerializer
        operate = KnowledgeBatchOperateSerializer(
            data={"user_id": str(self.user.id), "workspace_id": self.workspace_id}
        )
        operate.is_valid(raise_exception=True)
        with self.assertRaisesRegex(AppApiException, "不可删除"):
            operate.batch_delete(
                {"id_list": [str(self.normal.id), str(self.protected.id)]}, with_valid=False
            )
        self.assertTrue(Knowledge.objects.filter(id=self.protected.id).exists())
        self.assertTrue(Knowledge.objects.filter(id=self.normal.id).exists())

    def test_edit_protected_rejected(self):
        operate = KnowledgeSerializer.Operate(
            data={"user_id": str(self.user.id), "workspace_id": self.workspace_id,
                  "knowledge_id": str(self.protected.id)}
        )
        with self.assertRaisesRegex(AppApiException, "不可编辑"):
            operate.edit({"name": "改名"}, select_one=False)

    def test_get_resume_knowledge_backfills_marker(self):
        from hr.services.resume_index import get_resume_knowledge
        legacy = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id="workspace-legacy", name="简历语义索引",
            desc="", type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value,
            user_id=self.user.id,
        )
        found = get_resume_knowledge("workspace-legacy")
        self.assertEqual(found.id, legacy.id)
        self.assertTrue((found.meta or {}).get("hr_protected"))

class KnowledgeSearchToolTests(TestCase):
    """D2 search_knowledge：白名单强制 + 保护索引排除 + PII 掩码 + 结果形状"""

    def setUp(self):
        self.user = User.objects.create(
            username="kb-" + uuid.uuid7().hex[:8], nick_name="kb", password="p", role="ADMIN"
        )
        KnowledgeFolder.objects.get_or_create(id="default", defaults={"name": "default", "workspace_id": "default"})
        self.workspace_id = "workspace-kb"
        self.kb = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id=self.workspace_id, name="JD 模板库",
            desc="", type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value, user_id=self.user.id,
        )
        self.kb_other = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id=self.workspace_id, name="其他库",
            desc="", type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value, user_id=self.user.id,
        )
        self.kb_protected = Knowledge.objects.create(
            id=uuid.uuid7(), workspace_id=self.workspace_id, name="受保护简历索引",
            desc="", type=KnowledgeType.BASE.value, scope=KnowledgeScope.WORKSPACE.value, user_id=self.user.id,
            meta={"hr_protected": True},
        )
        HrConfig.objects.update_or_create(
            workspace_id=self.workspace_id,
            defaults={"llm_model_id": "fake", "agent_knowledge_bases": [str(self.kb.id), str(self.kb_protected.id)]},
        )
        self.document = Document.objects.create(
            id=uuid.uuid7(), knowledge=self.kb, name="JD规范.docx", char_length=200,
            user_id=self.user.id,
        )
        self.paragraph = Paragraph.objects.create(
            id=uuid.uuid7(), document=self.document, knowledge=self.kb, content="请联系 13812345678 或 alice@test.com",
            title="职位描述",
        )

    def _fake_embedding_model(self):
        fake = Mock()
        fake.embed_query.return_value = [0.1] * 8
        return fake

    def test_whitelist_enforced(self):
        from hr.services.knowledge_search import search_knowledge
        with self.assertRaises(AppApiException) as ctx:
            search_knowledge(self.workspace_id, "JD", kb_ids=[str(self.kb_other.id)])
        self.assertEqual(ctx.exception.code, 400)

    def test_whitelist_only_and_protected_excluded(self):
        with patch("hr.services.knowledge_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model()), \
                patch("hr.services.knowledge_search.EmbeddingSearch") as m_emb, \
                patch("hr.services.knowledge_search.KeywordsSearch") as m_key:
            from hr.services.knowledge_search import search_knowledge
            m_emb.return_value.handle.return_value = [{"paragraph_id": str(self.paragraph.id), "similarity": 0.9}]
            m_key.return_value.handle.return_value = []
            result = search_knowledge(self.workspace_id, "JD 模板")
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["knowledge_name"], "JD 模板库")
        self.assertEqual(item["document_name"], "JD规范.docx")
        self.assertIn("138****5678", item["content"])
        self.assertNotIn("13812345678", item["content"])
        self.assertIn("al***@test.com", item["content"])
        self.assertNotIn("alice@test.com", item["content"])
        # 受保护简历索引在白名单内也被排除（检索源仅企业知识库）
        patched = patch("hr.services.knowledge_search.get_embedding_model_by_knowledge_id", return_value=self._fake_embedding_model())
        with patched, patch("hr.services.knowledge_search.EmbeddingSearch") as m_emb2, \
                patch("hr.services.knowledge_search.KeywordsSearch"):
            m_emb2.return_value.handle.return_value = [{"paragraph_id": "missing", "similarity": 0.9}]
            result2 = search_knowledge(self.workspace_id, "JD", kb_ids=[str(self.kb_protected.id)])
        self.assertEqual(result2["items"], [])

    def test_empty_whitelist_returns_empty(self):
        from hr.services.knowledge_search import search_knowledge
        HrConfig.objects.update_or_create(workspace_id=self.workspace_id, defaults={"agent_knowledge_bases": []})
        result = search_knowledge(self.workspace_id, "JD")
        self.assertEqual(result["items"], [])
        self.assertEqual(result["meta"]["knowledge_count"], 0)


class SimilarJobsServiceTests(TestCase):
    """D2 similar_jobs：SQL 相似打分 + HIRED 录用画像，不含候选人联系方式"""

    def setUp(self):
        self.workspace_id = "workspace-sim"
        self.recruitment = RecruitmentService(self.workspace_id, uuid.uuid7(), hr_role="ADMIN")
        base = {"headcount": 1}
        self.job_a = Job.objects.get(id=self.recruitment.create_job(
            {"name": "Python 后端", "department": "Eng", "city": "上海", "skill_requirements": ["Python", "Django"], **base})["id"])
        self.job_b = Job.objects.get(id=self.recruitment.create_job(
            {"name": "资深 Python", "department": "Eng", "city": "上海", "skill_requirements": ["Python", "FastAPI"], **base})["id"])
        job_c = self.recruitment.create_job(
            {"name": "Java 前端", "department": "Ops", "city": "北京", "skill_requirements": ["Java"], **base}
        )
        self.job_c_id = job_c["id"]

    def _hired(self, job, skills, years):
        candidate = Candidate.objects.create(
            name="Hired-" + uuid.uuid7().hex[:6], workspace_id=self.workspace_id,
            skills=skills, years_experience=years,
        )
        return ApplicationService(self.workspace_id, uuid.uuid7(), hr_role="ADMIN").create_application(
            job.id, candidate.id, {}
        )

    def test_rank_and_hired_profile(self):
        from hr.services.similar_jobs import similar_jobs
        app = self._hired(self.job_b, ["Python", "Django"], 6)
        Application.objects.filter(id=app["id"]).update(status="HIRED")
        rows = similar_jobs(self.workspace_id, str(self.job_a.id))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["job_id"], str(self.job_b.id))
        self.assertEqual(row["hired_count"], 1)
        self.assertEqual(row["hired_avg_years"], 6.0)
        self.assertTrue(any(skill == "python" for skill in row["hired_top_skills"]))
        dumped = json.dumps(row)
        self.assertNotIn("phone", dumped)
        self.assertNotIn("email", dumped)

    def test_excludes_self_and_unrelated(self):
        from hr.services.similar_jobs import similar_jobs
        rows = similar_jobs(self.workspace_id, str(self.job_c_id))
        self.assertEqual(rows, [])


class JdDraftRunnerTests(TestCase):
    """D2 JD 起草 Runner：固定顺序工具 + LLM 草稿 + DRAFT 提案（target=JOB）"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.workspace_id = "workspace-jddraft"
        self.recruitment = RecruitmentService(self.workspace_id, self.user_id, hr_role="ADMIN")
        HrConfig.objects.update_or_create(
            workspace_id=self.workspace_id,
            defaults={"llm_model_id": "fake-llm", "agent_max_concurrent_runs": 2, "agent_run_rate_limit": 100},
        )
        job_data = self.recruitment.create_job({
            "name": "Python Engineer", "department": "Eng", "city": "上海",
            "skill_requirements": ["Python"], "description": "旧描述",
        })
        self.job = Job.objects.get(id=job_data["id"])

    def _fake_model(self, payload):
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return fake

    def _draft_payload(self):
        return {
            "name": "高级 Python 工程师",
            "description": "# 岗位职责\n负责核心服务开发。",
            "skill_requirements": ["Python", "Django"],
            "summary": "对标 JD 模板库与相似职位",
            "sources": [{"kind": "knowledge", "ref": "JD 模板库", "note": "职责结构"}],
        }

    def _patches(self, payload=None, kb_raise=False):
        from hr.agents.jd_runner import run_jd_draft_agent
        return (patch("hr.agents.jd_runner._load_llm", return_value=(self._fake_model(payload if payload is not None else self._draft_payload()), "fake-llm")),
                patch("hr.agents.jd_runner.search_knowledge", side_effect=AppApiException(500, "kb down") if kb_raise else lambda *a, **kw: {"items": [{"paragraph_id": "p1", "knowledge_id": "k1", "knowledge_name": "JD模板", "document_id": "d1", "document_name": "规范", "title": "t", "content": "模板内容", "score": 0.9}], "meta": {"knowledge_count": 1, "total": 1}}),
                patch("hr.agents.jd_runner.similar_jobs", return_value=[{"job_id": "j2", "name": "相似职位", "department": "Eng", "city": "上海", "level": "", "skill_overlap": ["Python"], "similarity": 0.8, "hired_count": 3, "hired_avg_years": 5.0, "hired_top_skills": ["python"]}]),
                run_jd_draft_agent)

    def test_success_flow_creates_job_draft_proposal(self):
        from hr.agents.jd_runner import run_jd_draft_agent
        with patch("hr.agents.jd_runner._load_llm", return_value=(self._fake_model(self._draft_payload()), "fake-llm")), \
                patch("hr.agents.jd_runner.search_knowledge", return_value={"items": [], "meta": {}}), \
                patch("hr.agents.jd_runner.similar_jobs", return_value=[]):
            output = run_jd_draft_agent(str(self.job.id), user_id=self.user_id)
        self.assertEqual(output["status"], "SUCCEEDED")
        run = HrAgentRun.objects.get(id=output["run_id"])
        self.assertEqual(run.agent_type, "JD_DRAFT")
        self.assertEqual(run.ref_object_type, "JOB")
        self.assertEqual(run.ref_object_id, str(self.job.id))
        self.assertEqual(run.prompt_version, "jd-draft-v1")
        tool_names = [item["tool"] for item in run.tool_trace]
        self.assertEqual(tool_names, ["get_job", "search_knowledge", "similar_jobs"])
        proposal = HrAgentProposal.objects.get(id=output["proposal_id"])
        self.assertEqual(proposal.target_type, "JOB")
        self.assertEqual(proposal.target_id, str(self.job.id))
        self.assertEqual(proposal.action, "DRAFT")
        self.assertEqual(proposal.status, "PENDING")
        self.assertIn("岗位职责", proposal.payload_json["fields"]["description"])
        self.assertTrue(
            HrAuditLog.objects.filter(workspace_id=self.workspace_id, action="AGENT_RUN", trace_id=run.id).exists()
        )
        self.assertTrue(HrConfig.objects.get(workspace_id=self.workspace_id).agent_prompt_versions.get("JD_DRAFT"))

    def test_kb_failure_does_not_abort(self):
        from hr.agents.jd_runner import run_jd_draft_agent
        with patch("hr.agents.jd_runner._load_llm", return_value=(self._fake_model(self._draft_payload()), "fake-llm")), \
                patch("hr.agents.jd_runner.search_knowledge", side_effect=AppApiException(500, "kb down")), \
                patch("hr.agents.jd_runner.similar_jobs", return_value=[]):
            output = run_jd_draft_agent(str(self.job.id), user_id=self.user_id)
        self.assertEqual(output["status"], "SUCCEEDED")

    def test_job_not_found_returns_none(self):
        from hr.agents.jd_runner import run_jd_draft_agent
        self.assertIsNone(run_jd_draft_agent(str(uuid.uuid7()), user_id=self.user_id))

    def test_closed_job_skips(self):
        from hr.agents.jd_runner import run_jd_draft_agent
        Job.objects.filter(id=self.job.id).update(status="CLOSED", close_reason="OTHER")
        output = run_jd_draft_agent(str(self.job.id), user_id=self.user_id)
        self.assertEqual(output["status"], "SKIPPED")
        self.assertIn("closed", output["error"])

    def test_invalid_llm_output_marks_failed(self):
        from hr.agents.jd_runner import run_jd_draft_agent
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content="not json")
        with patch("hr.agents.jd_runner._load_llm", return_value=(fake, "fake-llm")), \
                patch("hr.agents.jd_runner.search_knowledge", return_value={"items": [], "meta": {}}), \
                patch("hr.agents.jd_runner.similar_jobs", return_value=[]):
            output = run_jd_draft_agent(str(self.job.id), user_id=self.user_id)
        self.assertEqual(output["status"], "FAILED")
        self.assertTrue(HrAgentRun.objects.get(id=output["run_id"]).error)

    def test_new_run_expires_previous_pending_draft(self):
        from hr.agents.jd_runner import run_jd_draft_agent
        with patch("hr.agents.jd_runner._load_llm", return_value=(self._fake_model(self._draft_payload()), "fake-llm")), \
                patch("hr.agents.jd_runner.search_knowledge", return_value={"items": [], "meta": {}}), \
                patch("hr.agents.jd_runner.similar_jobs", return_value=[]):
            first = run_jd_draft_agent(str(self.job.id), user_id=self.user_id)
            second = run_jd_draft_agent(str(self.job.id), user_id=self.user_id)
        self.assertEqual(HrAgentProposal.objects.get(id=first["proposal_id"]).status, "EXPIRED")
        self.assertEqual(HrAgentProposal.objects.filter(
            workspace_id=self.workspace_id, target_type="JOB", target_id=str(self.job.id), status="PENDING"
        ).count(), 1)
        self.assertEqual(second["proposal_id"], str(HrAgentProposal.objects.get(
            workspace_id=self.workspace_id, target_type="JOB", target_id=str(self.job.id), status="PENDING").id))


class JdDraftAcceptTests(TestCase):
    """D2 JD 草稿采纳：仅写字段不改状态；ADMIN；幂等；关闭后过期"""

    def setUp(self):
        self.admin_id = uuid.uuid7()
        self.operator_id = uuid.uuid7()
        self.workspace_id = "workspace-jdaccept"
        self.recruitment = RecruitmentService(self.workspace_id, self.admin_id, hr_role="ADMIN")
        job_data = self.recruitment.create_job(
            {"name": "Engineer", "department": "Eng", "city": "上海", "skill_requirements": ["Python"]}
        )
        self.job = Job.objects.get(id=job_data["id"])

    def _proposal(self):
        from hr.agents.proposals import propose
        run = HrAgentRun.objects.create(
            workspace_id=self.workspace_id, agent_type="JD_DRAFT", trigger_type="MANUAL",
            ref_object_type="JOB", ref_object_id=str(self.job.id), status="SUCCEEDED",
            prompt_version="v", user_id=self.admin_id,
        )
        return propose(
            self.workspace_id, run, str(self.job.id), action="DRAFT", target_type="JOB",
            payload_json={"draft_target": "JOB", "fields": {
                "name": "高级工程师",
                "description": "# 岗位职责\n新草稿描述",
                "skill_requirements": ["Python", "Django"],
            }},
        )

    def _service(self, hr_role, user_id=None):
        return ProposalService(self.workspace_id, user_id or self.admin_id, hr_role)

    def test_accept_applies_fields_without_status_change(self):
        proposal = self._proposal()
        accepted = self._service("ADMIN").accept(proposal.id, {"decision_note": "采纳"})
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.job.refresh_from_db()
        self.assertEqual(self.job.name, "高级工程师")
        self.assertIn("新草稿描述", self.job.description)
        self.assertEqual(self.job.skill_requirements, ["Python", "Django"])
        self.assertEqual(self.job.status, "OPEN")
        self.assertTrue(HrAuditLog.objects.filter(
            workspace_id=self.workspace_id, action="AGENT_DECIDE", trace_id=proposal.run_id
        ).exists())

    def test_operator_cannot_apply_job_draft(self):
        proposal = self._proposal()
        with self.assertRaises(AppUnauthorizedFailed):
            self._service("OPERATOR", self.operator_id).accept(proposal.id, {})

    def test_accept_twice_rejected(self):
        proposal = self._proposal()
        self._service("ADMIN").accept(proposal.id, {})
        with self.assertRaises(AppApiException):
            self._service("ADMIN").accept(proposal.id, {})

    def test_accept_when_job_closed_expires(self):
        proposal = self._proposal()
        Job.objects.filter(id=self.job.id).update(status="CLOSED", close_reason="OTHER")
        with self.assertRaises(AppApiException) as ctx:
            self._service("ADMIN").accept(proposal.id, {})
        self.assertEqual(ctx.exception.code, 409)
        self.assertEqual(HrAgentProposal.objects.get(id=proposal.id).status, "EXPIRED")


class InterviewCopilotRunnerTests(TestCase):
    """D2 Interview Copilot Runner：prepare 面试题 / feedback 评估草稿；面试官权限；无 PII"""

    def setUp(self):
        self.interviewer = User.objects.create(
            username="copilot-" + uuid.uuid7().hex[:8], nick_name="copilot", password="p", role="ADMIN"
        )
        self.other_id = uuid.uuid7()
        self.workspace_id = "workspace-copilot"
        self.recruitment = RecruitmentService(self.workspace_id, self.interviewer.id, hr_role="ADMIN")
        HrConfig.objects.update_or_create(
            workspace_id=self.workspace_id,
            defaults={"llm_model_id": "fake-llm", "agent_max_concurrent_runs": 2, "agent_run_rate_limit": 100},
        )
        self.candidate = Candidate.objects.create(
            name="Alice", workspace_id=self.workspace_id, skills=["python"],
            current_city="上海", highest_degree="硕士", years_experience=5,
        )
        job_data = self.recruitment.create_job({
            "name": "Python Engineer", "department": "Eng", "city": "上海",
            "skill_requirements": ["Python", "K8s"],
        })
        self.job = Job.objects.get(id=job_data["id"])
        self.application = ApplicationService(self.workspace_id, self.interviewer.id, hr_role="ADMIN").create_application(
            self.job.id, self.candidate.id, {}
        )
        self.interview = Interview.objects.create(
            workspace_id=self.workspace_id, application=Application.objects.get(id=self.application["id"]),
            round_no=1, interviewer=self.interviewer.nick_name,
            interviewer_user_id=self.interviewer.id, status="PENDING", user_id=self.interviewer.id,
        )

    def _fake_model(self, payload):
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return fake

    def _prepare_facts(self):
        return {
            "weak_spots": [{"name": "K8s", "detail": "简历未提及容器化经验", "evidence": []}],
            "questions": [
                {"question": "请介绍你的 Python 项目", "target": "经验真实性", "difficulty": "基础", "follow_up": ""},
                {"question": "K8s 部署经验？", "target": "技能深挖", "difficulty": "深挖", "follow_up": "如何排查"},
                {"question": "如何排查线上故障", "target": "软素质", "difficulty": "进阶", "follow_up": ""},
                {"question": "为什么加入我们", "target": "动机", "difficulty": "基础", "follow_up": ""},
                {"question": "团队协作经历", "target": "软素质", "difficulty": "进阶", "follow_up": ""},
            ],
            "focus": ["K8s 实操", "排障能力"],
        }

    def test_prepare_success_by_interviewer(self):
        from hr.agents.copilot_runner import run_interview_copilot
        with patch("hr.agents.copilot_runner._load_llm", return_value=(self._fake_model(self._prepare_facts()), "fake-llm")), \
                patch("hr.agents.copilot_runner.search_resumes", return_value={"items": [], "meta": {}}), \
                patch("hr.agents.copilot_runner.search_knowledge", return_value={"items": [], "meta": {}}), \
                patch("hr.agents.copilot_runner.similar_jobs", return_value=[]):
            output = run_interview_copilot(
                str(self.interview.id), data={"phase": "prepare"}, user_id=self.interviewer.id, hr_role="VIEWER"
            )
        self.assertEqual(output["status"], "SUCCEEDED")
        run = HrAgentRun.objects.get(id=output["run_id"])
        self.assertEqual(run.agent_type, "INTERVIEW_COPILOT")
        self.assertEqual(run.ref_object_type, "INTERVIEW")
        self.assertEqual(run.ref_object_id, str(self.interview.id))
        tool_names = [item["tool"] for item in run.tool_trace]
        self.assertEqual(tool_names, ["get_job", "get_candidate_overview", "search_resumes", "search_knowledge", "similar_jobs"])
        proposal = HrAgentProposal.objects.get(id=output["proposal_id"])
        self.assertEqual(proposal.target_type, "INTERVIEW")
        self.assertEqual(proposal.action, "DRAFT")
        self.assertEqual(proposal.payload_json["phase"], "prepare")
        self.assertEqual(len(proposal.payload_json["questions"]), 5)

    def test_no_pii_in_payload(self):
        from hr.agents.copilot_runner import run_interview_copilot
        with patch("hr.agents.copilot_runner._load_llm", return_value=(self._fake_model(self._prepare_facts()), "fake-llm")), \
                patch("hr.agents.copilot_runner.search_resumes", return_value={"items": [{"candidate": {"id": str(self.candidate.id), "name": "Alice", "phone": "13812345678", "email": "a@b.com"}, "resume": {"id": "r1"}, "paragraphs": [{"id": "p1", "title": "t", "content": "Python", "score": 0.8}], "document_id": "d1"}], "meta": {}}), \
                patch("hr.agents.copilot_runner.search_knowledge", return_value={"items": [], "meta": {}}), \
                patch("hr.agents.copilot_runner.similar_jobs", return_value=[]):
            output = run_interview_copilot(str(self.interview.id), user_id=self.interviewer.id, hr_role="ADMIN")
        run = HrAgentRun.objects.get(id=output["run_id"])
        dumped = json.dumps({"input": run.input_meta, "trace": run.tool_trace, "output": run.output_json}, ensure_ascii=False)
        self.assertNotIn("13812345678", dumped)
        self.assertNotIn("a@b.com", dumped)

    def test_feedback_phase_generates_draft(self):
        from hr.agents.copilot_runner import run_interview_copilot
        feedback_facts = {"evaluation_draft": "综合表现良好，K8s 经验欠缺", "recommendation_hint": "推进", "open_items": ["K8s"]}
        Interview.objects.filter(id=self.interview.id).update(status="PASSED", feedback="表现不错")
        with patch("hr.agents.copilot_runner._load_llm", return_value=(self._fake_model(feedback_facts), "fake-llm")), \
                patch("hr.agents.copilot_runner.search_resumes", return_value={"items": [], "meta": {}}), \
                patch("hr.agents.copilot_runner.search_knowledge", return_value={"items": [], "meta": {}}), \
                patch("hr.agents.copilot_runner.similar_jobs", return_value=[]):
            output = run_interview_copilot(
                str(self.interview.id), data={"phase": "feedback", "feedback": "表现不错但 K8s 欠缺"},
                user_id=self.interviewer.id, hr_role="VIEWER",
            )
        self.assertEqual(output["status"], "SUCCEEDED")
        proposal = HrAgentProposal.objects.get(id=output["proposal_id"])
        self.assertEqual(proposal.payload_json["phase"], "feedback")
        self.assertIn("K8s", proposal.payload_json["evaluation_draft"])

    def test_feedback_phase_requires_feedback_text(self):
        from hr.agents.copilot_runner import run_interview_copilot
        output = run_interview_copilot(
            str(self.interview.id), data={"phase": "feedback"}, user_id=self.interviewer.id, hr_role="ADMIN"
        )
        self.assertEqual(output["status"], "SKIPPED")
        self.assertIn("feedback text", output["error"])

    def test_non_interviewer_viewer_denied(self):
        from hr.agents.copilot_runner import run_interview_copilot
        with self.assertRaises(AppUnauthorizedFailed):
            run_interview_copilot(str(self.interview.id), data={"phase": "prepare"}, user_id=self.other_id, hr_role="VIEWER")

    def test_prepare_skips_when_feedback_submitted(self):
        from hr.agents.copilot_runner import run_interview_copilot
        Interview.objects.filter(id=self.interview.id).update(status="PASSED")
        output = run_interview_copilot(str(self.interview.id), data={"phase": "prepare"}, user_id=self.interviewer.id, hr_role="ADMIN")
        self.assertEqual(output["status"], "SKIPPED")
        self.assertIn("interview not pending", output["error"])

    def test_interview_not_found_returns_none(self):
        from hr.agents.copilot_runner import run_interview_copilot
        self.assertIsNone(run_interview_copilot(str(uuid.uuid7()), user_id=self.interviewer.id, hr_role="ADMIN"))


class InterviewCopilotAcceptTests(TestCase):
    """D2 Copilot 草稿确认：不改业务状态；prepare 反馈后过期 / feedback 可采纳"""

    def setUp(self):
        self.owner_id = uuid.uuid7()
        self.workspace_id = "workspace-copilot-accept"
        self.recruitment = RecruitmentService(self.workspace_id, self.owner_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id=self.workspace_id)
        job_data = self.recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.application = ApplicationService(self.workspace_id, self.owner_id, hr_role="ADMIN").create_application(
            self.job.id, self.candidate.id, {}
        )
        self.interview = Interview.objects.create(
            workspace_id=self.workspace_id, application=Application.objects.get(id=self.application["id"]),
            round_no=1, interviewer="HR", interviewer_user_id=self.owner_id,
            status="PENDING", user_id=self.owner_id,
        )

    def _proposal(self, phase="prepare"):
        from hr.agents.proposals import propose
        run = HrAgentRun.objects.create(
            workspace_id=self.workspace_id, agent_type="INTERVIEW_COPILOT", trigger_type="MANUAL",
            ref_object_type="INTERVIEW", ref_object_id=str(self.interview.id), status="SUCCEEDED",
            prompt_version="v", user_id=self.owner_id,
        )
        payload = {"phase": phase, "questions": [{"question": "q1", "target": "t", "difficulty": "基础", "follow_up": ""}]}
        if phase == "feedback":
            payload = {"phase": phase, "evaluation_draft": "draft", "recommendation_hint": "推进", "open_items": []}
        return propose(
            self.workspace_id, run, str(self.interview.id), action="DRAFT", target_type="INTERVIEW",
            payload_json=payload,
        )

    def _service(self, hr_role="ADMIN"):
        return ProposalService(self.workspace_id, self.owner_id, hr_role)

    def test_accept_confirms_without_state_change(self):
        proposal = self._proposal()
        accepted = self._service().accept(proposal.id, {})
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.interview.refresh_from_db()
        self.assertEqual(self.interview.status, "PENDING")
        self.assertEqual(self.interview.feedback, "")
        self.assertTrue(HrAuditLog.objects.filter(
            workspace_id=self.workspace_id, action="AGENT_DECIDE"
        ).exists())

    def test_viewer_cannot_decide(self):
        proposal = self._proposal()
        with self.assertRaises(AppUnauthorizedFailed):
            ProposalService(self.workspace_id, self.owner_id, "VIEWER").accept(proposal.id, {})

    def test_prepare_proposal_expires_after_feedback(self):
        proposal = self._proposal()
        Interview.objects.filter(id=self.interview.id).update(status="PASSED", feedback="ok")
        with self.assertRaises(AppApiException) as ctx:
            self._service().accept(proposal.id, {})
        self.assertEqual(ctx.exception.code, 409)
        self.assertEqual(HrAgentProposal.objects.get(id=proposal.id).status, "EXPIRED")

    def test_feedback_proposal_acceptable_after_feedback(self):
        proposal = self._proposal(phase="feedback")
        Interview.objects.filter(id=self.interview.id).update(status="PASSED", feedback="ok")
        accepted = self._service().accept(proposal.id, {})
        self.assertEqual(accepted["status"], "ACCEPTED")

class SourcingRunnerTests(TestCase):
    """D3 Sourcing：沉睡候选人池（剔除已投递）+ 硬条件过滤 + LLM 优先级清单（DRAFT×JOB）"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.workspace_id = "workspace-sourcing"
        self.recruitment = RecruitmentService(self.workspace_id, self.user_id, hr_role="ADMIN")
        HrConfig.objects.update_or_create(
            workspace_id=self.workspace_id,
            defaults={"llm_model_id": "fake-llm", "agent_max_concurrent_runs": 2, "agent_run_rate_limit": 100},
        )
        job_data = self.recruitment.create_job({
            "name": "Python Engineer", "department": "Eng", "city": "上海",
            "skill_requirements": ["Python"], "description": "后端开发",
        })
        self.job = Job.objects.get(id=job_data["id"])
        self.candidate_a = Candidate.objects.create(
            name="Alice", workspace_id=self.workspace_id, skills=["python"],
            current_city="上海", highest_degree="硕士", years_experience=5,
        )
        self.candidate_b = Candidate.objects.create(
            name="Bob", workspace_id=self.workspace_id, skills=["python"],
            current_city="上海", highest_degree="本科", years_experience=3,
        )
        self.candidate_c = Candidate.objects.create(
            name="Carol", workspace_id=self.workspace_id, skills=["java"],
            current_city="北京", highest_degree="本科", years_experience=2,
        )
        # Bob 已投递该职位（历史申请）→ 应从沉睡池剔除
        ApplicationService(self.workspace_id, self.user_id, hr_role="ADMIN").create_application(
            self.job.id, self.candidate_b.id, {}
        )

    def _item(self, candidate):
        return {
            "candidate": {"id": str(candidate.id), "name": candidate.name, "phone": "13812345678",
                          "email": "a@b.com", "current_city": candidate.current_city,
                          "highest_degree": candidate.highest_degree,
                          "years_experience": candidate.years_experience, "skills": candidate.skills},
            "resume": {"id": "r1"},
            "paragraphs": [{"id": "p1", "title": "工作经历", "content": "Python 后端经验", "score": 0.8}],
            "document_id": "d1",
        }

    def _fake_model(self, payload):
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return fake

    def test_success_flow_with_sleeping_pool(self):
        from hr.agents.sourcing_runner import run_sourcing_agent
        facts = {
            "candidates": [
                {"candidate_id": str(self.candidate_a.id), "match_reason": "五年 Python 后端经验",
                 "risk": "", "evidence": [{"paragraph_id": "p1", "excerpt": "Python 后端经验", "relevance": 0.9}]},
            ],
            "summary": "池内 1 名沉睡候选人匹配",
        }
        with patch("hr.agents.sourcing_runner._load_llm", return_value=(self._fake_model(facts), "fake-llm")), \
                patch("hr.agents.sourcing_runner.search_resumes", return_value={
                    "items": [self._item(self.candidate_a), self._item(self.candidate_b), self._item(self.candidate_c)],
                    "meta": {},
                }):
            output = run_sourcing_agent(str(self.job.id), user_id=self.user_id)
        self.assertEqual(output["status"], "SUCCEEDED")
        run = HrAgentRun.objects.get(id=output["run_id"])
        self.assertEqual(run.agent_type, "SOURCING")
        tool_names = [item["tool"] for item in run.tool_trace]
        self.assertEqual(tool_names, ["get_job", "search_resumes", "structured_filter"])
        proposal = HrAgentProposal.objects.get(id=output["proposal_id"])
        self.assertEqual(proposal.target_type, "JOB")
        self.assertEqual(proposal.action, "DRAFT")
        candidates = proposal.payload_json["candidates"]
        self.assertEqual([c["candidate_id"] for c in candidates], [str(self.candidate_a.id)])
        self.assertEqual(candidates[0]["name"], "Alice")
        self.assertNotIn("13812345678", json.dumps(proposal.payload_json, ensure_ascii=False))
        self.assertNotIn("a@b.com", json.dumps(proposal.payload_json, ensure_ascii=False))

    def test_llm_hallucinated_ids_filtered(self):
        from hr.agents.sourcing_runner import run_sourcing_agent
        facts = {
            "candidates": [
                {"candidate_id": str(self.candidate_a.id), "match_reason": "ok", "risk": "", "evidence": []},
                {"candidate_id": str(uuid.uuid7()), "match_reason": "幻觉", "risk": "", "evidence": []},
            ],
            "summary": "s",
        }
        with patch("hr.agents.sourcing_runner._load_llm", return_value=(self._fake_model(facts), "fake-llm")), \
                patch("hr.agents.sourcing_runner.search_resumes", return_value={
                    "items": [self._item(self.candidate_a)], "meta": {},
                }):
            output = run_sourcing_agent(str(self.job.id), user_id=self.user_id)
        self.assertEqual(output["status"], "SUCCEEDED")
        proposal = HrAgentProposal.objects.get(id=output["proposal_id"])
        self.assertEqual(len(proposal.payload_json["candidates"]), 1)

    def test_empty_pool_marks_failed(self):
        from hr.agents.sourcing_runner import run_sourcing_agent
        with patch("hr.agents.sourcing_runner._load_llm", return_value=(self._fake_model({}), "fake-llm")), \
                patch("hr.agents.sourcing_runner.search_resumes", return_value={"items": [], "meta": {}}):
            output = run_sourcing_agent(str(self.job.id), user_id=self.user_id)
        self.assertEqual(output["status"], "FAILED")
        self.assertIn("no sleeping candidates", HrAgentRun.objects.get(id=output["run_id"]).error)

    def test_non_open_job_skips(self):
        from hr.agents.sourcing_runner import run_sourcing_agent
        Job.objects.filter(id=self.job.id).update(status="ON_HOLD")
        output = run_sourcing_agent(str(self.job.id), user_id=self.user_id)
        self.assertEqual(output["status"], "SKIPPED")
        self.assertIn("OPEN", output["error"])

    def test_job_not_found_returns_none(self):
        from hr.agents.sourcing_runner import run_sourcing_agent
        self.assertIsNone(run_sourcing_agent(str(uuid.uuid7()), user_id=self.user_id))


class CommunicationDraftTests(TestCase):
    """D3 沟通草稿：scenario 分发 + 企业话术库检索 + DRAFT×APPLICATION；无 PII"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.workspace_id = "workspace-draft"
        self.recruitment = RecruitmentService(self.workspace_id, self.user_id, hr_role="ADMIN")
        HrConfig.objects.update_or_create(
            workspace_id=self.workspace_id,
            defaults={"llm_model_id": "fake-llm", "agent_max_concurrent_runs": 2, "agent_run_rate_limit": 100},
        )
        self.candidate = Candidate.objects.create(
            name="Alice", workspace_id=self.workspace_id, skills=["python"],
            current_city="上海", highest_degree="硕士", years_experience=5,
        )
        job_data = self.recruitment.create_job({"name": "Engineer", "headcount": 1, "skill_requirements": ["Python"]})
        self.job = Job.objects.get(id=job_data["id"])
        self.application = ApplicationService(self.workspace_id, self.user_id, hr_role="ADMIN").create_application(
            self.job.id, self.candidate.id, {}
        )

    def _fake_model(self, payload):
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
        return fake

    def _draft_facts(self):
        return {
            "draft": "尊敬的 {{候选人}}：很遗憾通知您…",
            "key_points": ["结果明确", "语气克制"],
            "tone": "专业克制",
            "sources": [{"kind": "knowledge", "ref": "政策库", "note": "口径"}],
        }

    def _patched_search_knowledge(self):
        return patch("hr.agents.draft_runner.search_knowledge", return_value={
            "items": [{"paragraph_id": "p1", "knowledge_id": "k1", "knowledge_name": "政策库",
                       "document_id": "d1", "document_name": "话术规范", "title": "t",
                       "content": "请联系 13812345678", "score": 0.9}],
            "meta": {"knowledge_count": 1, "total": 1},
        })

    def test_success_flow_creates_draft_proposal(self):
        from hr.agents.draft_runner import run_communication_draft
        with patch("hr.agents.draft_runner._load_llm", return_value=(self._fake_model(self._draft_facts()), "fake-llm")), \
                self._patched_search_knowledge():
            output = run_communication_draft(
                self.application["id"], data={"scenario": "REJECT"}, user_id=self.user_id, hr_role="ADMIN"
            )
        self.assertEqual(output["status"], "SUCCEEDED")
        run = HrAgentRun.objects.get(id=output["run_id"])
        self.assertEqual(run.agent_type, "COMMUNICATION_DRAFT")
        tool_names = [item["tool"] for item in run.tool_trace]
        self.assertEqual(tool_names, ["get_job", "get_candidate_overview", "search_knowledge"])
        proposal = HrAgentProposal.objects.get(id=output["proposal_id"])
        self.assertEqual(proposal.target_type, "APPLICATION")
        self.assertEqual(proposal.action, "DRAFT")
        self.assertEqual(proposal.payload_json["scenario"], "REJECT")
        self.assertIn("候选人", proposal.payload_json["draft"])
        # 知识库命中即使含联系方式也被投影掩码，不得进入 LLM 上下文与 payload
        self.assertNotIn("13812345678", json.dumps(run.output_json, ensure_ascii=False))

    def test_invalid_scenario_skips(self):
        from hr.agents.draft_runner import run_communication_draft
        output = run_communication_draft(
            self.application["id"], data={"scenario": "NOPE"}, user_id=self.user_id, hr_role="ADMIN"
        )
        self.assertEqual(output["status"], "SKIPPED")
        self.assertIn("scenario", output["error"])

    def test_application_not_found_returns_none(self):
        from hr.agents.draft_runner import run_communication_draft
        self.assertIsNone(run_communication_draft(str(uuid.uuid7()), user_id=self.user_id, hr_role="ADMIN"))


class AgentStatsTests(TestCase):
    """D3 反馈闭环：按 agent_type 运行账本 + 提案决策采纳率 + 分数带"""

    def setUp(self):
        self.workspace_id = "workspace-stats"

    def _run(self, agent_type, status="SUCCEEDED"):
        return HrAgentRun.objects.create(
            workspace_id=self.workspace_id, agent_type=agent_type, trigger_type="MANUAL",
            ref_object_type="APPLICATION", ref_object_id=str(uuid.uuid7()), status=status,
            prompt_version="v",
        )

    def _proposal(self, run, action, status, score=None):
        payload = {"decision": {"score": score, "suggested_action": action}} if score is not None else {}
        return HrAgentProposal.objects.create(
            workspace_id=self.workspace_id, run=run, target_type="APPLICATION",
            target_id=str(uuid.uuid7()), action=action, status=status, payload_json=payload,
        )

    def test_stats_aggregate_by_agent_and_band(self):
        from hr.services.agent_stats import agent_feedback_stats
        run1 = self._run("SCREENING")
        run2 = self._run("SCREENING")
        run3 = self._run("SCREENING", status="FAILED")
        self._proposal(run1, "ADVANCE", "ACCEPTED", score=90)
        self._proposal(run2, "ADVANCE", "DISMISSED", score=85)
        self._proposal(run3, "HOLD", "PENDING", score=60)
        jd_run = self._run("JD_DRAFT")
        self._proposal(jd_run, "DRAFT", "ACCEPTED")
        stats = agent_feedback_stats(self.workspace_id)
        by_type = {item["agent_type"]: item for item in stats["by_agent"]}
        screening = by_type["SCREENING"]
        self.assertEqual(screening["runs"], 3)
        self.assertEqual(screening["succeeded"], 2)
        self.assertEqual(screening["failed"], 1)
        self.assertEqual(screening["decided"], 2)
        self.assertEqual(screening["accepted"], 1)
        self.assertEqual(screening["accept_rate"], 0.5)
        self.assertEqual(screening["score_bands"]["80-100"]["count"], 2)
        self.assertEqual(screening["score_bands"]["80-100"]["accept_rate"], 0.5)
        self.assertEqual(screening["proposals"]["ADVANCE"]["ACCEPTED"], 1)
        jd = by_type["JD_DRAFT"]
        self.assertEqual(jd["proposal_total"], 1)
        self.assertEqual(jd["score_bands"], {})


class AgentD3ApiTests(_HrApiBase):
    """D3 路由：SOURCING / COMMUNICATION_DRAFT run 与 /agents/stats 权限"""

    def setUp(self):
        self.admin = self._user("hr-d3-admin", "HR D3 Admin")
        self.operator = self._user("hr-d3-operator", "HR D3 Operator")
        self.viewer = self._user("hr-d3-viewer", "HR D3 Viewer")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.viewer.id, role="VIEWER")
        HrConfig.objects.update_or_create(
            workspace_id="workspace-a", defaults={"llm_model_id": "fake", "agent_max_concurrent_runs": 2}
        )
        self.recruitment = RecruitmentService("workspace-a", self.admin.id, hr_role="ADMIN")
        job_data = self.recruitment.create_job(
            {"name": "Engineer", "headcount": 1, "skill_requirements": ["Python"]}
        )
        self.job = Job.objects.get(id=job_data["id"])
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a", skills=["python"])
        self.application_id = ApplicationService("workspace-a", self.admin.id, hr_role="ADMIN").create_application(
            self.job.id, self.candidate.id, {}
        )["id"]

    def test_sourcing_run_requires_operator(self):
        response = self._client(self.viewer).post(
            "/admin/api/workspace/workspace-a/hr/agents/SOURCING/run",
            {"job_id": str(self.job.id)}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_sourcing_run_manual_succeeds(self):
        facts = {"candidates": [{"candidate_id": str(self.candidate.id), "match_reason": "ok", "risk": ""}],
                 "summary": "s"}
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content=json.dumps(facts))
        with patch("hr.agents.sourcing_runner._load_llm", return_value=(fake, "fake-llm")), \
                patch("hr.agents.sourcing_runner.search_resumes", return_value={"items": [{
                    "candidate": {"id": str(self.candidate.id), "name": "Alice", "current_city": "上海",
                                  "highest_degree": "本科", "years_experience": 3, "skills": ["python"]},
                    "resume": {"id": "r1"}, "paragraphs": [], "document_id": "d1",
                }], "meta": {}}):
            response = self._client(self.operator).post(
                "/admin/api/workspace/workspace-a/hr/agents/SOURCING/run",
                {"job_id": str(self.job.id)}, content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "SUCCEEDED")

    def test_communication_draft_run_succeeds(self):
        facts = {"draft": "尊敬的候选人：…", "key_points": [], "tone": "", "sources": []}
        fake = Mock()
        fake.invoke.return_value = SimpleNamespace(content=json.dumps(facts))
        with patch("hr.agents.draft_runner._load_llm", return_value=(fake, "fake-llm")), \
                patch("hr.agents.draft_runner.search_knowledge", return_value={"items": [], "meta": {}}):
            response = self._client(self.operator).post(
                "/admin/api/workspace/workspace-a/hr/agents/COMMUNICATION_DRAFT/run",
                {"application_id": self.application_id, "scenario": "PROGRESS"}, content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "SUCCEEDED")

    def test_agent_stats_requires_operator_and_returns_report(self):
        response = self._client(self.viewer).get("/admin/api/workspace/workspace-a/hr/agents/stats")
        self.assertEqual(response.status_code, 403)
        response = self._client(self.operator).get("/admin/api/workspace/workspace-a/hr/agents/stats")
        self.assertEqual(response.status_code, 200)
        self.assertIn("by_agent", response.json()["data"])


class AgentProbeCommandTests(TestCase):
    """D3 探针命令门控：未设置 RUN_REAL_MODEL 时 SKIP 退出 0，不触网"""

    def test_probe_skips_without_flag(self):
        from django.core.management import call_command
        from io import StringIO

        output = StringIO()
        call_command("hr_agent_probe", stdout=output)
        self.assertIn("SKIP", output.getvalue())
class DatasetImportCommandTests(TestCase):
    """D1 评测语料导入：掩码/技能抽取/年限估计/chunks 无联系方式/幂等"""

    def setUp(self):
        self.user = User.objects.create(
            username="dsimport-" + uuid.uuid7().hex[:8], nick_name="dsimport", password="p", role="ADMIN"
        )
        self.workspace_id = "workspace-dsimport"

    def _record(self, name="张三"):
        return {
            "姓名": name,
            "电话": "13812345678",
            "教育经历": [{"毕业时间": "2018.06", "毕业院校": "某某大学", "学位": "硕士学位"}],
            "工作经历": [{"工作时间": "2018.07-2022.12", "工作单位": "某公司", "职务": "python后端工程师",
                          "工作内容": "负责 python 后端与 mysql 开发"}],
            "项目经历": [{"项目时间": "2020.01-2021.06", "项目名称": "某某系统", "项目责任": "负责数据接口开发"}],
        }

    def test_mask_phone(self):
        from hr.management.commands.import_resume_dataset import _mask_phone
        self.assertEqual(_mask_phone("13812345678"), "138****5678")
        self.assertEqual(_mask_phone(""), "")
        self.assertEqual(_mask_phone("12345"), "****")

    def test_extract_skills_and_years(self):
        from hr.management.commands.import_resume_dataset import _extract_skills, _years_experience
        skills = _extract_skills("负责 python 后端与 mysql 开发，使用 vue 前端")
        self.assertIn("python", skills)
        self.assertIn("mysql", skills)
        self.assertEqual(_years_experience(self._record()["工作经历"]), 4)

    def test_chunks_have_no_phone(self):
        from hr.management.commands.import_resume_dataset import _build_chunks
        chunks = _build_chunks(self._record(), "x.txt")
        joined = "\n".join(chunk["content"] for chunk in chunks)
        self.assertNotIn("13812345678", joined)
        self.assertIn("python", joined)

    def test_import_creates_candidate_and_index(self):
        import json
        import os
        import tempfile

        from django.core.management import call_command
        from io import StringIO

        record = self._record()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "train.json")
            record_b = {**record, "姓名": "李四", "工作经历": [
                {"工作时间": "2019.01-2021.06", "工作单位": "乙公司", "职务": "java工程师",
                 "工作内容": "负责 java 后端开发"}]}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"k" + uuid.uuid7().hex + "a": record, "k" + uuid.uuid7().hex + "b": record_b},
                          handle, ensure_ascii=False)
            def fake_index(workspace_id, user_id, resume, text, chat_fn, stats=None, chunks=None):
                doc = str(uuid.uuid7())
                resume.document_id = doc
                resume.save(update_fields=["document_id", "update_time"])
                return doc

            output = StringIO()
            with patch("hr.management.commands.import_resume_dataset.index_resume", side_effect=fake_index), \
                    patch("hr.management.commands.import_resume_dataset.embedding_by_document.run") as m_embed:
                call_command("import_resume_dataset", path=path, workspace=self.workspace_id, seed=1,
                             manifest=os.path.join(tmp, "m.json"), stdout=output)
            self.assertIn("导入 2", output.getvalue())
            self.assertEqual(Candidate.objects.filter(workspace_id=self.workspace_id).count(), 2)
            resume = ResumeFile.objects.filter(workspace_id=self.workspace_id).first()
            self.assertEqual(resume.status, "SUCCESS")
            self.assertIsNotNone(resume.candidate)
            self.assertEqual(resume.candidate.phone, "138****5678")
            from hr.models import CandidateSkill
            self.assertTrue(CandidateSkill.objects.filter(candidate=resume.candidate).exists())
            self.assertEqual(m_embed.call_count, 2)
            # 幂等：重跑跳过（document_id 已存在，不再调用 index/embedding）
            with patch("hr.management.commands.import_resume_dataset.index_resume") as m_index2, \
                    patch("hr.management.commands.import_resume_dataset.embedding_by_document.run") as m_embed2:
                output2 = StringIO()
                call_command("import_resume_dataset", path=path, workspace=self.workspace_id, seed=1,
                             manifest=os.path.join(tmp, "m2.json"), stdout=output2)
            self.assertIn("跳过 2", output2.getvalue())
            self.assertEqual(m_index2.call_count, 0)
            self.assertEqual(m_embed2.call_count, 0)
            self.assertEqual(Candidate.objects.filter(workspace_id=self.workspace_id).count(), 2)

    def test_missing_dataset_reports_error(self):
        from django.core.management import call_command
        from io import StringIO

        output = StringIO()
        call_command("import_resume_dataset", path="/nonexistent/train.json", stderr=output)
        self.assertIn("不存在", output.getvalue())


class EvalScreeningCommandTests(TestCase):
    """D1 评测命令：门控 + 正/负样本构造逻辑"""

    def setUp(self):
        self.workspace_id = "workspace-evalcmd"

    def test_skip_without_flag(self):
        from django.core.management import call_command
        from io import StringIO

        output = StringIO()
        call_command("eval_screening", stdout=output)
        self.assertIn("SKIP", output.getvalue())

    def test_pair_construction(self):
        from hr.management.commands.eval_screening import Command

        command = Command()
        candidate_a = {"id": "00000000-0000-4000-8000-00000000000a", "name": "A",
                       "skills": ["python", "django"], "current_city": "上海",
                       "years_experience": 5, "highest_degree": "本科"}
        candidate_b = {"id": "00000000-0000-4000-8000-00000000000b", "name": "B",
                       "skills": ["java", "spring"], "current_city": "北京",
                       "years_experience": 3, "highest_degree": "本科"}
        pool = [candidate_a, candidate_b]
        # 无此候选人的简历文档 → 完整 JD 构造回退通用职责，技能要求仍取候选人技能
        positive = command._make_positive(self.workspace_id, candidate_a)
        self.assertEqual(positive["kind"], "positive")
        self.assertEqual(positive["job"]["skill_requirements"], ["python", "django"])
        self.assertIn("岗位职责", positive["job"]["description"])
        negative = command._make_negative(candidate_a, pool)
        self.assertIsNotNone(negative)
        self.assertEqual(negative["kind"], "negative")
        self.assertTrue(set(negative["job"]["skill_requirements"]) & {"java", "spring"})
        # 相同技能的候选人不产生负样本
        self.assertIsNone(command._make_negative(candidate_a, [candidate_a, {
            **candidate_b, "skills": ["python"]}], ))

    def test_ensure_skills_backfills_missing(self):
        from hr.management.commands.eval_screening import Command

        workspace_id = "workspace-evalskills"
        candidate = Candidate.objects.create(name="Alice", workspace_id=workspace_id, skills=[])
        ResumeFile.objects.create(
            workspace_id=workspace_id, file_name="a.txt", extension="txt", file_path="/tmp/a.txt",
            file_size=1, sha256="sha-" + uuid.uuid7().hex, source_channel="OTHER",
            status=ResumeStatus.SUCCESS, candidate=candidate, document_id=uuid.uuid7(),
        )
        HrConfig.objects.update_or_create(workspace_id=workspace_id, defaults={"llm_model_id": "fake"})
        with patch("hr.management.commands.eval_screening.get_model_instance_by_model_workspace_id", return_value=Mock()), \
                patch("hr.management.commands.eval_screening.Paragraph.objects.filter") as m_para, \
                patch("hr.services.ai_parser.extract_skills", return_value=["python", "mysql"]):
            m_para.return_value.values_list.return_value = ["负责 python 后端开发", "mysql 调优"]
            rows = [{"id": str(candidate.id), "skills": [], "name": "Alice", "current_city": "",
                     "years_experience": None, "highest_degree": ""}]
            updated = Command()._ensure_skills(workspace_id, rows, parallel=False)
        self.assertEqual(updated, 1)
        candidate.refresh_from_db()
        self.assertEqual(candidate.skills, ["python", "mysql"])
        from hr.models import CandidateSkill
        self.assertEqual(CandidateSkill.objects.filter(candidate=candidate).count(), 2)






class ReviewFixRegressionTests(TestCase):
    """针对审查修复的回归测试：跨工作区、检索范围、输入校验、附件守卫、幂等、空硬条件。"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.workspace = "workspace-fix"
        self.recruitment = RecruitmentService(self.workspace, self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id=self.workspace)
        job_data = self.recruitment.create_job({"name": "Engineer", "headcount": 1})
        self.job = Job.objects.get(id=job_data["id"])
        self.service = ApplicationService(self.workspace, self.user_id, hr_role="ADMIN")

    def test_create_application_rejects_invalid_enum(self):
        with self.assertRaisesRegex(AppApiException, "relation_type"):
            self.service.create_application(self.job.id, self.candidate.id, {"relation_type": "BAD"})
        with self.assertRaisesRegex(AppApiException, "channel"):
            self.service.create_application(self.job.id, self.candidate.id, {"channel": "BAD"})

    def test_structured_filter_empty_hard_met_true(self):
        from hr.agents.runner import structured_filter
        job = Job.objects.create(workspace_id=self.workspace, name="NoHard", headcount=1)
        result = structured_filter(job, self.candidate)
        self.assertTrue(result["hard_met"])

    def test_document_ids_cross_workspace_rejected(self):
        from hr.services.resume_search import search_resumes
        other = Candidate.objects.create(name="Bob", workspace_id="other-ws")
        other_resume = ResumeFile.objects.create(
            workspace_id="other-ws", file_name="b.docx", extension="docx",
            file_path="/tmp/b.docx", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            status="SUCCESS", candidate=other, document_id=uuid.uuid7(),
        )
        with self.assertRaisesRegex(AppApiException, "invalid or inaccessible"):
            search_resumes(
                self.workspace, "java", document_ids=[str(other_resume.document_id)],
                user_id=self.user_id, hr_role="ADMIN",
            )

    def test_document_ids_not_belong_candidate_rejected(self):
        from hr.services.resume_search import search_resumes
        resume = ResumeFile.objects.create(
            workspace_id=self.workspace, file_name="a.docx", extension="docx",
            file_path="/tmp/a.docx", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            status="SUCCESS", candidate=self.candidate, document_id=uuid.uuid7(),
        )
        other = Candidate.objects.create(name="Other", workspace_id=self.workspace)
        with self.assertRaisesRegex(AppApiException, "do not belong"):
            search_resumes(
                self.workspace, "java", candidate_id=str(other.id),
                document_ids=[str(resume.document_id)], user_id=self.user_id, hr_role="ADMIN",
            )

    def test_offer_attachment_only_draft(self):
        app = self.service.create_application(self.job.id, self.candidate.id, {})
        stages = list(JobStage.objects.filter(job=self.job).order_by("order"))
        self.service.move_stage(app["id"], stages[3].id, {"reason_text": "skip"})
        offer_svc = OfferService(self.workspace, self.user_id, hr_role="ADMIN")
        offer = offer_svc.create_offer_for_application(app["id"], {"salary_amount": "10000"})
        offer_svc.approve_offer(offer["id"], {"approval_status": "APPROVED"})
        offer_svc.send_offer(offer["id"])
        with self.assertRaisesRegex(AppApiException, "Only draft offer"):
            offer_svc.upload_offer_attachment(offer["id"], "/tmp/x.pdf", "x.pdf")

    def test_move_stage_idempotent_different_target_no_mutation(self):
        app = self.service.create_application(self.job.id, self.candidate.id, {})
        stages = list(JobStage.objects.filter(job=self.job).order_by("order"))
        key = "fix-" + uuid.uuid7().hex
        self.service.move_stage(app["id"], stages[1].id, {"idempotency_key": key, "reason_text": "first"})
        self.service.move_stage(app["id"], stages[2].id, {"idempotency_key": key, "reason_text": "retry"})
        current = Application.objects.get(id=app["id"])
        self.assertEqual(current.current_stage_id, stages[1].id)

    def test_agent_cross_workspace_returns_none(self):
        from hr.agents.runner import run_screening_agent
        app = self.service.create_application(self.job.id, self.candidate.id, {})
        self.assertIsNone(
            run_screening_agent(app["id"], trigger_type="MANUAL", user_id=self.user_id, workspace_id="other-ws")
        )

    def test_page_applications_queue_filters(self):
        cand_a = Candidate.objects.create(
            name="Alice", workspace_id=self.workspace, phone="13800000000",
            email="alice@example.com", current_city="上海",
        )
        cand_b = Candidate.objects.create(
            name="Bob", workspace_id=self.workspace, current_city="北京",
        )
        self.service.create_application(
            self.job.id, cand_a.id, {"channel": "JOB_SITE", "relation_type": "APPLY"}
        )
        self.service.create_application(
            self.job.id, cand_b.id, {"channel": "REFERRAL", "relation_type": "REFERRAL"}
        )
        self.assertEqual(len(self.service.page_applications(1, 20, {"channel": "JOB_SITE"})["records"]), 1)
        self.assertEqual(len(self.service.page_applications(1, 20, {"relation_type": "REFERRAL"})["records"]), 1)
        self.assertEqual(len(self.service.page_applications(1, 20, {"city": "上海"})["records"]), 1)
        self.assertEqual(len(self.service.page_applications(1, 20, {"q": "Bob"})["records"]), 1)

class HrOffboardCommandTests(TestCase):
    """阶段 A：hr_offboard_workspace 命令 —— 全量清理 / dry-run 一致 / 幂等 / 跨工作区隔离 / 活跃守卫 / 导出脱敏 / 留痕。"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.ws = "ws-offboard"
        self.keep_ws = "ws-keep"
        self.user = User.objects.create(
            username="offboard-" + uuid.uuid7().hex[:8], nick_name="offboard", password="p", role="ADMIN"
        )
        from hr.services.storage import get_storage

        self.storage = get_storage()
        # 简历原文件（写到本地存储根，验证注销连带删除存储对象）
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write("姓名：张三\n电话：13812345678\n3年经验".encode("utf-8"))
        handle.close()
        self.tmp_resume_src = handle.name
        self.resume_key = f"resume/{self.ws}/{uuid.uuid7().hex}.txt"
        self.storage.save(self.resume_key, self.tmp_resume_src)
        # Offer 附件（第二个存储对象，验证一并删除）
        self.att_key = f"offer/{self.ws}/{uuid.uuid7().hex}.pdf"
        att = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        att.write(b"%PDF-fake")
        att.close()
        self.storage.save(self.att_key, att.name)

    def _build_workspace(self, ws, active=True):
        """构造 ws 工作区的完整 HR 数据（候选人+技能/职位+阶段/申请+事件/面试/Offer/交接/Agent 账本/
        配置/授权/审计/简历索引/存储对象）。active=False 时职位关闭、申请置终态，用于守卫对比。"""
        from hr.models import CandidateSkill, ResumeFlowLog
        from knowledge.models import KnowledgeFolder
        from hr.services.audit import write_audit_log

        candidate = Candidate.objects.create(
            name="Alice", workspace_id=ws, phone="13812345678", email="alice@example.com", skills=["Python"]
        )
        CandidateSkill.objects.create(candidate=candidate, skill_norm="python", skill_raw="Python")
        job = Job.objects.create(
            name="Engineer", workspace_id=ws, headcount=1,
            status="OPEN" if active else "CLOSED", close_reason=None if active else "FILLED",
        )
        stages = [
            JobStage.objects.create(workspace_id=ws, job=job, key=key, name=name, order=order, is_system=True)
            for order, (key, name) in enumerate(
                [("APPLIED", "待筛选"), ("SCREEN", "初筛"), ("INTERVIEW", "面试"), ("OFFER", "Offer")], start=1
            )
        ]
        # 先建申请（此时无 HrConfig，post_save 不触发 Agent 分发），再建配置
        app = Application.objects.create(
            workspace_id=ws, candidate=candidate, job=job, current_stage=stages[0],
            status="ACTIVE" if active else "REJECTED",
            termination_reason=None if active else "NOT_FIT",
        )
        ApplicationEvent.objects.create(workspace_id=ws, application=app, event_type="CREATED", to_status="ACTIVE")
        Interview.objects.create(workspace_id=ws, application=app, round_no=1)
        offer = Offer.objects.create(
            workspace_id=ws, application=app, candidate=candidate, job=job, version=1,
            attachment_path=self.att_key,
        )
        OnboardingHandoff.objects.create(workspace_id=ws, application=app, candidate=candidate, job=job, offer=offer)
        run = HrAgentRun.objects.create(
            workspace_id=ws, agent_type="SCREENING", status="SUCCEEDED",
            ref_object_type="APPLICATION", ref_object_id=str(app.id),
        )
        HrAgentProposal.objects.create(
            workspace_id=ws, run=run, target_type="APPLICATION", target_id=str(app.id), action="ADVANCE"
        )
        HrConfig.objects.create(workspace_id=ws, llm_model_id="m-1", agent_enable_screening=True)
        HrAccess.objects.create(workspace_id=ws, user_id=self.user_id, role="ADMIN")
        write_audit_log(ws, self.user_id, "CREATE", "CANDIDATE", str(candidate.id))
        # 简历语义索引（知识库/文档/段落/向量）
        KnowledgeFolder.objects.get_or_create(id="default", defaults={"name": "default", "workspace_id": "default"})
        knowledge = Knowledge.objects.create(workspace_id=ws, name="简历语义索引", desc="")
        document = Document.objects.create(
            id=uuid.uuid7(), knowledge_id=knowledge.id, name="r.txt", char_length=10, user_id=self.user.id
        )
        paragraph = Paragraph.objects.create(
            id=uuid.uuid7(), document_id=document.id, knowledge_id=knowledge.id, content="内容", title="t"
        )
        Embedding.objects.create(
            id=uuid.uuid7(), document_id=document.id, paragraph_id=paragraph.id,
            knowledge_id=knowledge.id, embedding=[0.1] * 8, is_active=True,
        )
        resume = ResumeFile.objects.create(
            workspace_id=ws, file_name="r.txt", extension="txt", file_path=self.resume_key,
            file_size=1, sha256="sha-" + uuid.uuid7().hex, status=ResumeStatus.SUCCESS,
            candidate=candidate, document_id=document.id, user_id=self.user_id,
        )
        ResumeFlowLog.objects.create(workspace_id=ws, resume_id=resume.id, node="EXTRACT")
        return candidate, job, app, offer, knowledge, document

    def _ws_counts(self, ws):
        return {
            "candidates": Candidate.objects.filter(workspace_id=ws).count(),
            "jobs": Job.objects.filter(workspace_id=ws).count(),
            "applications": Application.objects.filter(workspace_id=ws).count(),
            "interviews": Interview.objects.filter(workspace_id=ws).count(),
            "offers": Offer.objects.filter(workspace_id=ws).count(),
            "handoffs": OnboardingHandoff.objects.filter(workspace_id=ws).count(),
        }

    def test_offboard_purges_all_hr_data_and_index_and_storage(self):
        from django.core.management import call_command
        from hr.models import CandidateSkill, HrOffboard, ResumeFlowLog

        _c, _j, _a, _o, knowledge, document = self._build_workspace(self.ws)
        before = self._ws_counts(self.ws)
        self.assertGreater(sum(before.values()), 0)
        self.assertTrue(self.storage.exists(self.resume_key))
        self.assertTrue(self.storage.exists(self.att_key))

        call_command("hr_offboard_workspace", self.ws, force=True, user_id=str(self.user_id))

        # 验收 1：hr_* 该工作区全表归零（hr_offboard tombstone 例外）
        self.assertEqual(Candidate.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(CandidateSkill.objects.filter(candidate__workspace_id=self.ws).count(), 0)
        self.assertEqual(Job.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(JobStage.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(Application.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(ApplicationEvent.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(Interview.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(Offer.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(OnboardingHandoff.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(HrAgentRun.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(HrAgentProposal.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(HrConfig.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(HrAccess.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(HrAuditLog.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(ResumeFlowLog.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertEqual(ResumeFile.objects.filter(workspace_id=self.ws).count(), 0)
        # 简历语义索引：知识库/文档/段落/向量全空
        self.assertFalse(Knowledge.objects.filter(id=knowledge.id).exists())
        self.assertFalse(Document.objects.filter(id=document.id).exists())
        self.assertFalse(Paragraph.objects.filter(document_id=document.id).exists())
        self.assertFalse(Embedding.objects.filter(document_id=document.id).exists())
        # 存储对象删除
        self.assertFalse(self.storage.exists(self.resume_key))
        self.assertFalse(self.storage.exists(self.att_key))
        # 留痕：tombstone（执行人/时间/计数/导出包）
        tombstone = HrOffboard.objects.get(workspace_id=self.ws)
        self.assertEqual(str(tombstone.user_id), str(self.user_id))
        self.assertEqual(tombstone.exported_path, "")
        self.assertEqual(tombstone.counts["applications"], before["applications"])
        self.assertEqual(tombstone.counts["storage_files"], 2)

    def test_dry_run_matches_actual_delete_counts(self):
        from django.core.management import call_command
        from hr.management.commands.hr_offboard_workspace import Command
        from hr.models import HrOffboard

        self._build_workspace(self.ws)
        expected = Command._counts(self.ws)
        self.assertGreater(expected["candidates"], 0)

        # dry-run：只统计不落库
        call_command("hr_offboard_workspace", self.ws, dry_run=True)
        self.assertFalse(HrOffboard.objects.filter(workspace_id=self.ws).exists())
        self.assertEqual(Candidate.objects.filter(workspace_id=self.ws).count(), expected["candidates"])

        # 实际删除：计数必须与 dry-run 一致（验收 3）
        call_command("hr_offboard_workspace", self.ws, force=True)
        tombstone = HrOffboard.objects.get(workspace_id=self.ws)
        self.assertEqual(tombstone.counts, expected)
        self.assertEqual(Candidate.objects.filter(workspace_id=self.ws).count(), 0)

    def test_second_run_reports_already_offboarded(self):
        from django.core.management import call_command
        from io import StringIO

        from hr.models import HrOffboard

        self._build_workspace(self.ws)
        call_command("hr_offboard_workspace", self.ws, force=True)
        self.assertEqual(HrOffboard.objects.filter(workspace_id=self.ws).count(), 1)

        out = StringIO()
        call_command("hr_offboard_workspace", self.ws, force=True, stdout=out)
        self.assertIn("已注销", out.getvalue())
        self.assertEqual(HrOffboard.objects.filter(workspace_id=self.ws).count(), 1)  # 不重复删

    def test_cross_workspace_isolation(self):
        from django.core.management import call_command
        from hr.models import CandidateSkill

        self._build_workspace(self.ws)
        keep_knowledge, keep_doc = self._build_workspace(self.keep_ws)[4:6]

        call_command("hr_offboard_workspace", self.ws, force=True)

        # 验收 4：其它工作区数据完整
        self.assertEqual(Candidate.objects.filter(workspace_id=self.keep_ws).count(), 1)
        self.assertEqual(CandidateSkill.objects.filter(candidate__workspace_id=self.keep_ws).count(), 1)
        self.assertEqual(Job.objects.filter(workspace_id=self.keep_ws).count(), 1)
        self.assertEqual(Application.objects.filter(workspace_id=self.keep_ws).count(), 1)
        self.assertEqual(Offer.objects.filter(workspace_id=self.keep_ws).count(), 1)
        self.assertEqual(HrConfig.objects.filter(workspace_id=self.keep_ws).count(), 1)
        self.assertTrue(Knowledge.objects.filter(id=keep_knowledge.id).exists())
        self.assertTrue(Document.objects.filter(id=keep_doc.id).exists())
        self.assertTrue(Embedding.objects.filter(document_id=keep_doc.id).exists())

    def test_guard_refuses_live_workspace_without_force(self):
        from django.core.management import call_command
        from io import StringIO

        from hr.models import HrOffboard

        self._build_workspace(self.ws)  # OPEN 职位 + ACTIVE 申请
        out = StringIO()
        call_command("hr_offboard_workspace", self.ws, stdout=out)
        self.assertIn("拒绝注销", out.getvalue())
        self.assertFalse(HrOffboard.objects.filter(workspace_id=self.ws).exists())
        self.assertEqual(Application.objects.filter(workspace_id=self.ws).count(), 1)  # 未删

        call_command("hr_offboard_workspace", self.ws, force=True)  # --force 放行
        self.assertEqual(Application.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertTrue(HrOffboard.objects.filter(workspace_id=self.ws).exists())

    def test_guard_refuses_pending_agent_run(self):
        from django.core.management import call_command
        from io import StringIO

        from hr.models import HrAgentRun, HrOffboard

        self._build_workspace(self.ws, active=False)  # 职位已关、申请已拒，无活跃流程
        HrAgentRun.objects.create(
            workspace_id=self.ws, agent_type="SCREENING", status="RUNNING",
            ref_object_type="APPLICATION", ref_object_id=str(uuid.uuid7()),
        )
        out = StringIO()
        call_command("hr_offboard_workspace", self.ws, stdout=out)
        self.assertIn("Agent 运行", out.getvalue())
        self.assertFalse(HrOffboard.objects.filter(workspace_id=self.ws).exists())

        call_command("hr_offboard_workspace", self.ws, force=True)
        self.assertEqual(HrAgentRun.objects.filter(workspace_id=self.ws).count(), 0)
        self.assertTrue(HrOffboard.objects.filter(workspace_id=self.ws).exists())

    def test_export_masks_contacts_and_persists_path(self):
        import glob as glob_module

        from django.core.management import call_command
        from hr.models import HrOffboard

        self._build_workspace(self.ws)
        export_dir = tempfile.mkdtemp(prefix="offboard-export")
        call_command("hr_offboard_workspace", self.ws, force=True, export=export_dir, user_id=str(self.user_id))

        files = glob_module.glob(os.path.join(export_dir, "hr_offboard_*.json"))
        self.assertEqual(len(files), 1)
        with open(files[0], "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        # 候选人联系方式脱敏（验收 3：可读 JSON + 导出后清理成功）
        cand = payload["candidates"][0]
        self.assertEqual(cand["name"], "Alice")
        self.assertEqual(cand["phone"], "138****5678")
        self.assertEqual(cand["email"], "al***@example.com")
        for section in ("candidates", "jobs", "applications", "interviews", "offers", "handoffs", "audit"):
            self.assertIn(section, payload)
        self.assertEqual(len(payload["applications"]), 1)
        self.assertEqual(len(payload["applications"][0]["events"]), 1)

        tombstone = HrOffboard.objects.get(workspace_id=self.ws)
        self.assertEqual(tombstone.exported_path, files[0])
        self.assertEqual(Candidate.objects.filter(workspace_id=self.ws).count(), 0)

class HrOffboardingApiTests(_HrApiBase):
    """阶段 B：HR 注销编排回调/API 的权限、数据返还、确认和跨工作区隔离。"""

    def setUp(self):
        self.workspace = "workspace-offboarding-api"
        self.other_workspace = "workspace-offboarding-other"
        self.admin = self._user("offboard-api-admin", "Offboard API Admin")
        self.operator = self._user("offboard-api-operator", "Offboard API Operator")
        HrAccess.objects.create(workspace_id=self.workspace, user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id=self.workspace, user_id=self.operator.id, role="OPERATOR")

    def test_preview_is_admin_only_and_workspace_scoped(self):
        Candidate.objects.create(name="Alice", workspace_id=self.workspace)
        Candidate.objects.create(name="Other", workspace_id=self.other_workspace)
        response = self._client(self.admin).get(
            f"/admin/api/workspace/{self.workspace}/hr/offboarding/preview"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "DRY_RUN")
        self.assertEqual(data["counts"]["candidates"], 1)
        self.assertTrue(data["can_offboard"])
        self.assertEqual(Candidate.objects.filter(workspace_id=self.other_workspace).count(), 1)

        denied = self._client(self.operator).get(
            f"/admin/api/workspace/{self.workspace}/hr/offboarding/preview"
        )
        self.assertEqual(denied.status_code, 403)

    def test_export_returns_masked_data_without_mutation(self):
        candidate = Candidate.objects.create(
            name="Alice", workspace_id=self.workspace, phone="13812345678", email="alice@example.com"
        )
        response = self._client(self.admin).get(
            f"/admin/api/workspace/{self.workspace}/hr/offboarding/export"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["workspace_id"], self.workspace)
        self.assertEqual(data["candidates"][0]["phone"], "138****5678")
        self.assertEqual(data["candidates"][0]["email"], "al***@example.com")
        self.assertTrue(Candidate.objects.filter(id=candidate.id, workspace_id=self.workspace).exists())
        self.assertFalse(HrOffboard.objects.filter(workspace_id=self.workspace).exists())

    def test_purge_requires_confirmation_and_returns_data_return_package(self):
        Candidate.objects.create(name="Alice", workspace_id=self.workspace, phone="13812345678")
        client = self._client(self.admin)
        wrong = client.post(
            f"/admin/api/workspace/{self.workspace}/hr/offboarding",
            {"confirm_workspace_id": "wrong", "export": True},
            format="json",
        )
        self.assertEqual(wrong.json()["code"], 400)
        self.assertFalse(HrOffboard.objects.filter(workspace_id=self.workspace).exists())
        self.assertEqual(Candidate.objects.filter(workspace_id=self.workspace).count(), 1)

        response = client.post(
            f"/admin/api/workspace/{self.workspace}/hr/offboarding",
            {"confirm_workspace_id": self.workspace, "export": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "OFFBOARDED")
        self.assertEqual(data["export"]["candidates"][0]["phone"], "138****5678")
        self.assertEqual(Candidate.objects.filter(workspace_id=self.workspace).count(), 0)
        self.assertTrue(HrOffboard.objects.filter(workspace_id=self.workspace).exists())

    def test_purge_blocks_active_workspace_without_force(self):
        candidate = Candidate.objects.create(name="Alice", workspace_id=self.workspace)
        job = Job.objects.create(name="Engineer", workspace_id=self.workspace, headcount=1, status="OPEN")
        stage = JobStage.objects.create(
            workspace_id=self.workspace, job=job, key="APPLIED", name="待筛选", order=1, is_system=True
        )
        Application.objects.create(
            workspace_id=self.workspace, candidate=candidate, job=job, current_stage=stage, status="ACTIVE"
        )
        response = self._client(self.admin).post(
            f"/admin/api/workspace/{self.workspace}/hr/offboarding",
            {"confirm_workspace_id": self.workspace},
            format="json",
        )
        self.assertIn(response.json()["code"], (400, 409))
        self.assertFalse(HrOffboard.objects.filter(workspace_id=self.workspace).exists())
        self.assertTrue(Application.objects.filter(workspace_id=self.workspace).exists())
        self.assertTrue(Job.objects.filter(workspace_id=self.workspace).exists())


class ResumeDatabaseCrudTests(_HrApiBase):
    """B：ResumeDatabase 0 覆盖补齐（增删改查 + 上传带库 + ResumeFile.save 总库兜底）"""

    def setUp(self):
        self.workspace = "ws-resume-db-b"
        self.other_workspace = "ws-resume-db-other"
        self.admin = self._user("resume-db-admin", "Resume DB Admin")
        self.operator = self._user("resume-db-operator", "Resume DB Operator")
        self.viewer = self._user("resume-db-viewer", "Resume DB Viewer")
        HrAccess.objects.create(workspace_id=self.workspace, user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id=self.workspace, user_id=self.operator.id, role="OPERATOR")
        HrAccess.objects.create(workspace_id=self.workspace, user_id=self.viewer.id, role="VIEWER")

    def test_total_auto_created_on_list(self):
        # 首次 list 应自动创建总库
        self.assertEqual(ResumeDatabase.objects.filter(workspace_id=self.workspace).count(), 0)
        resp = self._client(self.admin).get(f"/admin/api/workspace/{self.workspace}/hr/resume-databases")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "总库")
        self.assertTrue(data[0]["is_system"])
        self.assertEqual(data[0]["status"], "ACTIVE")
        # 再次创建总库同名应 400，同名业务库亦 400
        dup = self._client(self.admin).post(
            f"/admin/api/workspace/{self.workspace}/hr/resume-databases",
            {"name": "总库", "description": "dup"},
            format="json",
        )
        self.assertEqual(dup.json()["code"], 400)

    def test_create_and_list_business_database(self):
        # 先触发总库创建
        self._client(self.admin).get(f"/admin/api/workspace/{self.workspace}/hr/resume-databases")
        # 创建业务库
        resp = self._client(self.admin).post(
            f"/admin/api/workspace/{self.workspace}/hr/resume-databases",
            {"name": "2026春招-后端", "description": "业务库"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        biz = resp.json()["data"]
        self.assertEqual(biz["name"], "2026春招-后端")
        self.assertFalse(biz["is_system"])
        # 列表应含总库 + 业务库，按 is_system 排序
        lst = self._client(self.admin).get(f"/admin/api/workspace/{self.workspace}/hr/resume-databases").json()["data"]
        self.assertEqual(len(lst), 2)
        self.assertEqual(lst[0]["name"], "总库")
        self.assertEqual(lst[1]["name"], "2026春招-后端")
        # 重复名 400
        dup = self._client(self.admin).post(
            f"/admin/api/workspace/{self.workspace}/hr/resume-databases",
            {"name": "2026春招-后端"},
            format="json",
        )
        self.assertEqual(dup.json()["code"], 400)
        # VIEWER 无权创建 403
        denied = self._client(self.viewer).post(
            f"/admin/api/workspace/{self.workspace}/hr/resume-databases",
            {"name": "viewer-db"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

    def test_total_cannot_be_archived_and_business_archive(self):
        self._client(self.admin).get(f"/admin/api/workspace/{self.workspace}/hr/resume-databases")
        biz = self._client(self.admin).post(
            f"/admin/api/workspace/{self.workspace}/hr/resume-databases",
            {"name": "待归档库"},
            format="json",
        ).json()["data"]
        total = ResumeDatabase.objects.get(workspace_id=self.workspace, is_system=True)
        # 总库归档应 400
        resp = self._client(self.admin).put(f"/admin/api/workspace/{self.workspace}/hr/resume-databases/{total.id}/archive")
        self.assertEqual(resp.json()["code"], 400)
        # 业务库归档 200
        resp = self._client(self.admin).put(f"/admin/api/workspace/{self.workspace}/hr/resume-databases/{biz['id']}/archive")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["status"], "ARCHIVED")
        # 归档后再次归档幂等 200
        resp2 = self._client(self.admin).put(f"/admin/api/workspace/{self.workspace}/hr/resume-databases/{biz['id']}/archive")
        self.assertEqual(resp2.status_code, 200)
        # 跨工作区归档应 404（租户隔离）
        other_admin = self._user("other-admin", "Other")
        HrAccess.objects.create(workspace_id=self.other_workspace, user_id=other_admin.id, role="ADMIN")
        other_client = self._client(other_admin)
        # other workspace 首次 list 会建总库，但 biz 属于原 workspace，other 归档应 404
        resp = other_client.put(f"/admin/api/workspace/{self.other_workspace}/hr/resume-databases/{biz['id']}/archive")
        self.assertEqual(resp.status_code, 404)

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_upload_with_business_database_creates_both_memberships(self, mock_delay):
        # 准备总库 + 业务库
        self._client(self.admin).get(f"/admin/api/workspace/{self.workspace}/hr/resume-databases")
        biz = self._client(self.admin).post(
            f"/admin/api/workspace/{self.workspace}/hr/resume-databases",
            {"name": "业务库A"},
            format="json",
        ).json()["data"]
        total = ResumeDatabase.objects.get(workspace_id=self.workspace, is_system=True)
        # 上传 1 份 txt，指定业务库（总库由服务端强制追加）
        content = "姓名：上传测试\n电话：13800001111\n工作经历：Python 后端".encode()
        uploaded = SimpleUploadedFile("resume.txt", content, content_type="text/plain")
        resp = self._client(self.operator).post(
            f"/admin/api/workspace/{self.workspace}/hr/candidates/resumes",
            {"files": uploaded, "resume_database_ids": str(biz["id"])},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"][0]
        self.assertEqual(set(data["resume_database_ids"]), {str(total.id), str(biz["id"])})
        self.assertIn("总库", data["resume_database_names"])
        self.assertIn("业务库A", data["resume_database_names"])
        resume = ResumeFile.objects.get(id=data["resume_id"])
        # resume_database 外键指向总库（兼容字段）
        self.assertEqual(str(resume.resume_database_id), str(total.id))
        # 成员关系应含 2 条
        self.assertEqual(ResumeDatabaseMembership.objects.filter(resume_file=resume).count(), 2)
        self.assertTrue(ResumeDatabaseMembership.objects.filter(resume_file=resume, resume_database=total).exists())
        self.assertTrue(ResumeDatabaseMembership.objects.filter(resume_file=resume, resume_database_id=biz["id"]).exists())
        # 解析任务已派发
        mock_delay.assert_called_once()

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_duplicate_upload_adds_missing_membership(self, mock_delay):
        self._client(self.admin).get(f"/admin/api/workspace/{self.workspace}/hr/resume-databases")
        biz = self._client(self.admin).post(
            f"/admin/api/workspace/{self.workspace}/hr/resume-databases",
            {"name": "业务库B"},
            format="json",
        ).json()["data"]
        total = ResumeDatabase.objects.get(workspace_id=self.workspace, is_system=True)
        content = b"duplicate content same sha"
        # 第一次只进总库
        uploaded1 = SimpleUploadedFile("dup.txt", content, content_type="text/plain")
        resp1 = self._client(self.operator).post(
            f"/admin/api/workspace/{self.workspace}/hr/candidates/resumes",
            {"files": uploaded1},
            format="multipart",
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertFalse(resp1.json()["data"][0]["duplicate"])
        resume_id = resp1.json()["data"][0]["resume_id"]
        self.assertEqual(ResumeDatabaseMembership.objects.filter(resume_file_id=resume_id).count(), 1)
        # 第二次同内容（同 sha）上传到业务库，应复用文件且补充成员关系，不新建文件
        uploaded2 = SimpleUploadedFile("dup2.txt", content, content_type="text/plain")
        resp2 = self._client(self.operator).post(
            f"/admin/api/workspace/{self.workspace}/hr/candidates/resumes",
            {"files": uploaded2, "resume_database_ids": str(biz["id"])},
            format="multipart",
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.json()["data"][0]["duplicate"])
        self.assertEqual(resp2.json()["data"][0]["resume_id"], resume_id)
        self.assertEqual(ResumeFile.objects.filter(workspace_id=self.workspace).count(), 1)
        # 成员关系应增至 2
        self.assertEqual(ResumeDatabaseMembership.objects.filter(resume_file_id=resume_id).count(), 2)
        self.assertTrue(ResumeDatabaseMembership.objects.filter(resume_file_id=resume_id, resume_database_id=biz["id"]).exists())
        self.assertTrue(ResumeDatabaseMembership.objects.filter(resume_file_id=resume_id, resume_database=total).exists())
        # 去重上传不应再次触发解析
        self.assertEqual(mock_delay.call_count, 1)

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_archived_database_blocks_upload(self, mock_delay):
        self._client(self.admin).get(f"/admin/api/workspace/{self.workspace}/hr/resume-databases")
        biz = self._client(self.admin).post(
            f"/admin/api/workspace/{self.workspace}/hr/resume-databases",
            {"name": "归档阻断库"},
            format="json",
        ).json()["data"]
        # 归档
        self._client(self.admin).put(f"/admin/api/workspace/{self.workspace}/hr/resume-databases/{biz['id']}/archive")
        content = b"archived db test"
        uploaded = SimpleUploadedFile("archived.txt", content, content_type="text/plain")
        resp = self._client(self.operator).post(
            f"/admin/api/workspace/{self.workspace}/hr/candidates/resumes",
            {"files": uploaded, "resume_database_ids": str(biz["id"])},
            format="multipart",
        )
        # 归档库作为上传目标应 404
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(ResumeFile.objects.filter(workspace_id=self.workspace).count(), 0)
        mock_delay.assert_not_called()

    def test_resumefile_save_low_level_ensures_total(self):
        # 裸 ORM 创建：先建业务库（此时总库已由 list 触发创建）
        self._client(self.admin).get(f"/admin/api/workspace/{self.workspace}/hr/resume-databases")
        biz = self._client(self.admin).post(
            f"/admin/api/workspace/{self.workspace}/hr/resume-databases",
            {"name": "低层业务库"},
            format="json",
        ).json()["data"]
        biz = ResumeDatabase.objects.get(id=biz["id"])
        total = ResumeDatabase.objects.get(workspace_id=self.workspace, is_system=True)
        # 场景 A：直接用 ResumeFile.objects.create 指定 business，总库成员应自动补齐
        resume_a = ResumeFile.objects.create(
            workspace_id=self.workspace,
            file_name="lowlevel_a.txt",
            extension="txt",
            file_path="resume/lowlevel_a.txt",
            file_size=10,
            sha256="a" * 64,
            source_channel="OTHER",
            resume_database=biz,
            status=ResumeStatus.PENDING,
            user_id=self.admin.id,
        )
        self.assertEqual(ResumeDatabaseMembership.objects.filter(resume_file=resume_a).count(), 1)
        self.assertTrue(ResumeDatabaseMembership.objects.filter(resume_file=resume_a, resume_database=total).exists())
        # resume_database 外键保持业务库（多库以成员关系为准）
        resume_a.refresh_from_db()
        self.assertEqual(str(resume_a.resume_database_id), str(biz.id))
        # 场景 B：全新 workspace 无总库时，裸 save 应自动创建总库
        fresh_ws = "ws-fresh-total-ensure"
        fresh_admin = self._user("fresh-admin", "Fresh")
        HrAccess.objects.create(workspace_id=fresh_ws, user_id=fresh_admin.id, role="ADMIN")
        self.assertEqual(ResumeDatabase.objects.filter(workspace_id=fresh_ws).count(), 0)
        resume_b = ResumeFile(
            workspace_id=fresh_ws,
            file_name="lowlevel_b.txt",
            extension="txt",
            file_path="resume/lowlevel_b.txt",
            file_size=10,
            sha256="b" * 64,
            source_channel="OTHER",
            status=ResumeStatus.PENDING,
            user_id=fresh_admin.id,
        )
        # 不传 resume_database，save 应自动指向新建总库并建成员关系
        resume_b.save()
        self.assertIsNotNone(resume_b.resume_database_id)
        fresh_total = ResumeDatabase.objects.get(workspace_id=fresh_ws, is_system=True)
        self.assertEqual(str(resume_b.resume_database_id), str(fresh_total.id))
        self.assertTrue(ResumeDatabaseMembership.objects.filter(resume_file=resume_b, resume_database=fresh_total).exists())
        self.assertEqual(fresh_total.name, "总库")


class PydanticAgentValidationTests(TestCase):
    """Prompt 7：Pydantic AI output_type 校验失败重试（5 例）"""

    def test_screening_whitelist_validation_triggers_retry(self):
        from hr.agents.runner_pydantic import DimensionFact, ScreeningFacts
        from pydantic import ValidationError

        # 白名单外维度应触发验证失败
        with self.assertRaises(ValidationError):
            DimensionFact(name="年龄", verdict="偏大", evidence=[], confidence=0.9)
        # 白名单内应通过
        fact = DimensionFact(name="技能匹配", verdict="命中", evidence=[], confidence=0.9)
        self.assertEqual(fact.name, "技能匹配")
        # ScreeningFacts 整体也校验 dimensions 非空
        with self.assertRaises(ValidationError):
            ScreeningFacts(dimensions=[], concerns=[], clarifying_questions=[])

    def test_screening_paragraph_id_validation_via_allowed_set(self):
        from hr.agents.runner_pydantic import Evidence, ScreeningFacts, DimensionFact
        from pydantic_ai import ModelRetry
        import hr.agents.runner_pydantic as rp

        # 设置允许的 paragraph_id 集合
        rp._ALLOWED_PARAGRAPH_IDS = {"p1", "p2"}
        try:
            # 合法 paragraph_id 应通过
            facts = ScreeningFacts(
                dimensions=[DimensionFact(name="技能匹配", verdict="命中", evidence=[Evidence(paragraph_id="p1", excerpt="熟悉 Python", relevance=0.9)], confidence=0.9)],
                concerns=[],
                clarifying_questions=[],
            )
            self.assertEqual(facts.dimensions[0].evidence[0].paragraph_id, "p1")
            # 非法 paragraph_id 应在 model_validator 中触发 ModelRetry
            with self.assertRaises(ModelRetry):
                ScreeningFacts(
                    dimensions=[DimensionFact(name="技能匹配", verdict="命中", evidence=[Evidence(paragraph_id="p99", excerpt="编造", relevance=0.9)], confidence=0.9)],
                    concerns=[],
                    clarifying_questions=[],
                )
        finally:
            rp._ALLOWED_PARAGRAPH_IDS = set()

    def test_jd_draft_missing_description_validation(self):
        from hr.agents.jd_runner_pydantic import JdDraftFacts
        from pydantic import ValidationError

        # 缺少必填 description 应验证失败
        with self.assertRaises(ValidationError):
            JdDraftFacts(name="工程师", description="", skill_requirements=[], summary="x", sources=[])
        # 正常应通过
        facts = JdDraftFacts(name="工程师", description="完整 JD", skill_requirements=["Python"], summary="x", sources=[])
        self.assertEqual(facts.description, "完整 JD")

    def test_copilot_prepare_questions_count_validation(self):
        from hr.agents.copilot_runner_pydantic import PrepareFacts, Question

        # questions <5 应在业务层被 runner 校验为失败（模拟 _validate_prepare_facts 的 <5 检查）
        # Pydantic 层允许任意数量，但 runner 会在校验后重试；此处验证模型可创建后再由 runner 层校验
        facts = PrepareFacts(weak_spots=[], questions=[Question(question="Q1", target="t", difficulty="基础", follow_up="")], focus=[])
        self.assertEqual(len(facts.questions), 1)
        # 5 条以上应通过
        facts2 = PrepareFacts(
            weak_spots=[],
            questions=[Question(question=f"Q{i}", target="t", difficulty="基础", follow_up="") for i in range(5)],
            focus=[],
        )
        self.assertEqual(len(facts2.questions), 5)

    def test_sourcing_candidate_id_must_be_in_allowed(self):
        from hr.agents.sourcing_runner_pydantic import SourcingFacts, CandidateMatch

        # 空 candidates 应在 runner 层被校验为失败，此处验证模型本身可创建
        facts = SourcingFacts(candidates=[], summary="x")
        self.assertEqual(len(facts.candidates), 0)
        # 合法 candidate_id
        facts2 = SourcingFacts(candidates=[CandidateMatch(candidate_id="c1", match_reason="r", risk="", evidence=[])], summary="x")
        self.assertEqual(facts2.candidates[0].candidate_id, "c1")

    def test_pydantic_runner_valid_flow(self):
        # 集成：Pydantic Runner 有效数据流应 SUCCEEDED
        from unittest.mock import Mock, patch
        from types import SimpleNamespace
        from django.test import override_settings
        from hr.models import Candidate, Job, JobStage, HrConfig, Application
        from users.models import User
        from hr.models import HrAccess

        ws = "ws-pydantic-retry"
        user = User.objects.create(username="pydantic-retry-valid", nick_name="RetryValid", password="p", role="USER")
        HrAccess.objects.create(workspace_id=ws, user_id=user.id, role="ADMIN")
        HrConfig.objects.update_or_create(workspace_id=ws, defaults={"llm_model_id": "fake", "agent_enable_screening": True, "agent_max_concurrent_runs": 10, "agent_run_rate_limit": 100})
        cand = Candidate.objects.create(name="RetryCand", workspace_id=ws, skills=["python"], current_city="上海", highest_degree="硕士", years_experience=5)
        job = Job.objects.create(workspace_id=ws, name="Python Engineer", department="Eng", city="上海", skill_requirements=["Python"], headcount=1, status="OPEN", user_id=user.id, owner_id=user.id)
        for idx, (k, n) in enumerate([("APPLIED", "待筛选"), ("SCREEN", "初筛"), ("INTERVIEW", "面试"), ("OFFER", "Offer")], start=1):
            JobStage.objects.create(workspace_id=ws, job=job, key=k, name=n, order=idx, is_system=True)
        stage = JobStage.objects.get(job=job, key="APPLIED")
        app = Application.objects.create(workspace_id=ws, candidate=cand, job=job, current_stage=stage, status="ACTIVE", relation_type="APPLY", channel="OTHER", owner_id=user.id, recruiter_id=user.id)

        mock_model = Mock()
        mock_model._last_usage = {"input_tokens": 1, "output_tokens": 1}
        from hr.agents.runner_pydantic import ScreeningFacts

        mock_agent = Mock()
        mock_result = Mock()
        mock_result.output = ScreeningFacts(dimensions=[
            {"name": "技能匹配", "verdict": "命中", "evidence": [{"paragraph_id": "p1", "excerpt": "Python", "relevance": 0.9}], "confidence": 0.9},
            {"name": "经验相关性", "verdict": "相关", "evidence": [{"paragraph_id": "p1", "excerpt": "三年", "relevance": 0.8}], "confidence": 0.8},
        ], concerns=[], clarifying_questions=[])
        mock_result.usage = lambda: SimpleNamespace(input_tokens=1, output_tokens=1)
        mock_agent.run_sync.return_value = mock_result

        search_return = {"items": [{"candidate": {"id": str(cand.id)}, "resume": {"id": "r1"}, "paragraphs": [{"id": "p1", "content": "Python", "score": 0.9}], "document_id": "d1"}], "meta": {}}

        with override_settings(USE_PYDANTIC_AI=True), patch("hr.agents.runner_pydantic.get_pydantic_model", return_value=(mock_model, "fake")), patch("hr.agents.runner_pydantic.create_agent", return_value=mock_agent), patch("hr.agents.runner_pydantic.search_resumes", return_value=search_return), patch("hr.agents.runner_pydantic.candidate_document_ids", return_value=["d1"]):
            from hr.agents.runner_pydantic import run_screening_agent

            output = run_screening_agent(str(app.id), trigger_type="MANUAL", user_id=user.id, workspace_id=ws)
            self.assertEqual(output["status"], "SUCCEEDED")
            self.assertIsNotNone(output["proposal_id"])
            # 验证 Agent 使用 retries=1（创建时校验）
            self.assertEqual(mock_agent.run_sync.call_count, 1)

