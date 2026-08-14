import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient
import uuid_utils.compat as uuid

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import (
    AssignmentStatus,
    Candidate,
    CandidateAssignment,
    HrAccess,
    HrAuditLog,
    HrConfig,
    Interview,
    Job,
    ResumeFile,
    ResumeStatus,
)
from hr.services.audit import write_audit_log
from hr.task.resume import parse_resume_task
from hr.serializers.ai import AiService
from hr.serializers.recruitment import RecruitmentService
from hr.services.ai_parser import extract_skills, parse_search_conditions
from hr.services.resume_parser import parse_resume_text
from users.models import User


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
            hr_role="ADMIN",
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
            hr_role="OPERATOR",
        )

        with self.assertRaises(AppUnauthorizedFailed):
            member_service.edit_candidate(self.candidate.id, {"name": "Alice Updated"})
        with self.assertRaises(AppUnauthorizedFailed):
            member_service.create_job({"name": "Platform Engineer", "headcount": 1})

    def test_terminal_assignment_allows_reassignment_through_service(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(
            assignment["id"], {"status": AssignmentStatus.REJECTED, "termination_reason": "NOT_FIT"}
        )

        replacement = self.service.create_assignment(self.job.id, self.candidate.id, {})

        self.assertEqual(replacement["status"], AssignmentStatus.PENDING_SCREEN)

    def test_archived_candidate_rejects_reactivating_assignment(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(
            assignment["id"], {"status": AssignmentStatus.REJECTED, "termination_reason": "NOT_FIT"}
        )
        self.service.archive_candidate(self.candidate.id)

        with self.assertRaisesRegex(AppApiException, "archived"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})

    def test_closed_job_rejects_reactivating_assignment(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(
            assignment["id"], {"status": AssignmentStatus.REJECTED, "termination_reason": "NOT_FIT"}
        )
        self.service.close_job(self.job.id, "FILLED")

        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})

    def test_create_assignment_locks_job_row(self):
        with patch.object(Job.objects, "select_for_update", wraps=Job.objects.select_for_update) as locked:
            result = self.service.create_assignment(self.job.id, self.candidate.id, {})
        locked.assert_called_once()
        self.assertEqual(result["status"], "PENDING_SCREEN")


class ActiveAssignmentArchiveTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(
            workspace_id="workspace-a",
            user_id=self.user_id,
            hr_role="ADMIN",
        )
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(
            name="Python Engineer",
            department="Engineering",
            headcount=1,
            workspace_id="workspace-a",
        )

    def _transition(self, assignment_id, to_status):
        return self.service.update_assignment(assignment_id, {"status": to_status, "termination_reason": "OTHER"})

    def _to_interviewing(self, candidate):
        assignment = self.service.create_assignment(self.job.id, candidate.id, {})
        self._transition(assignment["id"], AssignmentStatus.SCREEN_PASSED)
        self._transition(assignment["id"], AssignmentStatus.INTERVIEWING)
        return assignment["id"]

    def test_archive_rejects_interviewing_assignment(self):
        self._to_interviewing(self.candidate)

        with self.assertRaisesRegex(AppApiException, "active assignment"):
            self.service.archive_candidate(self.candidate.id)

    def test_archive_rejects_offer_assignment(self):
        assignment_id = self._to_interviewing(self.candidate)
        self._transition(assignment_id, AssignmentStatus.OFFER)

        with self.assertRaisesRegex(AppApiException, "active assignment"):
            self.service.archive_candidate(self.candidate.id)

    def test_archive_allows_terminal_assignment_statuses(self):
        for status in (AssignmentStatus.HIRED, AssignmentStatus.REJECTED, AssignmentStatus.CLOSED):
            with self.subTest(status=status):
                candidate = Candidate.objects.create(name=f"C-{status}", workspace_id="workspace-a")
                assignment_id = self.service.create_assignment(self.job.id, candidate.id, {})["id"]
                if status == AssignmentStatus.HIRED:
                    self._transition(assignment_id, AssignmentStatus.SCREEN_PASSED)
                    self._transition(assignment_id, AssignmentStatus.INTERVIEWING)
                    self._transition(assignment_id, AssignmentStatus.OFFER)
                self._transition(assignment_id, status)

                result = self.service.archive_candidate(candidate.id)
                self.assertEqual(result["status"], "ARCHIVED")

    def test_active_assignment_count_includes_interviewing_and_offer(self):
        for status in (AssignmentStatus.INTERVIEWING, AssignmentStatus.OFFER, AssignmentStatus.HIRED):
            candidate = Candidate.objects.create(name=f"C-{status}", workspace_id="workspace-a")
            assignment_id = self.service.create_assignment(self.job.id, candidate.id, {})["id"]
            if status == AssignmentStatus.OFFER:
                self._transition(assignment_id, AssignmentStatus.SCREEN_PASSED)
                self._transition(assignment_id, AssignmentStatus.INTERVIEWING)
                self._transition(assignment_id, AssignmentStatus.OFFER)
            elif status == AssignmentStatus.HIRED:
                self._transition(assignment_id, AssignmentStatus.SCREEN_PASSED)
                self._transition(assignment_id, AssignmentStatus.INTERVIEWING)
                self._transition(assignment_id, AssignmentStatus.OFFER)
                self._transition(assignment_id, AssignmentStatus.HIRED)
            else:
                self._transition(assignment_id, AssignmentStatus.SCREEN_PASSED)
                self._transition(assignment_id, AssignmentStatus.INTERVIEWING)

        result = self.service.page_jobs(1, 20, {})
        job_record = next(item for item in result["records"] if item["id"] == str(self.job.id))
        self.assertEqual(job_record["active_assignment_count"], 2)


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
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]

    def _transition(self, to_status):
        return self.service.update_assignment(self.assignment_id, {"status": to_status, "termination_reason": "OTHER"})

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
        self.job.status = "CLOSED"
        self.job.save(update_fields=["status"])
        with self.assertRaisesRegex(AppApiException, "closed"):
            self._transition(AssignmentStatus.INTERVIEWING)


