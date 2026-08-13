# coding=utf-8
"""
@project: MaxKB
@Author：虎虎
@file： application.py
@date：2025/5/26 17:03
@desc:
"""

import hashlib
import json
import os
import re
from typing import Dict, List

import uuid_utils.compat as uuid
from application.models.application import Application, ApplicationFolder, ApplicationTypeChoices, ApplicationVersion
from application.models.application_access_token import ApplicationAccessToken
from application.serializers.common import update_resource_mapping_by_application
from common import result
from common.cache_data.application_access_token_cache import del_application_access_token
from common.database_model_manage.database_model_manage import DatabaseModelManage
from common.db.search import native_page_search, native_search
from common.exception.app_exception import AppApiException
from common.field.common import UploadedFileField
from common.utils.common import _remove_empty_lines, get_file_content
from common.utils.logger import maxkb_logger
from django.core import validators
from django.db import models, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from knowledge.models import Knowledge
from knowledge.serializers.common import BatchMoveSerializer, BatchSerializer
from knowledge.serializers.knowledge import KnowledgeModelSerializer, KnowledgeSerializer
from maxkb.conf import PROJECT_DIR
from models_provider.models import Model
from models_provider.tools import get_model_instance_by_model_workspace_id
from rest_framework import serializers, status
from rest_framework.utils.formatting import lazy_format
from system_manage.models import AuthTargetType, WorkspaceUserResourcePermission
from system_manage.models.resource_mapping import ResourceMapping
from system_manage.serializers.resource_mapping_serializers import ResourceMappingSerializer
from system_manage.serializers.user_resource_permission import UserResourcePermissionSerializer
from users.models import User
from users.serializers.user import is_workspace_manage, is_workspace_manage_permission_read

class ApplicationSerializerModel(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = "__all__"

class NoReferencesChoices(models.TextChoices):
    """订单类型"""

    ai_questioning = "ai_questioning", "ai回答"
    designated_answer = "designated_answer", "指定回答"

class NoReferencesSetting(serializers.Serializer):
    status = serializers.ChoiceField(required=True, choices=NoReferencesChoices.choices, label=_("No reference status"))
    value = serializers.CharField(required=True, label=_("Prompt word"))

class KnowledgeSettingSerializer(serializers.Serializer):
    top_n = serializers.FloatField(required=True, max_value=10000, min_value=1, label=_("Reference segment number"))
    similarity = serializers.FloatField(required=True, max_value=1, min_value=0, label=_("Acquaintance"))
    max_paragraph_char_number = serializers.IntegerField(
        required=True, min_value=500, max_value=100000, label=_("Maximum number of quoted characters")
    )
    search_mode = serializers.CharField(
        required=True,
        validators=[
            validators.RegexValidator(
                regex=re.compile("^embedding|keywords|blend$"),
                message=_("The type only supports embedding|keywords|blend"),
                code=500,
            )
        ],
        label=_("Retrieval Mode"),
    )

    no_references_setting = NoReferencesSetting(required=True, label=_("Segment settings not referenced"))

class ModelKnowledgeAssociation(serializers.Serializer):
    user_id = serializers.UUIDField(required=True, label=_("User ID"))
    model_id = serializers.CharField(required=False, allow_null=True, allow_blank=True, label=_("Model id"))
    knowledge_id_list = serializers.ListSerializer(
        required=False,
        child=serializers.UUIDField(required=True, label=_("Knowledge base id")),
        label=_("Knowledge Base List"),
    )

    def is_valid(self, *, raise_exception=True):
        super().is_valid(raise_exception=True)
        model_id = self.data.get("model_id")
        user_id = self.data.get("user_id")
        if model_id is not None and len(model_id) > 0:
            if not QuerySet(Model).filter(id=model_id).exists():
                raise AppApiException(500, f"{_('Model does not exist')}【{model_id}】")
        knowledge_id_list = list(set(self.data.get("knowledge_id_list", [])))
        exist_knowledge_id_list = [
            str(knowledge.id) for knowledge in QuerySet(Knowledge).filter(id__in=knowledge_id_list, user_id=user_id)
        ]
        for knowledge_id in knowledge_id_list:
            if not exist_knowledge_id_list.__contains__(knowledge_id):
                raise AppApiException(500, f"{_('The knowledge base id does not exist')}【{knowledge_id}】")

class ModelSettingSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=102400, label=_("Prompt word")
    )
    system = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=102400, label=_("Role prompts")
    )
    no_references_prompt = serializers.CharField(
        required=True, max_length=102400, allow_null=True, allow_blank=True, label=_("No citation segmentation prompt")
    )
    reasoning_content_enable = serializers.BooleanField(required=False, label=_("Thinking process switch"))
    reasoning_content_start = serializers.CharField(
        required=False,
        allow_null=True,
        default="<think>",
        allow_blank=True,
        max_length=256,
        trim_whitespace=False,
        label=_("The thinking process begins to mark"),
    )
    reasoning_content_end = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        default="</think>",
        max_length=256,
        trim_whitespace=False,
        label=_("End of thinking process marker"),
    )

