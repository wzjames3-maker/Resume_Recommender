import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
import uuid_utils.compat as uuid

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import AssignmentStatus, Candidate, CandidateAssignment, HrConfig, Interview, Job, ResumeFile, ResumeStatus
from hr.task.resume import parse_resume_task
from hr.serializers.ai import AiService
from hr.serializers.recruitment import RecruitmentService
from hr.services.ai_parser import extract_skills, parse_search_conditions
from hr.services.resume_parser import parse_resume_text


class AssignmentConstraintTests(TestCase):
    def setUp(self):
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(
            name="Python Engineer",
            department="Engineering",
            headcount=1,
            workspace_id="workspace-a",
        )

    def test_only_one_active_assignment_per_candidate_and_job(self):
        CandidateAssignment.objects.create(candidate=self.candidate, job=self.job, workspace_id="workspace-a")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CandidateAssignment.objects.create(
                    candidate=self.candidate,
                    job=self.job,
                    workspace_id="workspace-a",
                )

    def test_terminal_assignment_allows_a_new_assignment(self):
        CandidateAssignment.objects.create(
            candidate=self.candidate,
            job=self.job,
            workspace_id="workspace-a",
            status=AssignmentStatus.REJECTED,
        )

        assignment = CandidateAssignment.objects.create(
            candidate=self.candidate,
            job=self.job,
            workspace_id="workspace-a",
        )

        self.assertEqual(assignment.status, AssignmentStatus.PENDING_SCREEN)

    def test_job_headcount_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Job.objects.create(
                    name="Invalid headcount",
                    department="Engineering",
                    headcount=0,
                    workspace_id="workspace-a",
                )


class RecruitmentServiceTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(
            workspace_id="workspace-a",
            user_id=self.user_id,
            is_workspace_manage=True,
        )
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(
            name="Python Engineer",
            department="Engineering",
            headcount=1,
            workspace_id="workspace-a",
        )

    def test_closed_job_rejects_assignment(self):
        self.job.status = "CLOSED"
        self.job.save(update_fields=["status"])

        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})

    def test_archive_rejects_candidate_with_active_assignment(self):
        self.service.create_assignment(self.job.id, self.candidate.id, {})

        with self.assertRaisesRegex(AppApiException, "active assignment"):
            self.service.archive_candidate(self.candidate.id)

    def test_cross_workspace_resource_is_not_found(self):
        foreign = Candidate.objects.create(name="Bob", workspace_id="workspace-b")

        with self.assertRaises(NotFound404):
            self.service.get_candidate(foreign.id)

    def test_cross_workspace_job_and_assignment_are_not_found(self):
        foreign_candidate = Candidate.objects.create(name="Bob", workspace_id="workspace-b")
        foreign_job = Job.objects.create(
            name="Foreign job",
            department="Engineering",
            headcount=1,
            workspace_id="workspace-b",
        )
        foreign_assignment = CandidateAssignment.objects.create(
            candidate=foreign_candidate,
            job=foreign_job,
            workspace_id="workspace-b",
        )

        with self.assertRaises(NotFound404):
            self.service.get_job(foreign_job.id)
        with self.assertRaises(NotFound404):
            self.service.edit_job(foreign_job.id, {"name": "Changed"})
        with self.assertRaises(NotFound404):
            self.service.create_assignment(foreign_job.id, self.candidate.id, {})
        with self.assertRaises(NotFound404):
            self.service.update_assignment(foreign_assignment.id, {"status": AssignmentStatus.REJECTED})

    def test_member_cannot_edit_candidate_or_create_job(self):
        member_service = RecruitmentService(
            workspace_id="workspace-a",
            user_id=self.user_id,
            is_workspace_manage=False,
        )

        with self.assertRaises(AppUnauthorizedFailed):
            member_service.edit_candidate(self.candidate.id, {"name": "Alice Updated"})
        with self.assertRaises(AppUnauthorizedFailed):
            member_service.create_job({"name": "Platform Engineer", "headcount": 1})

    def test_terminal_assignment_allows_reassignment_through_service(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(assignment["id"], {"status": AssignmentStatus.REJECTED})

        replacement = self.service.create_assignment(self.job.id, self.candidate.id, {})

        self.assertEqual(replacement["status"], AssignmentStatus.PENDING_SCREEN)

    def test_archived_candidate_rejects_reactivating_assignment(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(assignment["id"], {"status": AssignmentStatus.REJECTED})
        self.service.archive_candidate(self.candidate.id)

        with self.assertRaisesRegex(AppApiException, "archived"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})

    def test_closed_job_rejects_reactivating_assignment(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(assignment["id"], {"status": AssignmentStatus.REJECTED})
        self.service.edit_job(self.job.id, {"status": "CLOSED"})

        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})


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
        self.assertEqual(result["current_city"], "杭州")
        self.assertEqual(result["target_city"], "上海")
        self.assertEqual(result["highest_degree"], "本科")
        self.assertEqual(result["years_experience"], 5)
        self.assertEqual(result["skills"], ["Python", "Django", "PostgreSQL"])

    def test_unknown_fields_stay_empty(self):
        result = parse_resume_text("这是一个没有结构化字段的文本")
        self.assertEqual(result["name"], "")
        self.assertEqual(result["email"], "")
        self.assertEqual(result["phone"], "")
        self.assertEqual(result["skills"], [])


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
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, is_workspace_manage=True)

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
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
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
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
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


class InterviewStatusMachineTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]

    def _transition(self, to_status):
        return self.service.update_assignment(self.assignment_id, {"status": to_status})

    def test_full_offer_chain_is_legal(self):
        self._transition(AssignmentStatus.SCREEN_PASSED)
        self._transition(AssignmentStatus.INTERVIEWING)
        self._transition(AssignmentStatus.OFFER)
        self._transition(AssignmentStatus.HIRED)
        assignment = CandidateAssignment.objects.get(id=self.assignment_id)
        self.assertEqual(assignment.status, "HIRED")

    def test_illegal_transition_rejected(self):
        with self.assertRaisesRegex(AppApiException, "transition"):
            self._transition(AssignmentStatus.OFFER)

    def test_terminal_state_cannot_transition(self):
        self._transition(AssignmentStatus.REJECTED)
        with self.assertRaisesRegex(AppApiException, "transition"):
            self._transition(AssignmentStatus.SCREEN_PASSED)

    def test_hired_candidate_cannot_get_new_assignment(self):
        self._transition(AssignmentStatus.SCREEN_PASSED)
        self._transition(AssignmentStatus.INTERVIEWING)
        self._transition(AssignmentStatus.OFFER)
        self._transition(AssignmentStatus.HIRED)
        with self.assertRaisesRegex(AppApiException, "hired"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})

    def test_closed_job_cannot_enter_interviewing(self):
        self._transition(AssignmentStatus.SCREEN_PASSED)
        self.service.edit_job(self.job.id, {"status": "CLOSED"})
        with self.assertRaisesRegex(AppApiException, "closed"):
            self._transition(AssignmentStatus.INTERVIEWING)


class InterviewServiceTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
        self.candidate = Candidate.objects.create(name="Bob", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]

    def test_create_interview_auto_increments_round(self):
        first = self.service.create_interview(self.assignment_id, {"interviewer": "张伟"})
        self.assertEqual(first["round_no"], 1)
        second = self.service.create_interview(self.assignment_id, {"interviewer": "李娜"})
        self.assertEqual(second["round_no"], 2)

    def test_update_interview_result_and_feedback(self):
        interview = self.service.create_interview(self.assignment_id, {})
        updated = self.service.update_interview(interview["id"], {"status": "PASSED", "feedback": "表现优秀"})
        self.assertEqual(updated["status"], "PASSED")
        self.assertEqual(updated["feedback"], "表现优秀")

    def test_interview_cross_workspace_not_found(self):
        foreign = Interview.objects.create(
            workspace_id="workspace-b", assignment_id=self.assignment_id, round_no=1,
        )
        with self.assertRaises(NotFound404):
            self.service.update_interview(foreign.id, {"status": "PASSED"})


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
        self.service = AiService(workspace_id="workspace-a", user_id=self.user_id, is_workspace_manage=True)

    def test_config_default_is_null(self):
        self.assertEqual(self.service.get_config(), {"llm_model_id": None})

    @patch("hr.serializers.ai.get_model_by_id")
    def test_save_and_get_config(self, mock_get_model):
        mock_get_model.return_value = SimpleNamespace(model_type="LLM")
        saved = self.service.save_config({"llm_model_id": "model-1"})
        self.assertEqual(saved, {"llm_model_id": "model-1"})
        self.assertEqual(self.service.get_config(), {"llm_model_id": "model-1"})
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

    def test_save_config_requires_model_id(self):
        with self.assertRaisesRegex(AppApiException, "llm_model_id is required"):
            self.service.save_config({})

    def test_member_cannot_save_config(self):
        member_service = AiService(workspace_id="workspace-a", user_id=self.user_id, is_workspace_manage=False)
        with self.assertRaises(AppUnauthorizedFailed):
            member_service.save_config({"llm_model_id": "model-1"})

    def test_parse_search_requires_config(self):
        with self.assertRaisesRegex(AppApiException, "AI 设置"):
            self.service.parse_search("找 Python 后端")

    @patch("hr.serializers.ai.get_model_by_id")
    def test_parse_search_rejects_non_llm_configured_model(self, mock_get_model):
        HrConfig.objects.create(workspace_id="workspace-a", llm_model_id="model-1")
        mock_get_model.return_value = SimpleNamespace(model_type="EMBEDDING")
        with self.assertRaisesRegex(AppApiException, "LLM"):
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
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)

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
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
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
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), is_workspace_manage=True)
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
