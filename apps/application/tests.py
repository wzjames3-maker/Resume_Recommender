import uuid_utils.compat as uuid
from django.test import SimpleTestCase, TestCase
from langchain_core.messages import AIMessage
from unittest.mock import patch
from rest_framework.exceptions import ValidationError

from application.api.application_api import ApplicationCreateAPI
from application.chat_pipeline.step.chat_step.impl.base_chat_step import BaseChatStep
from application.models import Application, ApplicationTypeChoices, ApplicationVersion
from application.serializers.application import ApplicationCreateSerializer
from application.serializers.common import ChatInfo
from common.exception.app_exception import ChatException
from common.job.scheduler import clean_removed_trigger_jobs


class FakeChatModel:
    def invoke(self, messages):
        return AIMessage(content="ok")


class SimpleChatRuntimeTests(SimpleTestCase):
    def test_block_chat_does_not_call_removed_mcp_handler(self):
        result, is_ai_chat = BaseChatStep().get_block_result(
            message_list=[],
            chat_model=FakeChatModel(),
            paragraph_list=[],
            no_references_setting={"status": "ai_questioning"},
            problem_text="question",
        )

        self.assertTrue(is_ai_chat)
        self.assertEqual(result.content, "ok")


class WorkflowApplicationRejectionTests(TestCase):
    def setUp(self):
        self.app = Application.objects.create(
            id=uuid.uuid7(),
            name="legacy-workflow-app",
            type=ApplicationTypeChoices.WORK_FLOW,
            workspace_id="default",
            user_id=None,
        )

    def _chat_info(self, debug):
        return ChatInfo(
            chat_id="",
            chat_user_id="",
            chat_user_type="ANONYMOUS_USER",
            ip_address="",
            source={},
            knowledge_id_list=[],
            exclude_document_id_list=[],
            application_id=str(self.app.id),
            debug=debug,
        )

    def test_debug_chat_rejects_workflow_application(self):
        with self.assertRaisesRegex(ChatException, "not supported"):
            self._chat_info(debug=True).get_application()

    def test_published_chat_rejects_workflow_application(self):
        ApplicationVersion.objects.create(
            id=uuid.uuid7(),
            application_id=self.app.id,
            workspace_id="default",
            application_name="legacy-workflow-app",
            type=ApplicationTypeChoices.WORK_FLOW,
            user_id=None,
        )
        with self.assertRaisesRegex(ChatException, "not supported"):
            self._chat_info(debug=False).get_application()


class ApplicationCreateValidationTests(TestCase):
    def test_create_schema_excludes_workflow_field(self):
        request = ApplicationCreateAPI.get_request()
        self.assertNotIn("work_flow", request().get_fields())

    def _payload(self, app_type):
        return {
            "name": "new-app",
            "desc": "",
            "folder_id": "default",
            "model_id": None,
            "dialogue_number": 0,
            "prologue": "",
            "knowledge_id_list": [],
            "knowledge_setting": {
                "top_n": 3,
                "similarity": 0.6,
                "max_paragraph_char_number": 5000,
                "search_mode": "embedding",
                "no_references_setting": {"status": "ai_questioning", "value": "{question}"},
            },
            "model_setting": {
                "prompt": "prompt",
                "system": "",
                "no_references_prompt": "{question}",
                "reasoning_content_enable": False,
            },
            "problem_optimization": False,
            "problem_optimization_prompt": "optimize",
            "type": app_type,
        }

    def test_workflow_type_is_rejected(self):
        serializer = ApplicationCreateSerializer.SimplateRequest(
            data=self._payload(ApplicationTypeChoices.WORK_FLOW)
        )
        with self.assertRaisesRegex(ValidationError, "WORK_FLOW"):
            serializer.is_valid(raise_exception=False)

    def test_simple_type_is_accepted(self):
        serializer = ApplicationCreateSerializer.SimplateRequest(data=self._payload(ApplicationTypeChoices.SIMPLE))
        serializer.is_valid(user_id=uuid.uuid7(), raise_exception=True)


class TriggerJobCleanupTests(SimpleTestCase):
    @patch("django_apscheduler.models.DjangoJob.objects")
    def test_cleanup_filters_trigger_prefix_only(self, mock_objects):
        clean_removed_trigger_jobs()
        mock_objects.filter.assert_called_once_with(id__startswith="trigger:")
        mock_objects.filter.return_value.delete.assert_called_once()