class ApplicationCreateSerializer(serializers.Serializer):
    class ApplicationResponse(serializers.ModelSerializer):
        class Meta:
            model = Application
            fields = "__all__"

    class SimplateRequest(serializers.Serializer):
        name = serializers.CharField(required=True, max_length=64, min_length=1, label=_("application name"))
        desc = serializers.CharField(
            required=False,
            allow_null=True,
            allow_blank=True,
            max_length=256,
            min_length=1,
            label=_("application describe"),
        )
        folder_id = serializers.CharField(required=True, label=_("folder id"))
        model_id = serializers.CharField(required=False, allow_null=True, allow_blank=True, label=_("Model"))
        dialogue_number = serializers.IntegerField(
            required=True, min_value=0, max_value=1024, label=_("Historical chat records")
        )
        prologue = serializers.CharField(
            required=False, allow_null=True, allow_blank=True, max_length=40960, label=_("Opening remarks")
        )
        knowledge_id_list = serializers.ListSerializer(
            required=False,
            child=serializers.UUIDField(required=True),
            allow_null=True,
            label=_("Related Knowledge Base"),
        )
        # 数据集相关设置
        knowledge_setting = KnowledgeSettingSerializer(required=True)
        # 模型相关设置
        model_setting = ModelSettingSerializer(required=True)
        # 问题补全
        problem_optimization = serializers.BooleanField(required=True, label=_("Question completion"))
        problem_optimization_prompt = serializers.CharField(
            required=False, max_length=102400, label=_("Question completion prompt")
        )
        # 应用类型
        type = serializers.ChoiceField(
            required=True,
            choices=[ApplicationTypeChoices.SIMPLE.value],
            label=_("Application Type"),
        )
        model_params_setting = serializers.DictField(required=False, label=_("Model parameters"))

        tts_model_enable = serializers.BooleanField(required=False, label=_("Voice playback enabled"))

        tts_model_id = serializers.UUIDField(required=False, allow_null=True, label=_("Voice playback model ID"))

        tts_type = serializers.CharField(required=False, label=_("Voice playback type"))

        tts_autoplay = serializers.BooleanField(required=False, label=_("Voice playback autoplay"))

        stt_model_enable = serializers.BooleanField(required=False, label=_("Voice recognition enabled"))

        stt_model_id = serializers.UUIDField(required=False, allow_null=True, label=_("Speech recognition model ID"))

        stt_autosend = serializers.BooleanField(required=False, label=_("Voice recognition automatic transmission"))

        def is_valid(self, *, user_id=None, raise_exception=False):
            super().is_valid(raise_exception=True)
            ModelKnowledgeAssociation(
                data={
                    "user_id": user_id,
                    "model_id": self.data.get("model_id"),
                    "knowledge_id_list": self.data.get("knowledge_id_list"),
                }
            ).is_valid()

        @staticmethod
        def to_application_model(user_id: str, workspace_id: str, application: Dict):
            return Application(
                id=uuid.uuid7(),
                name=application.get("name"),
                desc=application.get("desc"),
                workspace_id=workspace_id,
                prologue=application.get("prologue"),
                dialogue_number=application.get("dialogue_number", 0),
                user_id=user_id,
                model_id=application.get("model_id"),
                folder_id=application.get("folder_id", application.get("workspace_id")),
                knowledge_setting=application.get("knowledge_setting"),
                model_setting=application.get("model_setting"),
                problem_optimization=application.get("problem_optimization"),
                type=ApplicationTypeChoices.SIMPLE,
                model_params_setting=application.get("model_params_setting", {}),
                problem_optimization_prompt=application.get("problem_optimization_prompt", None),
                stt_model_enable=application.get("stt_model_enable", False),
                stt_model_id=application.get("stt_model", None),
                stt_autosend=application.get("stt_autosend", False),
                tts_model_id=application.get("tts_model", None),
                tts_model_enable=application.get("tts_model_enable", False),
                tts_model_params_setting=application.get("tts_model_params_setting", {}),
                tts_type=application.get("tts_type", "BROWSER"),
                file_upload_enable=application.get("file_upload_enable", False),
                file_upload_setting=application.get("file_upload_setting", {}),
                work_flow={},
                mcp_enable=application.get("mcp_enable", False),
                mcp_tool_ids=application.get("mcp_tool_ids", []),
                mcp_servers=application.get("mcp_servers", {}),
                mcp_source=application.get("mcp_source", "referencing"),
                tool_enable=application.get("tool_enable", False),
                tool_ids=application.get("tool_ids", []),
                mcp_output_enable=application.get("mcp_output_enable", False),
            )

