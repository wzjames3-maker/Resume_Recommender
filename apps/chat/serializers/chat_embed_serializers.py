# coding=utf-8
"""
    @project: MaxKB
    @Author：虎虎
    @file： chat_embed_serializers.py
    @date：2025/5/30 14:34
    @desc:
"""
import json
import os
import re
import uuid_utils.compat as uuid

from urllib.parse import quote

from django.db.models import QuerySet
from django.http import HttpResponse
from django.template import Template, Context
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from application.models import ApplicationAccessToken
from common.database_model_manage.database_model_manage import DatabaseModelManage
from maxkb.conf import PROJECT_DIR
from maxkb.const import CONFIG

# P1-5: embed.js 反射型 XSS 防护
# host 仅允许字母数字、点、横线及冒号端口(拒绝换行/引号/尖括号/斜杠/空格等字符)
HOST_PATTERN = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?$')
PROTOCOL_ALLOWLIST = ('http', 'https')
# header_font_color 会进入 SVG fill 属性位置(insertAdjacentHTML 会还原实体),仅放行安全的颜色格式
COLOR_PATTERN = re.compile(
    r'^(#[0-9a-fA-F]{3,8}|rgba?\(\s*\d{1,3}%?(?:\s*,\s*(?:\d{1,3}%?|\d*\.?\d+)\s*){2,3}\))$')
# x_type/y_type 会进入 CSS 属性名与 JS 比较位置,仅放行合法方位
POSITION_TYPE_ALLOWLIST = ('left', 'right', 'top', 'bottom')


def js_string(value):
    """用 json.dumps 生成可安全嵌入 JS 字符串字面量的值(引号/换行等均被转义)"""
    return mark_safe(json.dumps(str(value)))


def position_value(value, default):
    """仅允许数值,用于 CSS 数值位置"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return int(number) if number.is_integer() else number


class ChatEmbedSerializer(serializers.Serializer):
    host = serializers.CharField(required=True, label=_("Host"))
    protocol = serializers.CharField(required=True, label=_("protocol"))
    token = serializers.CharField(required=True, label=_("token"))

    def validate_protocol(self, value):
        # 仅允许 http/https,防止 javascript: 等协议注入
        if value not in PROTOCOL_ALLOWLIST:
            raise serializers.ValidationError(_('protocol 仅支持 http/https'))
        return value

    def validate_host(self, value):
        # 严格正则校验(fullmatch 连结尾换行也拒绝),拒绝含换行/引号/尖括号等字符的 host
        if HOST_PATTERN.fullmatch(value) is None:
            raise serializers.ValidationError(_('Host 格式不合法'))
        return value

    def get_embed(self, with_valid=True, params=None):
        if params is None:
            params = {}
        if with_valid:
            self.is_valid(raise_exception=True)
        index_path = os.path.join(PROJECT_DIR, 'apps', "chat", 'template', 'embed.js')
        file = open(index_path, "r", encoding='utf-8')
        content = file.read()
        file.close()
        application_access_token = QuerySet(ApplicationAccessToken).filter(
            access_token=self.data.get('token')).first()
        if application_access_token is None:
            # token 不存在时直接报错,而非渲染模板
            return HttpResponse('invalid token', status=400, content_type='text/plain')
        is_draggable = 'false'
        show_guide = 'true'
        float_icon = f"{self.data.get('protocol')}://{self.data.get('host')}{CONFIG.get_chat_path()}/MaxKB.gif"
        is_license_valid = DatabaseModelManage.get_model('license_is_valid')
        X_PACK_LICENSE_IS_VALID = is_license_valid() if is_license_valid is not None else False
        # 获取接入的query参数
        query = self.get_query_api_input(application_access_token.application, params)
        float_location = {"x": {"type": "right", "value": 0}, "y": {"type": "bottom", "value": 30}}
        header_font_color = "rgb(100, 106, 115)"
        application_setting_model = DatabaseModelManage.get_model('application_setting')
        if application_setting_model is not None and X_PACK_LICENSE_IS_VALID:
            application_setting = QuerySet(application_setting_model).filter(
                application_id=application_access_token.application_id).first()
            if application_setting is not None:
                is_draggable = 'true' if application_setting.draggable else 'false'
                if application_setting.float_icon is not None and len(application_setting.float_icon) > 0:
                    float_icon = application_setting.float_icon[1:] if application_setting.float_icon.startswith(
                        '.') else application_setting.float_icon
                    float_icon = f"{self.data.get('protocol')}://{self.data.get('host')}{CONFIG.get_chat_path()}{float_icon}"
                show_guide = 'true' if application_setting.show_guide else 'false'
                if application_setting.float_location is not None:
                    float_location = application_setting.float_location
                if application_setting.custom_theme is not None and len(
                        application_setting.custom_theme.get('header_font_color', 'rgb(100, 106, 115)')) > 0:
                    header_font_color = application_setting.custom_theme.get('header_font_color',
                                                                             'rgb(100, 106, 115)')

        is_auth = 'true' if application_access_token is not None and application_access_token.is_active else 'false'
        # 对进入 CSS 属性名/数值及 SVG fill 属性位置的变量做允许列表校验(这些位置无法用 json.dumps 保护)
        if COLOR_PATTERN.fullmatch(header_font_color) is None:
            header_font_color = 'rgb(100, 106, 115)'
        x_type = float_location.get('x', {}).get('type', 'right')
        y_type = float_location.get('y', {}).get('type', 'bottom')
        x_type = x_type if x_type in POSITION_TYPE_ALLOWLIST else 'right'
        y_type = y_type if y_type in POSITION_TYPE_ALLOWLIST else 'bottom'
        x_value = position_value(float_location.get('x', {}).get('value', 0), 0)
        y_value = position_value(float_location.get('y', {}).get('value', 30), 30)
        t = Template(content)
        s = t.render(
            Context(
                {'is_auth': is_auth, 'protocol': js_string(self.data.get('protocol')),
                 'host': js_string(self.data.get('host')),
                 'token': js_string(self.data.get('token')),
                 'white_list_str': js_string(",".join(
                     application_access_token.white_list if application_access_token.white_list is not None else [])),
                 'white_active': 'true' if application_access_token.white_active else 'false',
                 'is_draggable': is_draggable,
                 'float_icon': js_string(float_icon),
                 'prefix': js_string(CONFIG.get_chat_path()),
                 'query': js_string(query),
                 'show_guide': show_guide,
                 'x_type': x_type,
                 'x_value': x_value,
                 'y_type': y_type,
                 'y_value': y_value,
                 'max_kb_id': str(uuid.uuid7()).replace('-', ''),
                 'header_font_color': header_font_color}))
        response = HttpResponse(s, status=200, headers={'Content-Type': 'text/javascript'})
        return response

    @staticmethod
    def get_query_api_input(application, params):
        query = ''
        if application.work_flow is not None:
            work_flow = application.work_flow
            if work_flow is not None:
                for node in work_flow.get('nodes', []):
                    if node['id'] == 'base-node':
                        input_field_list = node.get('properties', {}).get('api_input_field_list',
                                                                          node.get('properties', {}).get(
                                                                              'input_field_list', []))
                        if input_field_list is not None:
                            for field in input_field_list:
                                if field['assignment_method'] == 'api_input' and field['variable'] in params:
                                    name = quote(str(field['variable']), safe='')
                                    value = quote(str(params[field['variable']]), safe='')
                                    query += f'&{name}={value}'
        if 'asker' in params:
            query += f"&asker={quote(str(params.get('asker')), safe='')}"
        return query
