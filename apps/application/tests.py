from django.test import SimpleTestCase
from langchain_core.messages import AIMessage

from application.chat_pipeline.step.chat_step.impl.base_chat_step import BaseChatStep


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