class ApplicationQueryRequest(serializers.Serializer):
    folder_id = serializers.CharField(required=False, label=_("folder id"))
    name = serializers.CharField(required=False, allow_null=True, allow_blank=True, label=_("Application Name"))
    desc = serializers.CharField(required=False, allow_null=True, allow_blank=True, label=_("Application Description"))
    publish_status = serializers.ChoiceField(
        required=False,
        label=_("Publish status"),
        choices=[("published", _("Published")), ("unpublished", _("Unpublished"))],
    )
    user_id = serializers.UUIDField(required=False, label=_("User ID"))
    create_user = serializers.CharField(required=False, allow_null=True, allow_blank=True, label=_("create user"))

class ApplicationListResponse(serializers.Serializer):
    id = serializers.CharField(required=True, label=_("Primary key id"), help_text=_("Primary key id"))
    name = serializers.CharField(required=True, label=_("Application Name"), help_text=_("Application Name"))
    desc = serializers.CharField(
        required=True, label=_("Application Description"), help_text=_("Application Description")
    )
    is_publish = serializers.BooleanField(required=True, label=_("Model id"), help_text=_("Model id"))
    type = serializers.CharField(required=True, label=_("Application type"), help_text=_("Application type"))
    resource_type = serializers.CharField(required=True, label=_("Resource type"), help_text=_("Resource type"))
    user_id = serializers.CharField(required=True, label=_("Affiliation user"), help_text=_("Affiliation user"))
    create_time = serializers.CharField(required=True, label=_("Creation time"), help_text=_("Creation time"))
    update_time = serializers.CharField(required=True, label=_("Modification time"), help_text=_("Modification time"))

