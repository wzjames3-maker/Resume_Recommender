from django.db import IntegrityError, transaction
from django.test import TestCase
import uuid_utils.compat as uuid

from common.exception.app_exception import AppApiException, AppUnauthorizedFailed, NotFound404
from hr.models import AssignmentStatus, Candidate, CandidateAssignment, Job, ResumeFile
from hr.serializers.recruitment import RecruitmentService
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
            self.service.update_assignment(assignment["id"], {"status": AssignmentStatus.PENDING_SCREEN})

    def test_closed_job_rejects_reactivating_assignment(self):
        assignment = self.service.create_assignment(self.job.id, self.candidate.id, {})
        self.service.update_assignment(assignment["id"], {"status": AssignmentStatus.REJECTED})
        self.service.edit_job(self.job.id, {"status": "CLOSED"})

        with self.assertRaisesRegex(AppApiException, "closed"):
            self.service.update_assignment(assignment["id"], {"status": AssignmentStatus.PENDING_SCREEN})


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
