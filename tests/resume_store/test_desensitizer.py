"""
智能招聘 RAG 推荐系统 - 数据脱敏测试
"""

import pytest

from src.resume_store.desensitizer import (
    DesensitizeConfig,
    DesensitizeRule,
    Desensitizer,
    get_desensitizer,
)


@pytest.fixture
def desensitizer():
    """创建脱敏器实例"""
    return Desensitizer()


@pytest.fixture
def config():
    """创建脱敏配置"""
    return DesensitizeConfig(
        rules=[
            DesensitizeRule(
                field="personal_info.phone",
                method="phone_mask",
                prefix_len=3,
                suffix_len=4,
            ),
            DesensitizeRule(
                field="personal_info.email",
                method="email_mask",
                prefix_len=3,
            ),
        ]
    )


class TestDesensitizeRule:
    """DesensitizeRule 测试"""

    def test_create_rule(self):
        """测试创建规则"""
        rule = DesensitizeRule(
            field="personal_info.phone",
            method="mask",
            prefix_len=3,
            suffix_len=4,
        )

        assert rule.field == "personal_info.phone"
        assert rule.method == "mask"
        assert rule.prefix_len == 3
        assert rule.suffix_len == 4


class TestDesensitizer:
    """Desensitizer 测试"""

    def test_mask(self, desensitizer):
        """测试通用脱敏"""
        # 测试标准脱敏
        result = desensitizer._mask("13800138000", 3, 4)
        assert result == "138****8000"

        # 测试前缀+后缀超过长度
        result = desensitizer._mask("123", 2, 2)
        assert result == "123"

        # 测试空值
        result = desensitizer._mask("", 3, 4)
        assert result == ""

    def test_email_mask(self, desensitizer):
        """测试邮箱脱敏"""
        result = desensitizer._email_mask("test@example.com", 3)
        assert result == "tes***@example.com"

        result = desensitizer._email_mask("ab@example.com", 3)
        assert result == "ab***@example.com"

        result = desensitizer._email_mask("", 3)
        assert result == ""

        result = desensitizer._email_mask("invalid", 3)
        assert result == "invalid"

    def test_phone_mask(self, desensitizer):
        """测试手机号脱敏"""
        result = desensitizer._phone_mask("13800138000")
        assert result == "138****8000"

        result = desensitizer._phone_mask("")
        assert result == ""

        result = desensitizer._phone_mask("123")
        assert result == "123"

    def test_id_card_mask(self, desensitizer):
        """测试身份证号脱敏"""
        result = desensitizer._id_card_mask("110101199001011234")
        assert result == "110101********1234"

        result = desensitizer._id_card_mask("")
        assert result == ""

        result = desensitizer._id_card_mask("12345")
        assert result == "12345"

    def test_desensitize_with_rules(self, desensitizer):
        """测试使用规则脱敏"""
        data = {
            "personal_info": {
                "name": "张三",
                "phone": "13800138000",
                "email": "zhangsan@example.com",
            }
        }

        rules = [
            DesensitizeRule(
                field="personal_info.phone",
                method="phone_mask",
                prefix_len=3,
                suffix_len=4,
            ),
            DesensitizeRule(
                field="personal_info.email",
                method="email_mask",
                prefix_len=3,
            ),
        ]

        result = desensitizer.desensitize(data, rules)

        assert result["personal_info"]["phone"] == "138****8000"
        assert result["personal_info"]["email"] == "zha***@example.com"
        assert result["personal_info"]["name"] == "张三"  # 未脱敏

    def test_desensitize_with_config(self, config):
        """测试使用配置脱敏"""
        desensitizer = Desensitizer(config=config)

        data = {
            "personal_info": {
                "phone": "13800138000",
                "email": "zhangsan@example.com",
            }
        }

        result = desensitizer.desensitize(data)

        assert result["personal_info"]["phone"] == "138****8000"
        assert result["personal_info"]["email"] == "zha***@example.com"

    def test_register_custom_method(self, desensitizer):
        """测试注册自定义方法"""
        # 注册自定义脱敏方法
        def custom_mask(value: str) -> str:
            return "CUSTOM:" + value[:3] + "***"

        desensitizer.register_method("custom_mask", custom_mask)

        # 使用自定义方法
        data = {"field": "test_value"}
        rules = [
            DesensitizeRule(field="field", method="custom_mask"),
        ]

        result = desensitizer.desensitize(data, rules)
        assert result["field"] == "CUSTOM:tes***"

    def test_get_nested_value(self, desensitizer):
        """测试获取嵌套值"""
        data = {
            "a": {
                "b": {
                    "c": "value",
                }
            }
        }

        assert desensitizer._get_nested_value(data, "a.b.c") == "value"
        assert desensitizer._get_nested_value(data, "a.b.d") is None
        assert desensitizer._get_nested_value(data, "x.y.z") is None

    def test_set_nested_value(self, desensitizer):
        """测试设置嵌套值"""
        data = {}

        desensitizer._set_nested_value(data, "a.b.c", "value")

        assert data["a"]["b"]["c"] == "value"

    def test_get_desensitizer(self):
        """测试获取全局实例"""
        desensitizer = get_desensitizer()
        assert isinstance(desensitizer, Desensitizer)


class TestDesensitizeConfig:
    """DesensitizeConfig 测试"""

    def test_create_config(self):
        """测试创建配置"""
        config = DesensitizeConfig(
            rules=[
                DesensitizeRule(
                    field="phone",
                    method="mask",
                    prefix_len=3,
                    suffix_len=4,
                ),
            ]
        )

        assert len(config.rules) == 1
        assert config.rules[0].field == "phone"