class Query(serializers.Serializer):
    workspace_id = serializers.CharField(required=False, label=_("Workspace ID"))
    user_id = serializers.UUIDField(required=True, label=_("User ID"))

    def get_query_set(self, instance: Dict, workspace_manage: bool, is_x_pack_ee: bool):
        folder_query_set = QuerySet(ApplicationFolder)
        application_query_set = QuerySet(Application)
        workspace_id = self.data.get("workspace_id")
        user_id = self.data.get("user_id")
        desc = instance.get("desc")
        name = instance.get("name")
        publish_status = instance.get("publish_status")
        create_user = instance.get("create_user")
        if publish_status is not None:
            is_publish = True if publish_status == "published" else False
            application_query_set = application_query_set.filter(is_publish=is_publish)
        if workspace_id is not None:
            folder_query_set = folder_query_set.filter(workspace_id=workspace_id)
            application_query_set = application_query_set.filter(workspace_id=workspace_id)
        folder_id = instance.get("folder_id")
        if folder_id is not None and folder_id != workspace_id:
            folder_query_set = folder_query_set.filter(parent=folder_id)
            application_query_set = application_query_set.filter(folder_id=folder_id)
        if name is not None:
            folder_query_set = folder_query_set.filter(name__contains=name)
            application_query_set = application_query_set.filter(name__contains=name)
        if desc is not None:
            folder_query_set = folder_query_set.filter(desc__contains=desc)
            application_query_set = application_query_set.filter(desc__contains=desc)
        if create_user is not None:
            application_query_set = application_query_set.filter(user_id=create_user)
        application_custom_sql_query_set = application_query_set
        application_query_set = application_query_set.order_by("-create_time")

        resource_and_folder_query_set = QuerySet(WorkspaceUserResourcePermission).filter(
            auth_target_type="APPLICATION", workspace_id=workspace_id, user_id=user_id
        )

        return (
            {
                "application_query_set": application_query_set,
                "workspace_user_resource_permission_query_set": resource_and_folder_query_set,
            }
            if (not workspace_manage)
            else {
                "application_query_set": application_query_set,
                "application_custom_sql": application_custom_sql_query_set,
            }
        )

    @staticmethod
    def is_x_pack_ee():
        workspace_user_role_mapping_model = DatabaseModelManage.get_model("workspace_user_role_mapping")
        role_permission_mapping_model = DatabaseModelManage.get_model("role_permission_mapping_model")
        return workspace_user_role_mapping_model is not None and role_permission_mapping_model is not None

    def list(self, instance: Dict):
        self.is_valid(raise_exception=True)
        workspace_id = self.data.get("workspace_id")
        user_id = self.data.get("user_id")
        req_dict = ApplicationQueryRequest(data=instance)
        req_dict.is_valid(raise_exception=True)
        workspace_manage = is_workspace_manage_permission_read(user_id, workspace_id, "APPLICATION:READ")
        is_x_pack_ee = self.is_x_pack_ee()
        return native_search(
            self.get_query_set(req_dict.data, workspace_manage, is_x_pack_ee),
            select_string=get_file_content(
                os.path.join(
                    PROJECT_DIR,
                    "apps",
                    "application",
                    "sql",
                    "list_application.sql"
                    if workspace_manage
                    else ("list_application_user_ee.sql" if is_x_pack_ee else "list_application_user.sql"),
                )
            ),
        )

    def page(self, current_page: int, page_size: int, instance: Dict):
        self.is_valid(raise_exception=True)
        req_dict = ApplicationQueryRequest(data=instance)
        req_dict.is_valid(raise_exception=True)
        workspace_id = self.data.get("workspace_id")
        user_id = self.data.get("user_id")
        workspace_manage = is_workspace_manage_permission_read(user_id, workspace_id, "APPLICATION:READ")
        is_x_pack_ee = self.is_x_pack_ee()
        result = native_page_search(
            current_page,
            page_size,
            self.get_query_set(req_dict.data, workspace_manage, is_x_pack_ee),
            get_file_content(
                os.path.join(
                    PROJECT_DIR,
                    "apps",
                    "application",
                    "sql",
                    "list_application.sql"
                    if workspace_manage
                    else ("list_application_user_ee.sql" if is_x_pack_ee else "list_application_user.sql"),
                )
            ),
        )

        return ResourceMappingSerializer().get_resource_count(result)

class ApplicationEditSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, max_length=64, min_length=1, label=_("Application Name"))
    desc = serializers.CharField(
        required=False,
        max_length=256,
        min_length=1,
        allow_null=True,
        allow_blank=True,
        label=_("Application Description"),
    )
    model_id = serializers.CharField(required=False, allow_blank=True, allow_null=True, label=_("Model"))
    dialogue_number = serializers.IntegerField(
        required=False, min_value=0, max_value=1024, label=_("Historical chat records")
    )
    prologue = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=102400, label=_("Opening remarks")
    )
    knowledge_id_list = serializers.ListSerializer(
        required=False, child=serializers.UUIDField(required=True), label=_("Related Knowledge Base")
    )
    # 数据集相关设置
    knowledge_setting = KnowledgeSettingSerializer(required=False, allow_null=True, label=_("Dataset settings"))
    # 模型相关设置
    model_setting = ModelSettingSerializer(required=False, allow_null=True, label=_("Model setup"))
    # 问题补全
    problem_optimization = serializers.BooleanField(required=False, allow_null=True, label=_("Question completion"))
    icon = serializers.CharField(required=False, allow_null=True, label=_("Icon"))

    model_params_setting = serializers.DictField(required=False, label=_("Model parameters"))

    tts_model_enable = serializers.BooleanField(required=False, label=_("Voice playback enabled"))

    tts_model_id = serializers.UUIDField(required=False, allow_null=True, label=_("Voice playback model ID"))

    tts_type = serializers.CharField(required=False, label=_("Voice playback type"))

    tts_autoplay = serializers.BooleanField(required=False, label=_("Voice playback autoplay"))

    stt_model_enable = serializers.BooleanField(required=False, label=_("Voice recognition enabled"))

    stt_model_id = serializers.UUIDField(required=False, allow_null=True, label=_("Speech recognition model ID"))

    stt_autosend = serializers.BooleanField(required=False, label=_("Voice recognition automatic transmission"))

class ApplicationSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True, label=_("workspace id"))
    user_id = serializers.UUIDField(required=True, label=_("User ID"))

    @transaction.atomic
    def insert(self, instance: Dict):
        r = self.insert_simple(instance)
        UserResourcePermissionSerializer(
            data={
                "workspace_id": self.data.get("workspace_id"),
                "user_id": self.data.get("user_id"),
                "auth_target_type": AuthTargetType.APPLICATION.value,
            }
        ).auth_resource(str(r.get("id")))
        return r

    def to_application_knowledge_mapping(application_id: str, knowledge_id: str):
        return ResourceMapping(
            id=uuid.uuid7(),
            source_id=application_id,
            target_id=knowledge_id,
            source_type="APPLICATION",
            target_type="KNOWLEDGE",
        )

    def insert_simple(self, instance: Dict):
        self.is_valid(raise_exception=True)
        user_id = self.data.get("user_id")
        workspace_id = self.data.get("workspace_id")
        ApplicationCreateSerializer.SimplateRequest(data=instance).is_valid(user_id=user_id, raise_exception=True)
        application_model = ApplicationCreateSerializer.SimplateRequest.to_application_model(
            user_id, workspace_id, instance
        )
        knowledge_id_list = instance.get("knowledge_id_list", [])
        application_knowledge_mapping_model_list = [
            self.to_application_knowledge_mapping(application_model.id, knowledge_id)
            for knowledge_id in knowledge_id_list
        ]
        # 插入应用
        application_model.save()
        # 插入认证信息
        ApplicationAccessToken(
            application_id=application_model.id, access_token=hashlib.md5(str(uuid.uuid7()).encode()).hexdigest()[8:24]
        ).save()
        # 插入关联数据
        QuerySet(ResourceMapping).bulk_create(application_knowledge_mapping_model_list)
        return ApplicationCreateSerializer.ApplicationResponse(application_model).data

