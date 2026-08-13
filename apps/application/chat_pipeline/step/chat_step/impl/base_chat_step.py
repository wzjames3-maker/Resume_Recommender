# coding=utf-8
"""
@project: maxkb
@Author：虎
@file： base_chat_step.py
@date：2024/1/9 18:25
@desc: 对话step Base实现
"""

import json
import time
import traceback
from typing import List

import uuid_utils.compat as uuid
from application.chat_pipeline.I_base_chat_pipeline import ParagraphPipelineModel
from application.chat_pipeline.pipeline_manage import PipelineManage
from application.chat_pipeline.step.chat_step.i_chat_step import IChatStep, PostResponseHandler
from application.models import (
    ApplicationChatUserStats,
    ApplicationLongTermMemory,
    ChatUserType,
)
from common.exception.app_exception import AppApiException
from common.utils.logger import maxkb_logger
from django.db.models import QuerySet
from django.http import StreamingHttpResponse
from django.utils.translation import gettext as _
from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from models_provider.tools import get_model_instance_by_model_workspace_id
from rest_framework import status


class Reasoning:
    def __init__(self, reasoning_content_start, reasoning_content_end):
        self.content = ""
        self.reasoning_content = ""
        self.all_content = ""
        self.reasoning_content_start_tag = reasoning_content_start
        self.reasoning_content_end_tag = reasoning_content_end
        self.reasoning_content_start_tag_len = (
            len(reasoning_content_start) if reasoning_content_start is not None else 0
        )
        self.reasoning_content_end_tag_len = len(reasoning_content_end) if reasoning_content_end is not None else 0
        self.reasoning_content_end_tag_prefix = (
            reasoning_content_end[0] if self.reasoning_content_end_tag_len > 0 else ""
        )
        self.reasoning_content_is_start = False
        self.reasoning_content_is_end = False
        self.reasoning_content_chunk = ""

    def get_end_reasoning_content(self):
        if not self.reasoning_content_is_start and not self.reasoning_content_is_end:
            r = {"content": self.all_content, "reasoning_content": ""}
            self.reasoning_content_chunk = ""
            return r
        if self.reasoning_content_is_start and not self.reasoning_content_is_end:
            r = {"content": "", "reasoning_content": self.reasoning_content_chunk}
            self.reasoning_content_chunk = ""
            return r
        return {"content": "", "reasoning_content": ""}

    def _normalize_content(self, content):
        """将不同类型的内容统一转换为字符串"""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # 处理包含多种内容类型的列表
            normalized_parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        normalized_parts.append(item.get("text", ""))
            return "".join(normalized_parts)
        else:
            return str(content)

    def get_reasoning_content(self, chunk):
        # 如果没有开始思考过程标签那么就全是结果
        if self.reasoning_content_start_tag is None or len(self.reasoning_content_start_tag) == 0:
            self.content += chunk.content
            return {"content": chunk.content, "reasoning_content": ""}
        # 如果没有结束思考过程标签那么就全部是思考过程
        if self.reasoning_content_end_tag is None or len(self.reasoning_content_end_tag) == 0:
            return {"content": "", "reasoning_content": chunk.content}
        chunk.content = self._normalize_content(chunk.content)
        self.all_content += chunk.content
        if not self.reasoning_content_is_start and len(self.all_content) >= self.reasoning_content_start_tag_len:
            if self.all_content.startswith(self.reasoning_content_start_tag):
                self.reasoning_content_is_start = True
                self.reasoning_content_chunk = self.all_content[self.reasoning_content_start_tag_len :]
            else:
                if not self.reasoning_content_is_end:
                    self.reasoning_content_is_end = True
                    self.content += self.all_content
                    return {
                        "content": self.all_content,
                        "reasoning_content": chunk.additional_kwargs.get("reasoning_content", "")
                        if chunk.additional_kwargs
                        else "",
                    }
        else:
            if self.reasoning_content_is_start:
                self.reasoning_content_chunk += chunk.content
        reasoning_content_end_tag_prefix_index = self.reasoning_content_chunk.find(
            self.reasoning_content_end_tag_prefix
        )
        if self.reasoning_content_is_end:
            self.content += chunk.content
            return {
                "content": chunk.content,
                "reasoning_content": chunk.additional_kwargs.get("reasoning_content", "")
                if chunk.additional_kwargs
                else "",
            }
        # 是否包含结束
        if reasoning_content_end_tag_prefix_index > -1:
            if (
                len(self.reasoning_content_chunk) - reasoning_content_end_tag_prefix_index
                >= self.reasoning_content_end_tag_len
            ):
                reasoning_content_end_tag_index = self.reasoning_content_chunk.find(self.reasoning_content_end_tag)
                if reasoning_content_end_tag_index > -1:
                    reasoning_content_chunk = self.reasoning_content_chunk[0:reasoning_content_end_tag_index]
                    content_chunk = self.reasoning_content_chunk[
                        reasoning_content_end_tag_index + self.reasoning_content_end_tag_len :
                    ]
                    self.reasoning_content += reasoning_content_chunk
                    self.content += content_chunk
                    self.reasoning_content_chunk = ""
                    self.reasoning_content_is_end = True
                    return {"content": content_chunk, "reasoning_content": reasoning_content_chunk}
        self.reasoning_content += self.reasoning_content_chunk
        self.reasoning_content_chunk = ""
        return {"content": "", "reasoning_content": ""}