class InterviewServiceTests(TestCase):
    def setUp(self):
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="ADMIN")
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
        self.service = AiService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")

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
        job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        resume = ResumeFile.objects.create(
            workspace_id="workspace-a", file_name="r.txt", extension="txt",
            file_path="/tmp/r.txt", file_size=1, sha256="sha-" + uuid.uuid7().hex,
            candidate=self.secondary,
        )
        assignment_id = self.service.create_assignment(job.id, self.secondary.id, {})["id"]
        interview = Interview.objects.create(workspace_id="workspace-a", assignment_id=assignment_id, round_no=1)
        self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})
        resume.refresh_from_db()
        self.assertEqual(resume.candidate_id, self.primary.id)
        assignment = CandidateAssignment.objects.get(id=assignment_id)
        self.assertEqual(assignment.candidate_id, self.primary.id)
        interview.refresh_from_db()
        self.assertEqual(str(interview.assignment_id), assignment_id)

    def test_merge_rejects_conflicting_active_assignment(self):
        job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=2)
        self.service.create_assignment(job.id, self.primary.id, {})
        self.service.create_assignment(job.id, self.secondary.id, {})
        with self.assertRaisesRegex(AppApiException, "冲突"):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})

    def test_merge_allows_different_job_active_assignments(self):
        job_a = Job.objects.create(name="Engineer A", workspace_id="workspace-a", headcount=1)
        job_b = Job.objects.create(name="Engineer B", workspace_id="workspace-a", headcount=1)
        self.service.create_assignment(job_a.id, self.primary.id, {})
        self.service.create_assignment(job_b.id, self.secondary.id, {})
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