class ApplicationOperateSerializer(serializers.Serializer):
    application_id = serializers.UUIDField(required=True, label=_("Application ID"))
    user_id = serializers.UUIDField(required=True, label=_("User ID"))
    workspace_id = serializers.CharField(required=False, allow_null=True, allow_blank=True, label=_("Workspace ID"))

    def is_valid(self, *, raise_exception=False):
        super().is_valid(raise_exception=True)
        workspace_id = self.data.get("workspace_id")
        query_set = QuerySet(Application).filter(id=self.data.get("application_id"))
        if workspace_id:
            query_set = query_set.filter(workspace_id=workspace_id)
        if not query_set.exists():
            raise AppApiException(500, _("Application id does not exist"))

    def delete(self, with_valid=True):
        if with_valid:
            self.is_valid()
        application_id = self.data.get("application_id")
        QuerySet(ApplicationVersion).filter(application_id=application_id).delete()
        QuerySet(ResourceMapping).filter(Q(target_id=application_id) | Q(source_id=application_id)).delete()
        QuerySet(WorkspaceUserResourcePermission).filter(target=application_id).delete()
        QuerySet(Application).filter(id=application_id).delete()
        return True

    def reset_application_version(application_version, application):
        update_field_dict = {
            "application_name": "name",
            "desc": "desc",
            "prologue": "prologue",
            "dialogue_number": "dialogue_number",
            "user_id": "user_id",
            "model_id": "model_id",
            "knowledge_setting": "knowledge_setting",
            "model_setting": "model_setting",
            "model_params_setting": "model_params_setting",
            "tts_model_params_setting": "tts_model_params_setting",
            "stt_model_params_setting": "stt_model_params_setting",
            "problem_optimization": "problem_optimization",
            "icon": "icon",
            "work_flow": "work_flow",
            "problem_optimization_prompt": "problem_optimization_prompt",
            "tts_model_id": "tts_model_id",
            "stt_model_id": "stt_model_id",
            "tts_model_enable": "tts_model_enable",
            "stt_model_enable": "stt_model_enable",
            "tts_type": "tts_type",
            "tts_autoplay": "tts_autoplay",
            "stt_autosend": "stt_autosend",
            "file_upload_enable": "file_upload_enable",
            "file_upload_setting": "file_upload_setting",
            "mcp_enable": "mcp_enable",
            "mcp_tool_ids": "mcp_tool_ids",
            "mcp_servers": "mcp_servers",
            "mcp_source": "mcp_source",
            "tool_enable": "tool_enable",
            "tool_ids": "tool_ids",
            "application_enable": "application_enable",
            "application_ids": "application_ids",
            "skill_tool_ids": "skill_tool_ids",
            "mcp_output_enable": "mcp_output_enable",
            "type": "type",
        }

        for version_field, app_field in update_field_dict.items():
            _v = getattr(application, app_field)
            setattr(application_version, version_field, _v)

    @transaction.atomic
    def publish(self, instance, with_valid=True):
        if with_valid:
            self.is_valid()
        user_id = self.data.get("user_id")
        workspace_id = self.data.get("workspace_id")
        user = QuerySet(User).filter(id=user_id).first()
        application = (
            QuerySet(Application).filter(id=self.data.get("application_id"), workspace_id=workspace_id).first()
        )
        application.publish_time = timezone.now()
        application.is_publish = True
        application.save()
        work_flow_version = ApplicationVersion(
            work_flow=application.work_flow,
            application=application,
            name=timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
            publish_user_id=user_id,
            publish_user_name=user.username,
            workspace_id=workspace_id,
        )
        self.reset_application_version(work_flow_version, application)
        # 如果是简易应用 需要存入 knowledge_ids
        if application.type == ApplicationTypeChoices.SIMPLE:
            work_flow_version.knowledge_ids = [
                str(row.target_id)
                for row in QuerySet(ResourceMapping).filter(
                    source_id=str(application.id), source_type="APPLICATION", target_type="KNOWLEDGE"
                )
            ]
        work_flow_version.save()
        access_token = hashlib.md5(str(uuid.uuid7()).encode()).hexdigest()[8:24]
        application_access_token = QuerySet(ApplicationAccessToken).filter(application_id=application.id).first()
        if application_access_token is None:
            application_access_token = ApplicationAccessToken(
                application_id=application.id, access_token=access_token, is_active=True
            )
            application_access_token.save()
        else:
            access_token = application_access_token.access_token
        del_application_access_token(access_token)
        return self.one(with_valid=False)

    @staticmethod
    def move(self, folder_id: str):
        self.is_valid(raise_exception=True)
        application_id = self.data.get("application_id")
        application = QuerySet(Application).get(id=application_id)
        application.folder_id = folder_id
        application.save()
        return True

    @transaction.atomic
    def edit(self, instance: Dict, with_valid=True):
        if with_valid:
            self.is_valid()
            ApplicationEditSerializer(data=instance).is_valid(raise_exception=True)
        application_id = self.data.get("application_id")

        application = QuerySet(Application).get(id=application_id)

        if instance.get("model_id") is None or len(instance.get("model_id")) == 0:
            application.model_id = None
        else:
            model = QuerySet(Model).filter(id=instance.get("model_id")).first()
            if model is None:
                raise AppApiException(500, _("Model does not exist"))
        if instance.get("stt_model_id") is None or len(instance.get("stt_model_id")) == 0:
            application.stt_model_id = None
        else:
            model = QuerySet(Model).filter(id=instance.get("stt_model_id")).first()
            if model is None:
                raise AppApiException(500, _("Model does not exist"))
        if instance.get("tts_model_id") is None or len(instance.get("tts_model_id")) == 0:
            application.tts_model_id = None
        else:
            model = QuerySet(Model).filter(id=instance.get("tts_model_id")).first()
            if model is None:
                raise AppApiException(500, _("Model does not exist"))
        if instance.get("long_term_model_id") is None or len(instance.get("long_term_model_id")) == 0:
            application.long_term_model_id = None
        else:
            model = QuerySet(Model).filter(id=instance.get("long_term_model_id")).first()
            if model is None:
                raise AppApiException(500, _("Model does not exist"))
        update_keys = [
            "name",
            "desc",
            "model_id",
            "multiple_rounds_dialogue",
            "prologue",
            "status",
            "knowledge_setting",
            "model_setting",
            "problem_optimization",
            "dialogue_number",
            "stt_model_id",
            "tts_model_id",
            "tts_model_enable",
            "stt_model_enable",
            "tts_type",
            "tts_autoplay",
            "stt_autosend",
            "file_upload_enable",
            "file_upload_setting",
            "api_key_is_active",
            "icon",
            "work_flow",
            "model_params_setting",
            "tts_model_params_setting",
            "stt_model_params_setting",
            "mcp_enable",
            "mcp_tool_ids",
            "mcp_servers",
            "mcp_source",
            "tool_enable",
            "tool_ids",
            "mcp_output_enable",
            "application_enable",
            "application_ids",
            "skill_tool_ids",
            "long_term_enable",
            "long_term_model_id",
            "long_term_model_params_setting",
            "long_term_trigger_setting",
            "long_term_trigger_type",
            "problem_optimization_prompt",
            "clean_time",
            "file_clean_time",
            "folder_id",
        ]
        for update_key in update_keys:
            if update_key in instance and instance.get(update_key) is not None:
                application.__setattr__(update_key, instance.get(update_key))
        application.save()
        # 当前用户可修改关联的知识库列表
        application_knowledge_id_list = [
            str(knowledge.get("id")) for knowledge in self.list_knowledge(with_valid=False)
        ]
        knowledge_id_list = []
        if "knowledge_id_list" in instance:
            # 当前用户可修改关联的知识库列表
            application_knowledge_id_list = [
                str(knowledge.get("id")) for knowledge in self.list_knowledge(with_valid=False)
            ]
            knowledge_id_list = instance.get("knowledge_id_list")
            for knowledge_id in knowledge_id_list:
                if not application_knowledge_id_list.__contains__(knowledge_id):
                    message = lazy_format(
                        _("Unknown knowledge base id {dataset_id}, unable to associate"), dataset_id=knowledge_id
                    )
                    raise AppApiException(500, str(message))

        update_resource_mapping_by_application(
            application_id,
            self.get_application_knowledge_mapping(application_knowledge_id_list, knowledge_id_list, application_id),
        )
        return self.one(with_valid=False)

    def one(self, with_valid=True):
        if with_valid:
            self.is_valid()
        application_id = self.data.get("application_id")
        application = QuerySet(Application).get(id=application_id)
        available_knowledge_list = self.list_knowledge(with_valid=False)
        available_knowledge_dict = {knowledge.get("id"): knowledge for knowledge in available_knowledge_list}
        knowledge_list = []
        knowledge_id_list = []
        mapping_knowledge_list = QuerySet(ResourceMapping).filter(
            source_id=application_id, source_type="APPLICATION", target_type="KNOWLEDGE"
        )
        knowledge_list = [
            available_knowledge_dict.get(str(km.target_id))
            for km in mapping_knowledge_list
            if available_knowledge_dict.__contains__(str(km.target_id))
        ]
        knowledge_id_list = [k.get("id") for k in knowledge_list]

        return {
            **ApplicationSerializerModel(application).data,
            "knowledge_id_list": knowledge_id_list,
            "knowledge_list": knowledge_list,
        }

    @staticmethod
    def list_knowledge(self, with_valid=True):
        if with_valid:
            self.is_valid(raise_exception=True)
        workspace_id = self.data.get("workspace_id")
        user_id = self.data.get("user_id")
        knowledge_workspace_authorization_model = DatabaseModelManage.get_model("knowledge_workspace_authorization")
        share_knowledge_list = []
        if knowledge_workspace_authorization_model is not None:
            white_list_condition = Q(authentication_type="WHITE_LIST") & Q(workspace_id_list__contains=[workspace_id])
            default_condition = ~Q(authentication_type="WHITE_LIST") & ~Q(workspace_id_list__contains=[workspace_id])
            # 组合查询
            query = white_list_condition | default_condition
            inner = QuerySet(knowledge_workspace_authorization_model).filter(query)
            share_knowledge_list = [
                {**KnowledgeModelSerializer(k).data, "scope": "SHARED"}
                for k in QuerySet(Knowledge).filter(id__in=inner)
            ]
        workspace_knowledge_list = [
            {**k, "scope": "WORKSPACE"}
            for k in KnowledgeSerializer.Query(
                data={"workspace_id": workspace_id, "scope": KnowledgeScope.WORKSPACE, "user_id": user_id}
            ).list()
            if k.get("resource_type") == "knowledge"
        ]

        return [*workspace_knowledge_list, *share_knowledge_list]

    @staticmethod
    def save_application_knowledge_mapping(application_knowledge_id_list, knowledge_id_list, application_id):
        # 需要排除已删除的数据集
        knowledge_id_list = [knowledge.id for knowledge in QuerySet(Knowledge).filter(id__in=knowledge_id_list)]

        # 删除已经关联的id
        QuerySet(ResourceMapping).filter(
            target_id__in=application_knowledge_id_list,
            source_id=application_id,
            source_type="APPLICATION",
            target_type="KNOWLEDGE",
        ).delete()
        # 插入
        QuerySet(ResourceMapping).bulk_create(
            [
                ResourceMapping(
                    source_id=application_id, target_id=knowledge_id, source_type="APPLICATION", target_type="KNOWLEDGE"
                )
                for knowledge_id in knowledge_id_list
            ]
        ) if len(knowledge_id_list) > 0 else None

    @staticmethod
    def get_application_knowledge_mapping(application_knowledge_id_list, knowledge_id_list, application_id):
        """

        @param application_knowledge_id_list:  当前应用可修改的知识库列表
        @param knowledge_id_list:              用户修改的知识库列表
        @param application_id:                 应用id
        @return:
        """
        # 当前知识库和应用已关联列表
        knowledge_application_mapping_list = (
            QuerySet(ResourceMapping)
            .filter(
                source_id=application_id,
                source_type="APPLICATION",
                target_type="KNOWLEDGE",
            )
            .exclude(target_id__in=application_knowledge_id_list)
        )
        edit_knowledge_list = [
            ResourceMapping(
                source_id=application_id, target_id=knowledge_id, source_type="APPLICATION", target_type="KNOWLEDGE"
            )
            for knowledge_id in knowledge_id_list
        ]
        return list(knowledge_application_mapping_list) + edit_knowledge_list

class ApplicationBatchOperateSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True, label=_("Workspace ID"))

    def is_valid(self, *, raise_exception=False):
        super().is_valid(raise_exception=True)

    @transaction.atomic
    def batch_delete(self, instance: Dict, with_valid=True):
        if with_valid:
            BatchSerializer(data=instance).is_valid(model=Application, raise_exception=True)
            self.is_valid(raise_exception=True)
        id_list = instance.get("id_list")
        workspace_id = self.data.get("workspace_id")
        id_list = list(
            QuerySet(Application).filter(id__in=id_list, workspace_id=workspace_id).values_list("id", flat=True)
        )

        QuerySet(ApplicationVersion).filter(application_id__in=id_list).delete()
        QuerySet(ResourceMapping).filter(Q(target_id__in=id_list) | Q(source_id__in=id_list)).delete()
        QuerySet(WorkspaceUserResourcePermission).filter(target__in=id_list).delete()

        QuerySet(Application).filter(id__in=id_list, workspace_id=workspace_id).delete()
        return True

    def batch_move(self, instance: Dict, with_valid=True):
        if with_valid:
            BatchMoveSerializer(data=instance).is_valid(model=Application, raise_exception=True)
            self.is_valid(raise_exception=True)
        id_list = instance.get("id_list")
        folder_id = instance.get("folder_id")
        workspace_id = self.data.get("workspace_id")

        QuerySet(Application).filter(id__in=id_list, workspace_id=workspace_id).update(folder_id=folder_id)
        return True

    @transaction.atomic
    def batch_clean_time(self, instance: Dict, with_valid=True):
        if with_valid:
            BatchCleanTimeSerializer(data=instance).is_valid(model=Application, raise_exception=True)
            self.is_valid(raise_exception=True)
        id_list = instance.get("id_list")
        workspace_id = self.data.get("workspace_id")
        clean_time = instance.get("clean_time")
        file_clean_time = instance.get("file_clean_time")
        application_count = QuerySet(Application).filter(id__in=id_list, workspace_id=workspace_id).count()
        if application_count != len(id_list):
            raise AppApiException(500, _("Application does not exist"))

        QuerySet(Application).filter(id__in=id_list, workspace_id=workspace_id).update(
            clean_time=clean_time,
            file_clean_time=file_clean_time,
        )
        return True

class BatchCleanTimeSerializer(BatchSerializer):
    clean_time = serializers.IntegerField(required=True, min_value=1, max_value=100000, label=_("Clean time"))
    file_clean_time = serializers.IntegerField(required=True, min_value=1, max_value=100000, label=_("File clean time"))

    def is_valid(self, *, model=None, raise_exception=False):
        super().is_valid(model=model, raise_exception=True)
        if not self.data.get("id_list"):
            raise AppApiException(500, _("id list cannot be empty"))
        if self.data.get("file_clean_time") > self.data.get("clean_time"):
            raise AppApiException(500, _("File clean time cannot exceed clean time"))
