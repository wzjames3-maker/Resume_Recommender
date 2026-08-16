import uuid_utils.compat as uuid
from django.test import SimpleTestCase, TestCase
from langchain_core.messages import AIMessage
from unittest.mock import patch
from rest_framework.exceptions import ValidationError

from application.api.application_api import ApplicationCreateAPI
from application.chat_pipeline.step.chat_step.impl.base_chat_step import BaseChatStep
from application.models import Application, ApplicationFolder, ApplicationTypeChoices, ApplicationVersion
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


class ChatStepExceptionTextTests(SimpleTestCase):
    """K3：模型异常时回答内容为通用文案，不泄露内部异常细节（修复前为 "Exception:"+str(e) 直出）。"""

    class _BoomModel:
        def invoke(self, messages):
            raise RuntimeError("secret internal detail: db connection refused")

    class _FakePostHandler:
        def handler(self, *args, **kwargs):
            pass

    def test_block_failure_returns_generic_message(self):
        from application.chat_pipeline.step.chat_step.impl.base_chat_step import BaseChatStep

        captured = {}

        class FakeToResponse:
            def to_block_response(self, *args, **kwargs):
                captured["text"] = args[2]
                return "RESP"

        class FakeManage:
            context = {"application_id": None, "start_time": __import__("time").time(),
                       "run_time": 0, "message_tokens": 0, "answer_tokens": 0}
            debug = True

            def get_base_to_response(self):
                return FakeToResponse()

        step = BaseChatStep()
        step.context = {"start_time": __import__("time").time(), "message_tokens": 0, "answer_tokens": 0}
        step.execute_block(
            message_list=[],
            chat_id="c1",
            problem_text="p",
            post_response_handler=self._FakePostHandler(),
            chat_model=self._BoomModel(),
            paragraph_list=[],
            manage=FakeManage(),
            no_references_setting={"status": "ai_questioning"},
            model_setting={},
        )
        self.assertNotIn("Exception:", captured["text"])
        self.assertNotIn("secret internal detail", captured["text"])
        self.assertIn("Sorry", captured["text"])


class WorkflowApplicationRejectionTests(TestCase):
    def setUp(self):
        ApplicationFolder.objects.create(id="default", name="root", workspace_id="default")
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


class ApplicationInsertMappingTests(TestCase):
    def setUp(self):
        ApplicationFolder.objects.create(id="default", name="root", workspace_id="default")
        from knowledge.models import KnowledgeFolder
        KnowledgeFolder.objects.create(id="default", name="root", workspace_id="default")

    def test_insert_simple_creates_application_and_access_token(self):
        from application.models import ApplicationAccessToken
        from application.serializers.application import ApplicationSerializer
        from system_manage.models import WorkspaceUserResourcePermission
        from users.models import User

        user = User.objects.create(username="app-insert-test", nick_name="t", role="ADMIN")
        payload = {
            "name": "insert-test-app",
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
            "type": "SIMPLE",
        }
        result = ApplicationSerializer(
            data={"workspace_id": "default", "user_id": str(user.id)}
        ).insert(payload)
        app = Application.objects.get(id=result["id"])
        self.assertEqual(app.name, "insert-test-app")
        self.assertTrue(ApplicationAccessToken.objects.filter(application_id=app.id).exists())
        self.assertTrue(
            WorkspaceUserResourcePermission.objects.filter(target=str(app.id), user_id=user.id).exists()
        )

    def test_insert_simple_creates_knowledge_mapping(self):
        from application.serializers.application import ApplicationSerializer
        from knowledge.models import Knowledge
        from system_manage.models.resource_mapping import ResourceMapping
        from users.models import User

        user = User.objects.create(username="app-insert-mapping-test", nick_name="t", role="ADMIN")
        knowledge = Knowledge.objects.create(
            id=uuid.uuid7(), name="kb", desc="", workspace_id="default", user_id=user.id
        )
        payload = {
            "name": "insert-mapping-test-app",
            "desc": "",
            "folder_id": "default",
            "model_id": None,
            "dialogue_number": 0,
            "prologue": "",
            "knowledge_id_list": [str(knowledge.id)],
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
            "type": "SIMPLE",
        }
        result = ApplicationSerializer(
            data={"workspace_id": "default", "user_id": str(user.id)}
        ).insert(payload)
        mapping = ResourceMapping.objects.filter(source_id=result["id"], source_type="APPLICATION").first()
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.target_id, str(knowledge.id))

    def test_publish_creates_application_version(self):
        from application.models import ApplicationVersion
        from application.serializers.application import ApplicationOperateSerializer, ApplicationSerializer
        from users.models import User

        user = User.objects.create(username="app-publish-test", nick_name="t", role="ADMIN")
        payload = {
            "name": "publish-test-app",
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
            "type": "SIMPLE",
        }
        result = ApplicationSerializer(
            data={"workspace_id": "default", "user_id": str(user.id)}
        ).insert(payload)
        ApplicationOperateSerializer(
            data={"application_id": result["id"], "user_id": str(user.id), "workspace_id": "default"}
        ).publish({})
        app = Application.objects.get(id=result["id"])
        self.assertTrue(app.is_publish)
        self.assertEqual(ApplicationVersion.objects.filter(application_id=app.id).count(), 1)


class TriggerJobCleanupTests(SimpleTestCase):
    @patch("django_apscheduler.models.DjangoJob.objects")
    def test_cleanup_filters_trigger_prefix_only(self, mock_objects):
        clean_removed_trigger_jobs()
        mock_objects.filter.assert_called_once_with(id__startswith="trigger:")
        mock_objects.filter.return_value.delete.assert_called_once()