class StatusMachineMatrixTests(TestCase):
    """A2: 扩展后的迁移矩阵每行允许/禁止流转各一例"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)

    def _new_assignment(self):
        candidate = Candidate.objects.create(name=f"C-{uuid.uuid7().hex[:6]}", workspace_id="workspace-a")
        return self.service.create_assignment(self.job.id, candidate.id, {})["id"]

    def test_matrix_allows_each_legal_transition(self):
        cases = [
            (["SCREEN_PASSED"], None),
            (["SCREEN_PASSED", "INTERVIEWING"], None),
            (["SCREEN_PASSED", "INTERVIEWING", "OFFER"], None),
            (["SCREEN_PASSED", "INTERVIEWING", "OFFER", "HIRED"], None),
            (["WITHDRAWN"], "CANDIDATE_WITHDRAW"),
            (["REJECTED"], "NOT_FIT"),
            (["CLOSED"], "JOB_CLOSED"),
        ]
        for steps, reason in cases:
            with self.subTest(final=steps[-1]):
                assignment_id = self._new_assignment()
                for index, step in enumerate(steps):
                    data = {"status": step}
                    if index == len(steps) - 1 and reason:
                        data["termination_reason"] = reason
                    self.service.update_assignment(assignment_id, data)
                assignment = CandidateAssignment.objects.get(id=assignment_id)
                self.assertEqual(assignment.status, steps[-1])

    def test_matrix_rejects_each_illegal_transition(self):
        cases = [
            (["INTERVIEWING"], "PENDING_SCREEN -> INTERVIEWING"),
            (["SCREEN_PASSED", "OFFER"], "SCREEN_PASSED -> OFFER"),
            (["SCREEN_PASSED", "INTERVIEWING", "HIRED"], "INTERVIEWING -> HIRED"),
            (["SCREEN_PASSED", "INTERVIEWING", "OFFER", "INTERVIEWING"], "OFFER -> INTERVIEWING"),
            (["REJECTED", "SCREEN_PASSED"], "REJECTED -> SCREEN_PASSED"),
            (["WITHDRAWN", "PENDING_SCREEN"], "WITHDRAWN -> PENDING_SCREEN"),
            (["CLOSED", "PENDING_SCREEN"], "CLOSED -> PENDING_SCREEN"),
            (["SCREEN_PASSED", "INTERVIEWING", "OFFER", "HIRED", "REJECTED"], "HIRED -> REJECTED"),
        ]
        for steps, label in cases:
            with self.subTest(label=label):
                assignment_id = self._new_assignment()
                for index, step in enumerate(steps):
                    data = {"status": step}
                    if step in (AssignmentStatus.REJECTED, AssignmentStatus.WITHDRAWN, AssignmentStatus.CLOSED):
                        data["termination_reason"] = "OTHER"
                    if index == len(steps) - 1:
                        with self.assertRaisesRegex(AppApiException, "transition"):
                            self.service.update_assignment(assignment_id, data)
                    else:
                        self.service.update_assignment(assignment_id, data)


class TerminationReasonTests(TestCase):
    """A2: 终态流转必填 termination_reason，非法枚举 400"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)

    def _new_assignment(self):
        candidate = Candidate.objects.create(name=f"C-{uuid.uuid7().hex[:6]}", workspace_id="workspace-a")
        return self.service.create_assignment(self.job.id, candidate.id, {})["id"]

    def test_terminal_transition_requires_termination_reason(self):
        for status in (AssignmentStatus.REJECTED, AssignmentStatus.WITHDRAWN, AssignmentStatus.CLOSED):
            with self.subTest(status=status):
                assignment_id = self._new_assignment()
                with self.assertRaisesRegex(AppApiException, "termination_reason"):
                    self.service.update_assignment(assignment_id, {"status": status})

    def test_terminal_transition_stores_termination_reason(self):
        assignment_id = self._new_assignment()
        result = self.service.update_assignment(
            assignment_id, {"status": AssignmentStatus.REJECTED, "termination_reason": "SALARY"}
        )
        self.assertEqual(result["termination_reason"], "SALARY")

    def test_invalid_termination_reason_rejected(self):
        assignment_id = self._new_assignment()
        with self.assertRaisesRegex(AppApiException, "termination_reason"):
            self.service.update_assignment(
                assignment_id, {"status": AssignmentStatus.REJECTED, "termination_reason": "NOPE"}
            )


