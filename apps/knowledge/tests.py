import uuid_utils.compat as uuid
from django.test import TestCase

from common.exception.app_exception import AppApiException
from knowledge.models import Knowledge
from knowledge.serializers.knowledge import KnowledgeSerializer


class WorkflowKnowledgeRejectionTests(TestCase):
    def setUp(self):
        self.knowledge = Knowledge.objects.create(
            id=uuid.uuid7(),
            name="legacy-workflow-kb",
            desc="",
            type=4,
            workspace_id="default",
            user_id=None,
            meta={"disabled_reason": "workflow_knowledge_removed_by_local_core"},
        )

    def test_operate_rejects_workflow_knowledge(self):
        serializer = KnowledgeSerializer.Operate(
            data={"user_id": str(uuid.uuid7()), "workspace_id": "default", "knowledge_id": str(self.knowledge.id)}
        )
        with self.assertRaisesRegex(AppApiException, "not supported"):
            serializer.is_valid(raise_exception=True)

    def test_hit_test_rejects_workflow_knowledge(self):
        serializer = KnowledgeSerializer.HitTest(
            data={
                "workspace_id": "default",
                "knowledge_id": str(self.knowledge.id),
                "query_text": "q",
                "top_number": 3,
                "similarity": 0.6,
                "search_mode": "embedding",
            }
        )
        with self.assertRaisesRegex(AppApiException, "not supported"):
            serializer.is_valid(raise_exception=True)