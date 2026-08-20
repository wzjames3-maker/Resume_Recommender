from unittest.mock import patch

import uuid_utils.compat as uuid
from django.test import TestCase

from common.exception.app_exception import AppApiException
from hr.models import (
    Application,
    Candidate,
    HrAgentProposal,
    HrAgentRun,
    Interview,
    Job,
    ResumeFile,
)
from hr.serializers.recruitment import RecruitmentService
from hr.services.agent_workbench import get_evidence_paragraph, get_run, list_proposals, list_runs, retry_run
from knowledge.models import Document, Knowledge, KnowledgeFolder, KnowledgeScope, KnowledgeType, Paragraph


class AgentWorkbenchServiceTests(TestCase):
    def setUp(self):
        self.workspace_id = "agent-workbench"
        self.other_workspace = "other-workspace"
        self.user_id = uuid.uuid7()
        self.run = HrAgentRun.objects.create(
            workspace_id=self.workspace_id,
            agent_type="SCREENING",
            trigger_type="MANUAL",
            ref_object_type="APPLICATION",
            ref_object_id="application-1",
            status="FAILED",
            input_meta={
                "application_id": "application-1",
                "candidate_id": "candidate-1",
                "resume_database_ids": ["database-1"],
            },
            tool_trace=[{"tool": "structured_filter", "elapsed_ms": 12, "rows": 2}],
            error="LLM unavailable",
            llm_model="screening-model",
            prompt_tokens=10,
            completion_tokens=4,
            prompt_version="screening-v2",
            duration_ms=321,
            user_id=self.user_id,
        )
        self.proposal = HrAgentProposal.objects.create(
            workspace_id=self.workspace_id,
            run=self.run,
            target_type="APPLICATION",
            target_id="application-1",
            action="HOLD",
            payload_json={
                "decision": {"suggested_action": "HOLD"},
                "dimensions": [{
                    "name": "技能匹配",
                    "evidence": [{"paragraph_id": "p-1", "excerpt": "熟悉 Python", "relevance": 0.9}],
                }],
            },
        )
        HrAgentRun.objects.create(
            workspace_id=self.other_workspace,
            agent_type="SCREENING",
            trigger_type="MANUAL",
            ref_object_type="APPLICATION",
            ref_object_id="other-application",
            status="SUCCEEDED",
        )

    def test_list_runs_is_workspace_scoped_and_paginated(self):
        result = list_runs(self.workspace_id, {"current_page": "1", "page_size": "10"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["id"], str(self.run.id))
        self.assertEqual(result["records"][0]["total_tokens"], 14)
        self.assertEqual(result["records"][0]["status"], "FAILED")
        summary = result["summary"]
        self.assertEqual(summary["total_runs"], 1)
        self.assertEqual(summary["status_counts"]["FAILED"], 1)
        self.assertEqual(summary["total_tokens"], 14)
        self.assertGreater(summary["total_duration_ms"], 0)

    def test_run_filters_cover_trigger_target_search_and_date(self):
        result = list_runs(self.workspace_id, {
            "trigger_type": "MANUAL",
            "ref_object_type": "APPLICATION",
            "search": "application-1",
            "created_from": self.run.create_time.date().isoformat(),
            "created_to": self.run.create_time.date().isoformat(),
        })
        self.assertEqual(result["total"], 1)

    def test_list_interviews_service(self):
        candidate = Candidate.objects.create(
            workspace_id=self.workspace_id, name="面试候选人", phone="13800000000", skills=["Python"],
        )
        job = Job.objects.create(
            workspace_id=self.workspace_id, name="后端工程师", department="技术", status="OPEN",
            skill_requirements=["Python"],
        )
        application = Application.objects.create(
            workspace_id=self.workspace_id, candidate=candidate, job=job, status="ACTIVE",
        )
        Interview.objects.create(
            workspace_id=self.workspace_id,
            application=application,
            round_no=1,
            interviewer="面试官A",
            status="PENDING",
            feedback="整体匹配度较高",
        )
        service = RecruitmentService(
            workspace_id=self.workspace_id, user_id=self.user_id, hr_role="ADMIN"
        )
        result = service.list_interviews({"current_page": "1", "page_size": "10", "search": "后端工程师"})
        self.assertEqual(result["total"], 1)
        record = result["records"][0]
        self.assertEqual(record["candidate_name"], "面试候选人")
        self.assertEqual(record["job_name"], "后端工程师")
        self.assertEqual(record["interviewer"], "面试官A")
        self.assertEqual(record["feedback"], "整体匹配度较高")
        filtered = service.list_interviews({"current_page": "1", "page_size": "10", "status": "PASSED"})
        self.assertEqual(filtered["total"], 0)

    def test_evidence_paragraph_is_workspace_scoped_and_returns_source(self):
        KnowledgeFolder.objects.get_or_create(
            id="default", defaults={"name": "default", "workspace_id": "default"}
        )
        knowledge = Knowledge.objects.create(
            workspace_id=self.workspace_id,
            name="Resume evidence test",
            desc="",
            type=KnowledgeType.BASE.value,
            scope=KnowledgeScope.WORKSPACE.value,
        )
        document = Document.objects.create(
            knowledge=knowledge,
            name="candidate-resume.txt",
            char_length=20,
        )
        paragraph = Paragraph.objects.create(
            document=document,
            knowledge=knowledge,
            title="工作经历",
            content="负责 Python 服务开发。",
            position=2,
        )
        resume = ResumeFile.objects.create(
            workspace_id=self.workspace_id,
            file_name="candidate-resume.txt",
            extension="txt",
            file_path="/tmp/candidate-resume.txt",
            file_size=20,
            sha256="evidence-source-1",
            document_id=document.id,
        )
        result = get_evidence_paragraph(self.workspace_id, str(paragraph.id))
        self.assertEqual(result["resume_id"], str(resume.id))
        self.assertEqual(result["content"], "负责 Python 服务开发。")
        with self.assertRaisesMessage(AppApiException, "Evidence paragraph not found"):
            get_evidence_paragraph(self.other_workspace, str(paragraph.id))

    def test_detail_includes_trace_output_and_evidence(self):
        result = get_run(self.workspace_id, str(self.run.id))
        self.assertEqual(result["run"]["tool_trace"][0]["tool"], "structured_filter")
        self.assertEqual(result["proposals"][0]["id"], str(self.proposal.id))
        self.assertEqual(result["evidence"][0]["paragraph_id"], "p-1")

    def test_proposal_inbox_filters_by_status_and_agent(self):
        result = list_proposals(self.workspace_id, {"status": "PENDING", "agent_type": "SCREENING"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["records"][0]["action"], "HOLD")
        self.assertEqual(result["records"][0]["evidence_count"], 1)

    @patch("hr.services.agent_workbench.run_screening_agent")
    def test_retry_failed_run_delegates_without_overwriting_original(self, run_screening):
        run_screening.return_value = {"run_id": "new-run", "status": "SUCCEEDED"}
        result = retry_run(self.workspace_id, str(self.run.id), self.user_id)
        self.assertEqual(result["run_id"], "new-run")
        run_screening.assert_called_once_with(
            "application-1",
            trigger_type="MANUAL",
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            resume_database_ids=["database-1"],
        )
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, "FAILED")

    def test_retry_rejects_succeeded_run(self):
        self.run.status = "SUCCEEDED"
        self.run.save(update_fields=["status"])
        with self.assertRaisesMessage(AppApiException, "only FAILED or SKIPPED runs can be retried"):
            retry_run(self.workspace_id, str(self.run.id), self.user_id)