def add_access_num(chat_user_id=None, chat_user_type=None, application_id=None):
    if [ChatUserType.ANONYMOUS_USER.value, ChatUserType.CHAT_USER.value].__contains__(
        chat_user_type
    ) and application_id is not None:
        application_public_access_client = (
            QuerySet(ApplicationChatUserStats)
            .filter(chat_user_id=chat_user_id, chat_user_type=chat_user_type, application_id=application_id)
            .first()
        )
        if application_public_access_client is not None:
            application_public_access_client.access_num = application_public_access_client.access_num + 1
            application_public_access_client.intraday_access_num = (
                application_public_access_client.intraday_access_num + 1
            )
            application_public_access_client.save()


def write_context(step, manage, request_token, response_token, all_text):
    step.context["message_tokens"] = request_token
    step.context["answer_tokens"] = response_token
    current_time = time.time()
    step.context["answer_text"] = all_text
    step.context["run_time"] = current_time - step.context["start_time"]
    manage.context["run_time"] = current_time - manage.context["start_time"]
    manage.context["message_tokens"] = manage.context["message_tokens"] + request_token
    manage.context["answer_tokens"] = manage.context["answer_tokens"] + response_token


def event_content(
    response,
    chat_id,
    chat_record_id,
    paragraph_list: List[ParagraphPipelineModel],
    post_response_handler: PostResponseHandler,
    manage,
    step,
    chat_model,
    message_list: List[BaseMessage],
    problem_text: str,
    padding_problem_text: str = None,
    chat_user_id=None,
    chat_user_type=None,
    is_ai_chat: bool = None,
    model_setting=None,
):
    if model_setting is None:
        model_setting = {}
    reasoning_content_enable = model_setting.get("reasoning_content_enable", False)
    reasoning_content_start = model_setting.get("reasoning_content_start", "<think>")
    reasoning_content_end = model_setting.get("reasoning_content_end", "</think>")
    reasoning = Reasoning(reasoning_content_start, reasoning_content_end)
    all_text = ""
    reasoning_content = ""
    try:
        response_reasoning_content = False
        for chunk in response:
            reasoning_chunk = reasoning.get_reasoning_content(chunk)
            content_chunk = reasoning_chunk.get("content")
            if "reasoning_content" in chunk.additional_kwargs:
                response_reasoning_content = True
                reasoning_content_chunk = chunk.additional_kwargs.get("reasoning_content", "")
            else:
                reasoning_content_chunk = reasoning_chunk.get("reasoning_content")
            content_chunk = reasoning._normalize_content(content_chunk)
            all_text += content_chunk
            if reasoning_content_chunk is None:
                reasoning_content_chunk = ""
            reasoning_content += reasoning_content_chunk
            yield manage.get_base_to_response().to_stream_chunk_response(
                chat_id,
                str(chat_record_id),
                "ai-chat-node",
                [],
                content_chunk,
                False,
                0,
                0,
                {
                    "node_is_end": False,
                    "view_type": "many_view",
                    "node_type": "ai-chat-node",
                    "real_node_id": "ai-chat-node",
                    "reasoning_content": reasoning_content_chunk if reasoning_content_enable else "",
                },
            )
        reasoning_chunk = reasoning.get_end_reasoning_content()
        all_text += reasoning_chunk.get("content")
        reasoning_content_chunk = ""
        if not response_reasoning_content:
            reasoning_content_chunk = reasoning_chunk.get("reasoning_content")
        yield manage.get_base_to_response().to_stream_chunk_response(
            chat_id,
            str(chat_record_id),
            "ai-chat-node",
            [],
            reasoning_chunk.get("content"),
            False,
            0,
            0,
            {
                "node_is_end": False,
                "view_type": "many_view",
                "node_type": "ai-chat-node",
                "real_node_id": "ai-chat-node",
                "reasoning_content": reasoning_content_chunk if reasoning_content_enable else "",
            },
        )
        # 获取token
        if is_ai_chat:
            try:
                request_token = chat_model.get_num_tokens_from_messages(message_list)
                response_token = chat_model.get_num_tokens(all_text)
            except Exception as e:
                request_token = 0
                response_token = 0
        else:
            request_token = 0
            response_token = 0
        write_context(step, manage, request_token, response_token, all_text)
        post_response_handler.handler(
            chat_id,
            chat_record_id,
            paragraph_list,
            problem_text,
            all_text,
            manage,
            step,
            padding_problem_text,
            reasoning_content=reasoning_content if reasoning_content_enable else "",
        )
        yield manage.get_base_to_response().to_stream_chunk_response(
            chat_id,
            str(chat_record_id),
            "ai-chat-node",
            [],
            "",
            True,
            request_token,
            response_token,
            {"node_is_end": True, "view_type": "many_view", "node_type": "ai-chat-node"},
        )
        if not manage.debug:
            add_access_num(chat_user_id, chat_user_type, manage.context.get("application_id"))
    except BaseException as e:
        if isinstance(e, GeneratorExit):
            maxkb_logger.error(f"Generator was closed (client disconnected)")
        else:
            maxkb_logger.error(f"{str(e)}:{traceback.format_exc()}")
            all_text = "Exception:" + str(e)
        write_context(step, manage, 0, 0, all_text)
        post_response_handler.handler(
            chat_id,
            chat_record_id,
            paragraph_list,
            problem_text,
            all_text,
            manage,
            step,
            padding_problem_text,
            reasoning_content=reasoning_content if reasoning_content_enable else "",
        )
        if not manage.debug:
            add_access_num(chat_user_id, chat_user_type, manage.context.get("application_id"))
        yield manage.get_base_to_response().to_stream_chunk_response(
            chat_id,
            str(chat_record_id),
            "ai-chat-node",
            [],
            all_text,
            False,
            0,
            0,
            {
                "node_is_end": False,
                "view_type": "many_view",
                "node_type": "ai-chat-node",
                "real_node_id": "ai-chat-node",
                "reasoning_content": "",
            },
        )


