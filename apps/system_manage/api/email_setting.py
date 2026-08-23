# coding=utf-8
"""
    @project: MaxKB
    @Author：虎虎
    @file： workspace_user_resource_permission.py
    @date：2025/4/28 18:13
    @desc:
"""

from common.mixins.api_mixin import APIMixin
from common.result import ResultSerializer
from system_manage.serializers.email_setting import EmailSettingSerializer


class EmailResponse(ResultSerializer):
    def get_data(self):
        return EmailSettingSerializer.Create()


class EmailSettingAPI(APIMixin):
    @staticmethod
    def get_request():
        return EmailSettingSerializer.Create()

    @staticmethod
    def get_response():
        return EmailResponse