class RestoreRejectedTests(TestCase):
    """A2: REJECTED -> PENDING_SCREEN 仅管理员，note 记 [restore]，清空 termination_reason"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]
        self.service.update_assignment(
            self.assignment_id, {"status": AssignmentStatus.REJECTED, "termination_reason": "NOT_FIT"}
        )

    def test_member_cannot_restore(self):
        member_service = RecruitmentService(
            workspace_id="workspace-a", user_id=self.user_id, hr_role="OPERATOR"
        )
        with self.assertRaises(AppUnauthorizedFailed):
            member_service.update_assignment(self.assignment_id, {"status": AssignmentStatus.PENDING_SCREEN, "note": "误拒绝"})

    def test_restore_records_note_and_clears_termination_reason(self):
        result = self.service.update_assignment(
            self.assignment_id, {"status": AssignmentStatus.PENDING_SCREEN, "note": "误拒绝"}
        )
        self.assertEqual(result["status"], AssignmentStatus.PENDING_SCREEN)
        assignment = CandidateAssignment.objects.get(id=self.assignment_id)
        self.assertEqual(assignment.status, AssignmentStatus.PENDING_SCREEN)
        self.assertEqual(assignment.note, "[restore] 误拒绝")
        self.assertIsNone(assignment.termination_reason)

    def test_restore_requires_reason(self):
        with self.assertRaisesRegex(AppApiException, "restore reason"):
            self.service.update_assignment(self.assignment_id, {"status": AssignmentStatus.PENDING_SCREEN})

    def test_restore_rejected_when_another_active_assignment_exists(self):
        self.service.create_assignment(self.job.id, self.candidate.id, {})
        with self.assertRaisesRegex(AppApiException, "active assignment"):
            self.service.update_assignment(self.assignment_id, {"status": AssignmentStatus.PENDING_SCREEN, "note": "误拒绝"})


class ReapplyTests(TestCase):
    """A2: 终态历史后新建关联 is_reapply=True，applied_at 可覆盖"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)

    def test_fresh_assignment_defaults_and_not_reapply(self):
        result = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.assertIs(result["is_reapply"], False)
        self.assertEqual(result["relation_type"], "APPLY")
        self.assertEqual(result["channel"], "OTHER")
        self.assertEqual(result["owner_id"], str(self.user_id))
        self.assertTrue(result["applied_at"])

    def test_reapply_marked_after_rejected_history(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(
            assignment["id"], {"status": AssignmentStatus.REJECTED, "termination_reason": "NOT_FIT"}
        )
        replacement = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.assertIs(replacement["is_reapply"], True)
        self.assertEqual(replacement["status"], AssignmentStatus.PENDING_SCREEN)

    def test_reapply_applied_at_overridable(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(
            assignment["id"], {"status": AssignmentStatus.WITHDRAWN, "termination_reason": "CANDIDATE_WITHDRAW"}
        )
        replacement = self.service.create_assignment(
            self.job.id, self.candidate.id, {"applied_at": "2026-08-01T10:00:00Z"}
        )
        self.assertIs(replacement["is_reapply"], True)
        self.assertTrue(replacement["applied_at"].isoformat().startswith("2026-08-01T10:00:00"))

    def test_create_assignment_with_relation_fields(self):
        result = self.service.create_assignment(
            self.job.id, self.candidate.id,
            {"relation_type": "REFERRAL", "channel": "HEADHUNTER", "owner_id": str(uuid.uuid7())},
        )
        self.assertEqual(result["relation_type"], "REFERRAL")
        self.assertEqual(result["channel"], "HEADHUNTER")
        self.assertNotEqual(result["owner_id"], str(self.user_id))


class CloseJobTests(TestCase):
    """A2: 关闭职位批量收尾在途关联、恢复职位清空 close_reason"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=5)
        self.first = self.service.create_assignment(
            self.job.id, Candidate.objects.create(name="A", workspace_id="workspace-a").id, {}
        )["id"]
        self.second = self.service.create_assignment(
            self.job.id, Candidate.objects.create(name="B", workspace_id="workspace-a").id, {}
        )["id"]
        self.service.update_assignment(
            self.second, {"status": AssignmentStatus.SCREEN_PASSED, "termination_reason": "OTHER"}
        )
        self.rejected = self.service.create_assignment(
            self.job.id, Candidate.objects.create(name="C", workspace_id="workspace-a").id, {}
        )["id"]
        self.service.update_assignment(
            self.rejected, {"status": AssignmentStatus.REJECTED, "termination_reason": "NOT_FIT"}
        )

    def test_close_requires_close_reason(self):
        with self.assertRaisesRegex(AppApiException, "close_reason"):
            self.service.close_job(self.job.id, "")

    def test_close_rejects_invalid_close_reason(self):
        with self.assertRaisesRegex(AppApiException, "close_reason"):
            self.service.close_job(self.job.id, "NOPE")

    def test_close_terminates_active_assignments(self):
        result = self.service.close_job(self.job.id, "FILLED")
        self.assertEqual(result["closed_count"], 2)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "CLOSED")
        self.assertEqual(self.job.close_reason, "FILLED")
        for assignment_id in (self.first, self.second):
            assignment = CandidateAssignment.objects.get(id=assignment_id)
            self.assertEqual(assignment.status, AssignmentStatus.CLOSED)
            self.assertEqual(assignment.termination_reason, "JOB_CLOSED")
        rejected = CandidateAssignment.objects.get(id=self.rejected)
        self.assertEqual(rejected.status, AssignmentStatus.REJECTED)

    def test_reopen_clears_close_reason(self):
        self.service.close_job(self.job.id, "CANCELLED")
        result = self.service.reopen_job(self.job.id)
        self.assertEqual(result["status"], "OPEN")
        self.assertIsNone(result["close_reason"])
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "OPEN")
        self.assertIsNone(self.job.close_reason)

    def test_member_cannot_close_or_reopen(self):
        member_service = RecruitmentService(
            workspace_id="workspace-a", user_id=self.user_id, hr_role="OPERATOR"
        )
        with self.assertRaises(AppUnauthorizedFailed):
            member_service.close_job(self.job.id, "FILLED")
        with self.assertRaises(AppUnauthorizedFailed):
            member_service.reopen_job(self.job.id)

    def test_close_cross_workspace_raises_404(self):
        foreign = Job.objects.create(name="Foreign", workspace_id="workspace-b", headcount=1)
        with self.assertRaises(NotFound404):
            self.service.close_job(foreign.id, "FILLED")
        with self.assertRaises(NotFound404):
            self.service.reopen_job(foreign.id)

    def test_reopen_rejects_open_job(self):
        with self.assertRaisesRegex(AppApiException, "on hold or closed"):
            self.service.reopen_job(self.job.id)


class JobPositionStatusTests(TestCase):
    """A2: DRAFT/ON_HOLD 不能建新关联；ON_HOLD 下不能流转到 INTERVIEWING"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)

    def test_draft_job_rejects_new_assignment(self):
        self.job.status = "DRAFT"
        self.job.save(update_fields=["status"])
        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})

    def test_on_hold_job_rejects_new_assignment(self):
        self.job.status = "ON_HOLD"
        self.job.save(update_fields=["status"])
        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.create_assignment(self.job.id, self.candidate.id, {})

    def test_on_hold_allows_terminal_but_not_interviewing(self):
        assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]
        self.job.status = "ON_HOLD"
        self.job.save(update_fields=["status"])
        self.service.update_assignment(assignment_id, {"status": AssignmentStatus.SCREEN_PASSED})
        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.update_assignment(assignment_id, {"status": AssignmentStatus.INTERVIEWING})
        self.service.update_assignment(
            assignment_id, {"status": AssignmentStatus.REJECTED, "termination_reason": "NOT_FIT"}
        )
        self.assertEqual(
            CandidateAssignment.objects.get(id=assignment_id).status, AssignmentStatus.REJECTED
        )


