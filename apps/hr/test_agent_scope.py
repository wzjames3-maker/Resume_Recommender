import uuid_utils.compat as uuid
from django.test import TestCase

from hr.agents.scope import candidate_document_ids, normalize_resume_database_ids
from hr.models import Candidate, ResumeDatabase, ResumeDatabaseMembership, ResumeFile


class AgentResumeScopeTests(TestCase):
    def setUp(self):
        self.workspace_id = "agent-scope"
        self.candidate = Candidate.objects.create(
            workspace_id=self.workspace_id,
            name="Scope Candidate",
        )
        self.total = ResumeDatabase.objects.create(
            workspace_id=self.workspace_id,
            name="总库",
            is_default=True,
            is_system=True,
        )
        self.business = ResumeDatabase.objects.create(
            workspace_id=self.workspace_id,
            name="业务库",
        )
        self.total_resume = self._resume("total")
        self.business_resume = self._resume("business")
        ResumeDatabaseMembership.objects.create(resume_file=self.business_resume, resume_database=self.business)

    def _resume(self, suffix):
        return ResumeFile.objects.create(
            workspace_id=self.workspace_id,
            file_name=f"{suffix}.txt",
            extension="txt",
            file_path=f"resume/{suffix}.txt",
            file_size=1,
            sha256=(suffix * 64)[:64],
            resume_database=self.total,
            candidate=self.candidate,
            document_id=uuid.uuid7(),
        )

    def test_normalize_database_ids_deduplicates_repeated_values(self):
        self.assertEqual(
            normalize_resume_database_ids([str(self.business.id), str(self.business.id)]),
            [str(self.business.id)],
        )

    def test_direct_resume_create_gets_total_membership(self):
        resume = ResumeFile.objects.create(
            workspace_id=self.workspace_id,
            file_name="direct.txt",
            extension="txt",
            file_path="resume/direct.txt",
            file_size=1,
            sha256=("direct" * 64)[:64],
            document_id=uuid.uuid7(),
        )
        self.assertEqual(resume.resume_database_id, self.total.id)
        self.assertTrue(
            ResumeDatabaseMembership.objects.filter(resume_file=resume, resume_database=self.total).exists()
        )

    def test_candidate_scope_uses_memberships(self):
        all_documents = set(candidate_document_ids(self.workspace_id, self.candidate.id))
        business_documents = set(
            candidate_document_ids(self.workspace_id, self.candidate.id, [str(self.business.id)])
        )
        self.assertEqual(all_documents, {str(self.total_resume.document_id), str(self.business_resume.document_id)})
        self.assertEqual(business_documents, {str(self.business_resume.document_id)})
