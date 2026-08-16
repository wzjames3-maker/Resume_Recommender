import csv
import io
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
    AssignmentStatus,
    Candidate,
    CandidateAssignment,
    HandoffStatus,
    HrAccess,
    HrAuditLog,
    HrConfig,
    Interview,
    Job,
    Offer,
    OnboardingHandoff,
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
from knowledge.models import Document, Embedding, Knowledge, KnowledgeFolder, KnowledgeScope, KnowledgeType, Paragraph
from models_provider.models import Model
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


class InterviewerCollaborationTests(TestCase):
    """B1: 面试官用户化、最小可见、反馈截止与可追溯"""

    def setUp(self):
        self.admin_id = uuid.uuid7()
        self.interviewer = User.objects.create(
            username="interviewer-1", nick_name="面试官甲", password="p", role="USER"
        )
        self.other = User.objects.create(
            username="interviewer-2", nick_name="面试官乙", password="p", role="USER"
        )
        self.admin = RecruitmentService(workspace_id="workspace-a", user_id=self.admin_id, hr_role="ADMIN")
        self.interviewer_service = RecruitmentService(
            workspace_id="workspace-a", user_id=self.interviewer.id, hr_role=None
        )
        self.candidate = Candidate.objects.create(name="Bob", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = self.admin.create_assignment(self.job.id, self.candidate.id, {})["id"]

    def test_create_interview_saves_interviewer_user_and_deadline(self):
        interview = self.admin.create_interview(self.assignment_id, {
            "interviewer_user_id": str(self.interviewer.id),
            "feedback_deadline": "2026-08-20T10:00:00Z",
        })
        self.assertEqual(interview["interviewer_user_id"], str(self.interviewer.id))
        self.assertEqual(interview["interviewer"], "面试官甲")
        row = Interview.objects.get(id=interview["id"])
        self.assertEqual(row.interviewer_user_id, self.interviewer.id)
        self.assertIsNotNone(row.feedback_deadline)

    def test_create_interview_rejects_non_member_interviewer(self):
        stranger = User.objects.create(
            username="sys-admin", nick_name="系统管理员", password="p", role="ADMIN"
        )
        with self.assertRaisesRegex(AppApiException, "workspace member"):
            self.admin.create_interview(self.assignment_id, {"interviewer_user_id": str(stranger.id)})

    def test_create_interview_rejects_invalid_interviewer_uuid(self):
        with self.assertRaisesRegex(AppApiException, "interviewer_user_id is invalid"):
            self.admin.create_interview(self.assignment_id, {"interviewer_user_id": "not-a-uuid"})

    def test_list_my_interviews_only_returns_mine(self):
        mine = self.admin.create_interview(self.assignment_id, {
            "interviewer_user_id": str(self.interviewer.id),
        })
        self.admin.create_interview(self.assignment_id, {
            "interviewer_user_id": str(self.other.id),
        })
        result = self.interviewer_service.list_my_interviews()
        self.assertEqual([item["interview_id"] for item in result], [mine["id"]])
        self.assertEqual(result[0]["candidate_name"], "Bob")
        self.assertEqual(result[0]["job_name"], "Engineer")
        self.assertIs(result[0]["is_overdue"], False)
        self.assertNotIn("phone", result[0])
        self.assertNotIn("email", result[0])

    def test_my_interviews_marks_overdue_when_pending_past_deadline(self):
        interview = self.admin.create_interview(self.assignment_id, {
            "interviewer_user_id": str(self.interviewer.id),
            "feedback_deadline": "2020-01-01T00:00:00Z",
        })
        result = self.interviewer_service.list_my_interviews()
        self.assertEqual(result[0]["interview_id"], interview["id"])
        self.assertIs(result[0]["is_overdue"], True)
        # 已提交反馈后不再视为逾期
        self.interviewer_service.submit_interview_feedback(interview["id"], {"status": "PASSED", "feedback": "ok"})
        result = self.interviewer_service.list_my_interviews()
        self.assertIs(result[0]["is_overdue"], False)

    def test_submit_feedback_saves_status_feedback_timestamp_and_audit(self):
        interview = self.admin.create_interview(self.assignment_id, {
            "interviewer_user_id": str(self.interviewer.id),
        })
        updated = self.interviewer_service.submit_interview_feedback(
            interview["id"], {"status": "PASSED", "feedback": "表现优秀"}
        )
        self.assertEqual(updated["status"], "PASSED")
        self.assertEqual(updated["feedback"], "表现优秀")
        self.assertIsNotNone(updated["feedback_submitted_at"])
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.interviewer.id,
                action="INTERVIEW_FEEDBACK", object_type="INTERVIEW", object_id=str(interview["id"]),
            ).exists()
        )

    def test_submit_feedback_rejects_non_interviewer(self):
        interview = self.admin.create_interview(self.assignment_id, {
            "interviewer_user_id": str(self.other.id),
        })
        with self.assertRaises(NotFound404):
            self.interviewer_service.submit_interview_feedback(interview["id"], {"status": "PASSED"})

    def test_submit_feedback_rejects_invalid_status(self):
        interview = self.admin.create_interview(self.assignment_id, {
            "interviewer_user_id": str(self.interviewer.id),
        })
        with self.assertRaisesRegex(AppApiException, "status is invalid"):
            self.interviewer_service.submit_interview_feedback(interview["id"], {"status": "CANCELLED"})

    def test_submit_feedback_again_updates_and_audits(self):
        interview = self.admin.create_interview(self.assignment_id, {
            "interviewer_user_id": str(self.interviewer.id),
        })
        self.interviewer_service.submit_interview_feedback(interview["id"], {"status": "PASSED", "feedback": "v1"})
        self.interviewer_service.submit_interview_feedback(interview["id"], {"status": "FAILED", "feedback": "v2"})
        row = Interview.objects.get(id=interview["id"])
        self.assertEqual(row.status, "FAILED")
        self.assertEqual(row.feedback, "v2")
        self.assertEqual(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="INTERVIEW_FEEDBACK", object_id=str(interview["id"]),
            ).count(), 2
        )

    def test_update_interview_changes_interviewer_and_syncs_name(self):
        interview = self.admin.create_interview(self.assignment_id, {})
        updated = self.admin.update_interview(interview["id"], {
            "interviewer_user_id": str(self.interviewer.id),
            "feedback_deadline": "2026-08-25T09:00:00Z",
        })
        self.assertEqual(updated["interviewer_user_id"], str(self.interviewer.id))
        self.assertEqual(updated["interviewer"], "面试官甲")
        self.assertIsNotNone(updated["feedback_deadline"])


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
        self.assertEqual(self.service.get_config(), {"llm_model_id": None, "rerank_model_id": None})

    @patch("hr.serializers.ai.get_model_by_id")
    def test_save_and_get_config(self, mock_get_model):
        mock_get_model.return_value = SimpleNamespace(model_type="LLM")
        saved = self.service.save_config({"llm_model_id": "model-1"})
        self.assertEqual(saved, {"llm_model_id": "model-1", "rerank_model_id": None})
        self.assertEqual(self.service.get_config(), {"llm_model_id": "model-1", "rerank_model_id": None})
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
        self.assertEqual(saved, {"llm_model_id": "model-1", "rerank_model_id": "rerank-1"})
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

    def test_merge_rejects_deleted_primary(self):
        self.service.delete_candidate(self.primary.id)
        with self.assertRaisesRegex(AppApiException, "deleted candidate cannot be merged"):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})

    def test_merge_rejects_deleted_secondary(self):
        self.service.delete_candidate(self.secondary.id)
        with self.assertRaisesRegex(AppApiException, "deleted candidate cannot be merged"):
            self.service.merge_candidates(str(self.primary.id), {"secondary_id": str(self.secondary.id)})


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
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)

    def test_delete_rejects_active_assignment(self):
        self.service.create_assignment(self.job.id, self.candidate.id, {})
        with self.assertRaisesRegex(AppApiException, "active assignment"):
            self.service.delete_candidate(self.candidate.id)

    def test_delete_rejects_hired_assignment(self):
        assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]
        self.service.update_assignment(assignment_id, {"status": "SCREEN_PASSED"})
        self.service.update_assignment(assignment_id, {"status": "INTERVIEWING"})
        self.service.update_assignment(assignment_id, {"status": "OFFER"})
        self.service.update_assignment(assignment_id, {"status": "HIRED"})
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
        assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]
        self.service.update_assignment(assignment_id, {"status": "REJECTED", "termination_reason": "NOT_FIT"})
        self.service.delete_candidate(self.candidate.id)
        assignment = CandidateAssignment.objects.get(id=assignment_id)
        self.assertEqual(assignment.candidate_id, self.candidate.id)
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
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)

    def test_restore_returns_active_and_allows_new_assignment(self):
        self.service.archive_candidate(self.candidate.id)
        result = self.service.restore_candidate(self.candidate.id)
        self.assertEqual(result["status"], "ACTIVE")
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.assertEqual(assignment["status"], "PENDING_SCREEN")

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
        assignment_id = self.service.create_assignment(self.job.id, self.candidate.id, {})["id"]
        self.service.update_assignment(assignment_id, {"status": "REJECTED", "termination_reason": "NOT_FIT"})
        self.service.archive_candidate(self.candidate.id)
        self.service.restore_candidate(self.candidate.id)
        assignment = CandidateAssignment.objects.get(id=assignment_id)
        self.assertEqual(assignment.status, "REJECTED")


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
        client = self._client(self.admin)
        candidate = Candidate.objects.create(name="Bob", workspace_id="workspace-a")
        job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        assignment_id = client.post(
            "/admin/api/workspace/workspace-a/hr/jobs/{}/assignments".format(job.id),
            {"candidate_id": str(candidate.id)},
            content_type="application/json",
        ).json()["data"]["id"]
        self.interview_id = client.post(
            "/admin/api/workspace/workspace-a/hr/assignments/{}/interviews".format(assignment_id),
            {"interviewer_user_id": str(self.interviewer.id)},
            content_type="application/json",
        ).json()["data"]["id"]

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
    """B2: Offer 工件状态机、版本、审批、附件与权限"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.service = OfferService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.recruitment = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        self.job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = self.recruitment.create_assignment(self.job.id, self.candidate.id, {})["id"]

    def _to_offer(self):
        self.recruitment.update_assignment(self.assignment_id, {"status": "SCREEN_PASSED"})
        self.recruitment.update_assignment(self.assignment_id, {"status": "INTERVIEWING"})
        self.recruitment.update_assignment(self.assignment_id, {"status": "OFFER"})

    def _sent_offer(self):
        self._to_offer()
        offer_id = self.service.create_offer(self.assignment_id, {"salary_amount": "25000", "currency": "CNY"})["id"]
        self.service.send_offer(offer_id)
        return offer_id

    def test_create_offer_requires_offer_assignment(self):
        with self.assertRaisesRegex(AppApiException, "not in offer status"):
            self.service.create_offer(self.assignment_id, {})

    def test_create_offer_auto_increments_version(self):
        self._to_offer()
        first = self.service.create_offer(self.assignment_id, {"salary_amount": "20000"})
        second = self.service.create_offer(self.assignment_id, {"salary_amount": "25000"})
        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["status"], "DRAFT")

    def test_create_offer_saves_amount_currency_and_note(self):
        self._to_offer()
        offer = self.service.create_offer(self.assignment_id, {
            "salary_amount": "30000.50", "currency": "USD", "note": "含期权",
        })
        self.assertEqual(offer["salary_amount"], "30000.50")
        self.assertEqual(offer["currency"], "USD")
        self.assertEqual(offer["note"], "含期权")

    def test_update_offer_only_in_draft(self):
        offer_id = self._sent_offer()
        with self.assertRaisesRegex(AppApiException, "draft offer"):
            self.service.update_offer(offer_id, {"salary_amount": "99999"})

    def test_approve_offer_writes_audit(self):
        self._to_offer()
        offer_id = self.service.create_offer(self.assignment_id, {})["id"]
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
        offer_id = self.service.create_offer(self.assignment_id, {})["id"]
        with self.assertRaisesRegex(AppApiException, "approval_status is invalid"):
            self.service.approve_offer(offer_id, {"approval_status": "NOPE"})

    def test_send_offer_marks_sent(self):
        self._to_offer()
        offer_id = self.service.create_offer(self.assignment_id, {})["id"]
        sent = self.service.send_offer(offer_id)
        self.assertEqual(sent["status"], "SENT")
        self.assertIsNotNone(sent["sent_at"])
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="OFFER_SEND", object_type="OFFER"
            ).exists()
        )

    def test_send_from_non_draft_rejected(self):
        offer_id = self._sent_offer()
        with self.assertRaisesRegex(AppApiException, "Illegal status transition"):
            self.service.send_offer(offer_id)

    def test_accept_offer_moves_assignment_to_hired(self):
        offer_id = self._sent_offer()
        accepted = self.service.accept_offer(offer_id)
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertIsNotNone(accepted["accepted_at"])
        assignment = CandidateAssignment.objects.get(id=self.assignment_id)
        self.assertEqual(assignment.status, "HIRED")
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.user_id, action="OFFER_ACCEPT", object_type="OFFER"
            ).exists()
        )
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", action="ASSIGNMENT_TRANSITION", object_type="ASSIGNMENT"
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

    def test_rejected_offer_allows_new_version_while_assignment_in_offer(self):
        offer_id = self._sent_offer()
        self.service.reject_offer(offer_id, {"note": "薪资未谈拢"})
        new_version = self.service.create_offer(self.assignment_id, {"salary_amount": "30000"})
        self.assertEqual(new_version["version"], 2)
        self.assertEqual(new_version["status"], "DRAFT")

    def test_no_new_offer_after_accepted(self):
        offer_id = self._sent_offer()
        self.service.accept_offer(offer_id)
        with self.assertRaisesRegex(AppApiException, "not in offer status"):
            self.service.create_offer(self.assignment_id, {"salary_amount": "30000"})

    def test_offer_cross_workspace_not_found(self):
        self._to_offer()
        offer_id = self.service.create_offer(self.assignment_id, {})["id"]
        foreign = OfferService(workspace_id="workspace-b", user_id=self.user_id, hr_role="ADMIN")
        with self.assertRaises(NotFound404):
            foreign.get_offer(offer_id)

    def test_operator_cannot_manage_offers(self):
        self._to_offer()
        operator = OfferService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            operator.create_offer(self.assignment_id, {})
        offer_id = self.service.create_offer(self.assignment_id, {})["id"]
        with self.assertRaises(AppUnauthorizedFailed):
            operator.accept_offer(offer_id)

    def test_attachment_upload_and_download_permission(self):
        self._to_offer()
        offer_id = self.service.create_offer(self.assignment_id, {})["id"]
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
    """B3: Offer 接受后幂等交接（CHECKLIST/WEBHOOK、失败重试、审计）"""

    def setUp(self):
        self.user_id = uuid.uuid7()
        self.offer_service = OfferService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.handoff_service = OnboardingService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.recruitment = RecruitmentService(workspace_id="workspace-a", user_id=self.user_id, hr_role="ADMIN")
        self.candidate = Candidate.objects.create(
            name="Alice", workspace_id="workspace-a", phone="13812345678", email="alice@example.com"
        )
        self.job = Job.objects.create(
            name="Engineer", department="Engineering", workspace_id="workspace-a", headcount=1
        )
        self.assignment_id = self.recruitment.create_assignment(self.job.id, self.candidate.id, {})["id"]
        for status in ("SCREEN_PASSED", "INTERVIEWING", "OFFER"):
            self.recruitment.update_assignment(self.assignment_id, {"status": status})
        self.offer_id = self.offer_service.create_offer(
            self.assignment_id, {"salary_amount": "25000", "currency": "CNY"}
        )["id"]
        self.offer_service.send_offer(self.offer_id)

    def test_accept_creates_handoff_with_full_payload(self):
        self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(assignment_id=self.assignment_id)
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
        self.assertEqual(OnboardingHandoff.objects.filter(assignment_id=self.assignment_id).count(), 1)

    def test_webhook_success(self):
        HrConfig.objects.update_or_create(
            workspace_id="workspace-a",
            defaults={"handoff_target_type": "WEBHOOK", "handoff_webhook_url": "https://hris.example.com/hires"},
        )
        with patch("hr.serializers.offer.urlopen") as urlopen:
            response = type("Response", (), {"status": 200, "read": lambda self: b'{"ok": true}'})()
            urlopen.return_value = response
            self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(assignment_id=self.assignment_id)
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
        handoff = OnboardingHandoff.objects.get(assignment_id=self.assignment_id)
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
            handoff = OnboardingHandoff.objects.get(assignment_id=self.assignment_id)
            self.assertEqual(handoff.status, HandoffStatus.FAILED)
            retried = self.handoff_service.retry_handoff(handoff.id)
        self.assertEqual(retried["status"], "SUCCESS")
        handoff.refresh_from_db()
        self.assertEqual(handoff.attempts, 2)

    def test_retry_success_handoff_rejected(self):
        self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(assignment_id=self.assignment_id)
        with self.assertRaisesRegex(AppApiException, "failed handoff"):
            self.handoff_service.retry_handoff(handoff.id)

    def test_handoff_cross_workspace_not_found(self):
        self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(assignment_id=self.assignment_id)
        foreign = OnboardingService(workspace_id="workspace-b", user_id=self.user_id, hr_role="ADMIN")
        with self.assertRaises(NotFound404):
            foreign.retry_handoff(handoff.id)

    def test_operator_cannot_retry(self):
        self.offer_service.accept_offer(self.offer_id)
        handoff = OnboardingHandoff.objects.get(assignment_id=self.assignment_id)
        operator = OnboardingService(workspace_id="workspace-a", user_id=uuid.uuid7(), hr_role="OPERATOR")
        with self.assertRaises(AppUnauthorizedFailed):
            operator.retry_handoff(handoff.id)


class OfferApiTests(_HrApiBase):
    """B2 路由：Offer 全链路与权限"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        self.recruitment = RecruitmentService(workspace_id="workspace-a", user_id=self.admin.id, hr_role="ADMIN")
        candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a")
        job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = self.recruitment.create_assignment(job.id, candidate.id, {})["id"]
        for status in ("SCREEN_PASSED", "INTERVIEWING", "OFFER"):
            self.recruitment.update_assignment(self.assignment_id, {"status": status})
        self.client_admin = self._client(self.admin)

    def test_full_offer_flow_via_api(self):
        path = "/admin/api/workspace/workspace-a/hr/assignments/{}/offers".format(self.assignment_id)
        offer_id = self.client_admin.post(
            path, {"salary_amount": "25000", "currency": "CNY"}, content_type="application/json"
        ).json()["data"]["id"]
        self.client_admin.put("/admin/api/workspace/workspace-a/hr/offers/{}/approve".format(offer_id),
                              {"approval_status": "APPROVED", "approver_id": str(self.admin.id)},
                              content_type="application/json")
        self.client_admin.put("/admin/api/workspace/workspace-a/hr/offers/{}/send".format(offer_id))
        accepted = self.client_admin.put("/admin/api/workspace/workspace-a/hr/offers/{}/accept".format(offer_id))
        self.assertEqual(accepted.json()["data"]["status"], "ACCEPTED")
        assignment = self.client_admin.get(
            "/admin/api/workspace/workspace-a/hr/assignments/{}/interviews".format(self.assignment_id)
        )
        self.assertEqual(assignment.status_code, 200)
        from hr.models import CandidateAssignment as _CA
        self.assertEqual(_CA.objects.get(id=self.assignment_id).status, "HIRED")

    def test_operator_offer_create_gets_403(self):
        response = self._client(self.operator).post(
            "/admin/api/workspace/workspace-a/hr/assignments/{}/offers".format(self.assignment_id),
            {}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            HrAuditLog.objects.filter(
                workspace_id="workspace-a", user_id=self.operator.id, action="ACCESS_DENIED", result="DENIED"
            ).exists()
        )

    def test_attachment_upload_and_download(self):
        path = "/admin/api/workspace/workspace-a/hr/assignments/{}/offers".format(self.assignment_id)
        offer_id = self.client_admin.post(path, {}, content_type="application/json").json()["data"]["id"]
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
    """B3 路由：交接列表/重试/配置"""

    def setUp(self):
        self.admin = self._user("hr-admin", "HR Admin")
        self.operator = self._user("hr-operator", "HR Operator")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.admin.id, role="ADMIN")
        HrAccess.objects.create(workspace_id="workspace-a", user_id=self.operator.id, role="OPERATOR")
        recruitment = RecruitmentService(workspace_id="workspace-a", user_id=self.admin.id, hr_role="ADMIN")
        candidate = Candidate.objects.create(name="Alice", workspace_id="workspace-a", phone="13812345678")
        job = Job.objects.create(name="Engineer", workspace_id="workspace-a", headcount=1)
        self.assignment_id = recruitment.create_assignment(job.id, candidate.id, {})["id"]
        for status in ("SCREEN_PASSED", "INTERVIEWING", "OFFER"):
            recruitment.update_assignment(self.assignment_id, {"status": status})
        offer = OfferService(workspace_id="workspace-a", user_id=self.admin.id, hr_role="ADMIN")
        self.offer_id = offer.create_offer(self.assignment_id, {})["id"]
        offer.send_offer(self.offer_id)
        offer.accept_offer(self.offer_id)
        self.handoff = OnboardingHandoff.objects.get(assignment_id=self.assignment_id)

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

    def test_prefilter_skills_exists(self):
        """T7：技能维度接入预筛——LLM 解析 1 个技能 → phrase 模式 → candidate_skill EXISTS 限定候选集。"""
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
        self.assertTrue(result["meta"]["prefilter"]["applied"])
        self.assertEqual(result["meta"]["prefilter"]["candidate_count"], 1)  # 仅 java 候选人
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