class OwnerFieldTests(TestCase):
    """A2: 负责人默认当前用户，可按 owner_id 筛选"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.other_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")

    def test_create_defaults_owner_to_current_user(self):
        job = self.service.create_job({"name": "Engineer", "headcount": 1})
        self.assertEqual(job["owner_id"], str(self.user_id))
        assignment = self.service.create_assignment(
            job["id"], Candidate.objects.create(name="Alice", workspace_id="workspace-a").id, {}
        )
        self.assertEqual(assignment["owner_id"], str(self.user_id))

    def test_explicit_owner_on_create(self):
        job = self.service.create_job({"name": "Engineer", "headcount": 1, "owner_id": str(self.other_id)})
        self.assertEqual(job["owner_id"], str(self.other_id))
        assignment = self.service.create_assignment(
            job["id"], Candidate.objects.create(name="Alice", workspace_id="workspace-a").id,
            {"owner_id": str(self.other_id)},
        )
        self.assertEqual(assignment["owner_id"], str(self.other_id))

    def test_edit_job_updates_owner_id(self):
        job = self.service.create_job({"name": "Engineer", "headcount": 1})
        result = self.service.edit_job(job["id"], {"owner_id": str(self.other_id)})
        self.assertEqual(result["owner_id"], str(self.other_id))

    def test_update_assignment_updates_owner_id(self):
        job = self.service.create_job({"name": "Engineer", "headcount": 1})
        assignment = self.service.create_assignment(
            job["id"], Candidate.objects.create(name="Alice", workspace_id="workspace-a").id, {}
        )
        result = self.service.update_assignment(assignment["id"], {"owner_id": str(self.other_id)})
        self.assertEqual(result["owner_id"], str(self.other_id))

    def test_page_jobs_filters_by_owner_id(self):
        self.service.create_job({"name": "Mine", "headcount": 1})
        self.service.create_job({"name": "Theirs", "headcount": 1, "owner_id": str(self.other_id)})
        result = self.service.page_jobs(1, 20, {"owner_id": str(self.other_id)})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Theirs")

    def test_page_candidates_filters_by_owner_id(self):
        alice = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        bob = Candidate.objects.create(name="Bob", workspace_id="workspace-a")
        job = self.service.create_job({"name": "Engineer", "headcount": 1})
        self.service.create_assignment(job["id"], alice.id, {})
        self.service.create_assignment(job["id"], bob.id, {"owner_id": str(self.other_id)})
        result = self.service.page_candidates(1, 20, {"owner_id": str(self.other_id)})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["name"], "Bob")

    def test_page_jobs_rejects_invalid_owner_id(self):
        with self.assertRaisesRegex(AppApiException, "owner_id is invalid"):
            self.service.page_jobs(1, 20, {"owner_id": "garbage"})

    def test_page_candidates_rejects_invalid_owner_id(self):
        with self.assertRaisesRegex(AppApiException, "owner_id is invalid"):
            self.service.page_candidates(1, 20, {"owner_id": "garbage"})


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


class EnumValidationTests(TestCase):
    """A2: relation_type / channel 非法枚举 400"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)

    def test_invalid_relation_type_rejected(self):
        with self.assertRaisesRegex(AppApiException, "relation_type"):
            self.service.create_assignment(self.job.id, self.candidate.id, {"relation_type": "NOPE"})

    def test_invalid_channel_rejected(self):
        with self.assertRaisesRegex(AppApiException, "channel"):
            self.service.create_assignment(self.job.id, self.candidate.id, {"channel": "NOPE"})

    def test_invalid_owner_id_rejected(self):
        with self.assertRaisesRegex(AppApiException, "owner_id"):
            self.service.create_assignment(self.job.id, self.candidate.id, {"owner_id": "garbage"})

    def test_invalid_close_reason_on_edit_job_rejected(self):
        job = self.service.create_job({"name": "Engineer", "headcount": 1})
        with self.assertRaisesRegex(AppApiException, "close_reason"):
            self.service.edit_job(job["id"], {"close_reason": "NOPE"})