class BaseChatStep(IChatStep):
    def execute(
        self,
        message_list: List[BaseMessage],
        chat_id,
        problem_text,
        post_response_handler: PostResponseHandler,
        model_id: str = None,
        workspace_id: str = None,
        paragraph_list=None,
        manage: PipelineManage = None,
        padding_problem_text: str = None,
        stream: bool = True,
        chat_user_id=None,
        chat_user_type=None,
        no_references_setting=None,
        model_params_setting=None,
        model_setting=None,
        mcp_tool_ids=None,
        mcp_servers="",
        mcp_source="referencing",
        tool_ids=None,
        application_ids=None,
        skill_tool_ids=None,
        mcp_output_enable=True,
        **kwargs,
    ):
        chat_model = (
            get_model_instance_by_model_workspace_id(model_id, workspace_id, **(model_params_setting or {}))
            if model_id is not None
            else None
        )
        if stream:
            return self.execute_stream(
                message_list,
                chat_id,
                problem_text,
                post_response_handler,
                chat_model,
                paragraph_list,
                manage,
                padding_problem_text,
                chat_user_id,
                chat_user_type,
                no_references_setting,
                model_setting,
                mcp_tool_ids,
                mcp_servers,
                mcp_source,
                tool_ids,
                application_ids,
                skill_tool_ids,
                workspace_id,
                mcp_output_enable,
            )
        else:
            return self.execute_block(
                message_list,
                chat_id,
                problem_text,
                post_response_handler,
                chat_model,
                paragraph_list,
                manage,
                padding_problem_text,
                chat_user_id,
                chat_user_type,
                no_references_setting,
                model_setting,
                mcp_tool_ids,
                mcp_servers,
                mcp_source,
                tool_ids,
                application_ids,
                skill_tool_ids,
                workspace_id,
                mcp_output_enable,
            )

    def get_details(self, manage, **kwargs):
        return {
            "status": self.status,
            "err_message": self.err_message,
            "step_type": "chat_step",
            "run_time": self.context.get("run_time") or 0,
            "model_id": str(manage.context["model_id"]),
            "message_list": self.reset_message_list(
                self.context["step_args"].get("message_list"), self.context.get("answer_text")
            ),
            "message_tokens": self.context.get("message_tokens"),
            "answer_tokens": self.context.get("answer_tokens"),
            "cost": 0,
        }

    @staticmethod
    def reset_message_list(message_list: List[BaseMessage], answer_text):
        result = [
            {
                "role": "user"
                if isinstance(message, HumanMessage)
                else ("system" if isinstance(message, SystemMessage) else "ai"),
                "content": message.content,
            }
            for message in message_list
        ]
        result.append({"role": "ai", "content": answer_text})
        return result

    def get_stream_result(
        self,
        message_list: List[BaseMessage],
        chat_model: BaseChatModel = None,
        paragraph_list=None,
        no_references_setting=None,
        problem_text=None,
        mcp_tool_ids=None,
        mcp_servers="",
        mcp_source="referencing",
        tool_ids=None,
        application_ids=None,
        skill_tool_ids=None,
        workspace_id=None,
        mcp_output_enable=True,
        agent_id=None,
        chat_id=None,
        chat_user_id=None,
        chat_user_type=None,
    ):
        if paragraph_list is None:
            paragraph_list = []
        directly_return_chunk_list = [
            AIMessageChunk(content=paragraph.content)
            for paragraph in paragraph_list
            if (
                paragraph.hit_handling_method == "directly_return"
                and paragraph.similarity >= paragraph.directly_return_similarity
            )
        ]
        if directly_return_chunk_list is not None and len(directly_return_chunk_list) > 0:
            return iter(directly_return_chunk_list), False
        elif len(paragraph_list) == 0 and no_references_setting.get("status") == "designated_answer":
            return iter(
                [AIMessageChunk(content=no_references_setting.get("value").replace("{question}", problem_text))]
            ), False
        if chat_model is None:
            return iter(
                [
                    AIMessageChunk(
                        _(
                            "Sorry, the AI model is not configured. Please go to the application to set up the AI model first."
                        )
                    )
                ]
            ), False
        else:
            user_system_prompt = None
            filtered_message_list = []
            long_term_memory = (
                QuerySet(ApplicationLongTermMemory).filter(chat_user_id=chat_user_id, application_id=agent_id).first()
            )
            if long_term_memory is not None:
                memory = long_term_memory.memory
            else:
                memory = ""

            # print(chat_user_id, chat_user_type)
            for msg in message_list:
                if isinstance(msg, SystemMessage):
                    if isinstance(msg.content, str):
                        user_system_prompt = msg.content.replace("{memory}", memory)
                        msg.content = user_system_prompt
                    elif isinstance(msg.content, list):
                        user_system_prompt = "".join(
                            item.get("text", "") if isinstance(item, dict) else str(item) for item in msg.content
                        )
                    else:
                        user_system_prompt = str(msg.content)
                else:
                    filtered_message_list.append(msg)
            return chat_model.stream(message_list), True

    def execute_stream(
        self,
        message_list: List[BaseMessage],
        chat_id,
        problem_text,
        post_response_handler: PostResponseHandler,
        chat_model: BaseChatModel = None,
        paragraph_list=None,
        manage: PipelineManage = None,
        padding_problem_text: str = None,
        chat_user_id=None,
        chat_user_type=None,
        no_references_setting=None,
        model_setting=None,
        mcp_tool_ids=None,
        mcp_servers="",
        mcp_source="referencing",
        tool_ids=None,
        application_ids=None,
        skill_tool_ids=None,
        workspace_id=None,
        mcp_output_enable=True,
    ):
        chat_result, is_ai_chat = self.get_stream_result(
            message_list,
            chat_model,
            paragraph_list,
            no_references_setting,
            problem_text,
            mcp_tool_ids,
            mcp_servers,
            mcp_source,
            tool_ids,
            application_ids,
            skill_tool_ids,
            workspace_id,
            mcp_output_enable,
            manage.context.get("application_id"),
            chat_id,
            chat_user_id,
            chat_user_type,
        )
        chat_record_id = (
            self.context.get("step_args", {}).get("chat_record_id")
            if self.context.get("step_args", {}).get("chat_record_id")
            else uuid.uuid7()
        )
        r = StreamingHttpResponse(
            streaming_content=event_content(
                chat_result,
                chat_id,
                chat_record_id,
                paragraph_list,
                post_response_handler,
                manage,
                self,
                chat_model,
                message_list,
                problem_text,
                padding_problem_text,
                chat_user_id,
                chat_user_type,
                is_ai_chat,
                model_setting,
            ),
            content_type="text/event-stream;charset=utf-8",
        )

        r["Cache-Control"] = "no-cache"
        return r

    def get_block_result(
        self,
        message_list: List[BaseMessage],
        chat_model: BaseChatModel = None,
        paragraph_list=None,
        no_references_setting=None,
        problem_text=None,
        mcp_tool_ids=None,
        mcp_servers="",
        mcp_source="referencing",
        tool_ids=None,
        application_ids=None,
        skill_tool_ids=None,
        workspace_id=None,
        mcp_output_enable=True,
        application_id=None,
        chat_id=None,
        chat_user_id=None,
        chat_user_type=None,
    ):
        if paragraph_list is None:
            paragraph_list = []
        directly_return_chunk_list = [
            AIMessageChunk(content=paragraph.content)
            for paragraph in paragraph_list
            if (
                paragraph.hit_handling_method == "directly_return"
                and paragraph.similarity >= paragraph.directly_return_similarity
            )
        ]
        if directly_return_chunk_list is not None and len(directly_return_chunk_list) > 0:
            return directly_return_chunk_list[0], False
        elif len(paragraph_list) == 0 and no_references_setting.get("status") == "designated_answer":
            return AIMessage(no_references_setting.get("value").replace("{question}", problem_text)), False
        if chat_model is None:
            return AIMessage(
                _("Sorry, the AI model is not configured. Please go to the application to set up the AI model first.")
            ), False
        else:
            return chat_model.invoke(message_list), True

    def execute_block(
        self,
        message_list: List[BaseMessage],
        chat_id,
        problem_text,
        post_response_handler: PostResponseHandler,
        chat_model: BaseChatModel = None,
        paragraph_list=None,
        manage: PipelineManage = None,
        padding_problem_text: str = None,
        chat_user_id=None,
        chat_user_type=None,
        no_references_setting=None,
        model_setting=None,
        mcp_tool_ids=None,
        mcp_servers="",
        mcp_source="referencing",
        tool_ids=None,
        application_ids=None,
        skill_tool_ids=None,
        workspace_id=None,
        mcp_output_enable=True,
    ):
        reasoning_content_enable = model_setting.get("reasoning_content_enable", False)
        reasoning_content_start = model_setting.get("reasoning_content_start", "<think>")
        reasoning_content_end = model_setting.get("reasoning_content_end", "</think>")
        reasoning = Reasoning(reasoning_content_start, reasoning_content_end)
        chat_record_id = uuid.uuid7()
        # 调用模型
        try:
            chat_result, is_ai_chat = self.get_block_result(
                message_list,
                chat_model,
                paragraph_list,
                no_references_setting,
                problem_text,
                mcp_tool_ids,
                mcp_servers,
                mcp_source,
                tool_ids,
                application_ids,
                skill_tool_ids,
                workspace_id,
                mcp_output_enable,
                manage.context.get("application_id"),
                chat_id,
                chat_user_id,
                chat_user_type,
            )
            if is_ai_chat:
                request_token = chat_model.get_num_tokens_from_messages(message_list)
                response_token = chat_model.get_num_tokens(chat_result.content)
            else:
                request_token = 0
                response_token = 0
            write_context(self, manage, request_token, response_token, chat_result.content)
            reasoning_result = reasoning.get_reasoning_content(chat_result)
            reasoning_result_end = reasoning.get_end_reasoning_content()
            content = reasoning_result.get("content") + reasoning_result_end.get("content")
            if "reasoning_content" in chat_result.response_metadata:
                reasoning_content = chat_result.response_metadata.get("reasoning_content", "") or ""
            else:
                reasoning_content = (reasoning_result.get("reasoning_content") or "") + (
                    reasoning_result_end.get("reasoning_content") or ""
                )
            post_response_handler.handler(
                chat_id,
                chat_record_id,
                paragraph_list,
                problem_text,
                content,
                manage,
                self,
                padding_problem_text,
                reasoning_content=reasoning_content,
            )
            if not manage.debug:
                add_access_num(chat_user_id, chat_user_type, manage.context.get("application_id"))
            return manage.get_base_to_response().to_block_response(
                str(chat_id),
                str(chat_record_id),
                content,
                True,
                request_token,
                response_token,
                {
                    "reasoning_content": reasoning_content if reasoning_content_enable else "",
                    "answer_list": [
                        {"content": content, "reasoning_content": reasoning_content if reasoning_content_enable else ""}
                    ],
                },
            )
        except Exception as e:
            all_text = "Exception:" + str(e)
            write_context(self, manage, 0, 0, all_text)
            post_response_handler.handler(
                chat_id,
                chat_record_id,
                paragraph_list,
                problem_text,
                all_text,
                manage,
                self,
                padding_problem_text,
                reasoning_content="",
            )
            if not manage.debug:
                add_access_num(chat_user_id, chat_user_type, manage.context.get("application_id"))
            return manage.get_base_to_response().to_block_response(
                str(chat_id), str(chat_record_id), all_text, True, 0, 0, _status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