class CloseReopenRouteTests(TestCase):
    """A2: close/reopen 路由注册且受权限保护"""

    def test_close_reopen_routes_are_registered_and_protected(self):
        from django.urls import resolve
        from hr.views.recruitment import JobDetailAPI

        for suffix in ("close", "reopen"):
            path = f"/admin/api/workspace/workspace-a/hr/jobs/{uuid.uuid7()}/{suffix}"
            resolved = resolve(path)
            self.assertIs(resolved.func.cls, JobDetailAPI.Close if suffix == "close" else JobDetailAPI.Reopen)
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


class HrRoleEnforcementTests(TestCase):
    """A3: 服务层角色能力矩阵（VIEWER 只读 / OPERATOR / ADMIN 分级）"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.viewer = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="VIEWER")
        self.operator = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="OPERATOR")
        self.admin = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)

    def test_viewer_cannot_create_candidate(self):
        with self.assertRaises(AppUnauthorizedFailed):
            self.viewer.create_candidate({"name": "Bob"})

    def test_viewer_cannot_create_assignment(self):
        with self.assertRaises(AppUnauthorizedFailed):
            self.viewer.create_assignment(self.job.id, self.candidate.id, {})

    def test_viewer_cannot_transition_assignment(self):
        assignment = self.operator.create_assignment(self.job.id, self.candidate.id, {})
        with self.assertRaises(AppUnauthorizedFailed):
            self.viewer.update_assignment(assignment["id"], {"status": "SCREEN_PASSED"})

    def test_viewer_cannot_upload_or_download_resume(self):
        with self.assertRaises(AppUnauthorizedFailed):
            self.viewer.upload_resumes([], "OTHER")

    def test_operator_cannot_create_job_or_edit_candidate(self):
        with self.assertRaises(AppUnauthorizedFailed):
            self.operator.create_job({"name": "Platform", "headcount": 1})
        with self.assertRaises(AppUnauthorizedFailed):
            self.operator.edit_candidate(self.candidate.id, {"name": "Renamed"})

    def test_operator_can_create_candidate_assignment_and_transition(self):
        created = self.operator.create_candidate({"name": "Bob"})
        self.assertEqual(created["name"], "Bob")
        assignment = self.operator.create_assignment(self.job.id, self.candidate.id, {})
        transitioned = self.operator.update_assignment(assignment["id"], {"status": "SCREEN_PASSED"})
        self.assertEqual(transitioned["status"], "SCREEN_PASSED")

    def test_operator_cannot_archive_or_merge(self):
        with self.assertRaises(AppUnauthorizedFailed):
            self.operator.archive_candidate(self.candidate.id)
        secondary = Candidate.objects.create(name="Bob", workspace_id="workspace-a")
        with self.assertRaises(AppUnauthorizedFailed):
            self.operator.merge_candidates(self.candidate.id, {"secondary_id": str(secondary.id)})

    def test_viewer_can_read_lists(self):
        result = self.viewer.page_candidates(1, 20, {})
        self.assertEqual(result["total"], 1)


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


class HrAuditLogTests(TestCase):
    """A3: 服务层关键操作审计记录"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a", phone="13812345678")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)

    def _logs(self, action):
        return HrAuditLog.objects.filter(workspace_id="workspace-a", user_id=self.user_id, action=action)

    def test_detail_view_writes_view_detail_audit(self):
        self.service.get_candidate(self.candidate.id)
        self.service.get_job(self.job.id)
        self.assertTrue(self._logs("VIEW_DETAIL").filter(object_type="CANDIDATE", object_id=str(self.candidate.id)).exists())
        self.assertTrue(self._logs("VIEW_DETAIL").filter(object_type="JOB", object_id=str(self.job.id)).exists())

    def test_create_candidate_writes_create_audit(self):
        created = self.service.create_candidate({"name": "Bob"})
        self.assertTrue(self._logs("CREATE").filter(object_type="CANDIDATE", object_id=str(created["id"])).exists())

    def test_assignment_transition_writes_audit(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(assignment["id"], {"status": "SCREEN_PASSED"})
        self.assertTrue(self._logs("ASSIGNMENT_TRANSITION").filter(object_type="ASSIGNMENT").exists())

    def test_archive_and_close_job_write_audit(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(assignment["id"], {"status": "REJECTED", "termination_reason": "NOT_FIT"})
        self.service.archive_candidate(self.candidate.id)
        self.assertTrue(self._logs("ARCHIVE").exists())
        self.service.close_job(self.job.id, "FILLED")
        self.assertTrue(self._logs("JOB_CLOSE").filter(object_type="JOB").exists())
        self.service.reopen_job(self.job.id)
        self.assertTrue(self._logs("JOB_REOPEN").exists())

    @patch("hr.serializers.recruitment.parse_resume_task.delay")
    def test_resume_upload_and_download_write_audit(self, mock_delay):
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write("姓名：李四\n电话：13912345678".encode("utf-8"))
        handle.close()
        record = self.service.upload_resumes([(handle.name, "li.txt", "txt")], "OTHER")[0]
        self.assertTrue(self._logs("RESUME_UPLOAD").filter(object_id=str(record["resume_id"])).exists())
        self.service.download_resume(str(record["resume_id"]))
        self.assertTrue(self._logs("RESUME_DOWNLOAD").filter(object_id=str(record["resume_id"])).exists())

    def test_merge_writes_merge_audit(self):
        secondary = Candidate.objects.create(name="Bob", workspace_id="workspace-a")
        self.service.merge_candidates(self.candidate.id, {"secondary_id": str(secondary.id)})
        self.assertTrue(self._logs("MERGE").filter(object_id=str(self.candidate.id)).exists())

    def test_denied_write_writes_access_denied_audit(self):
        viewer = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="VIEWER")
        with self.assertRaises(AppUnauthorizedFailed):
            viewer.create_candidate({"name": "Bob"})
        denied = HrAuditLog.objects.filter(
            workspace_id="workspace-a", user_id=self.user_id, action="ACCESS_DENIED", result="DENIED"
        )
        self.assertTrue(denied.exists())


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
