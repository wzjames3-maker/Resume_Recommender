"""
智能招聘 RAG 推荐系统 - PII 处理测试
"""

import pytest

from src.resume_parser.pii_handler import (
    PIIHandler,
    PIIDetection,
    PIIDetectionResult,
    PIIType,
    get_pii_handler,
)


@pytest.fixture
def handler():
    """创建 PII 处理器实例"""
    return PIIHandler()


class TestPIIType:
    """PII 类型测试"""

    def test_pii_types(self):
        """测试 PII 类型枚举"""
        assert PIIType.PHONE.value == "phone"
        assert PIIType.ID_CARD.value == "id_card"
        assert PIIType.EMAIL.value == "email"
        assert PIIType.ADDRESS.value == "address"
        assert PIIType.BANK_CARD.value == "bank_card"
        assert PIIType.NAME.value == "name"


class TestPIIHandler:
    """PIIHandler 测试"""

    def test_detect_phone(self, handler):
        """测试检测手机号"""
        text = "我的电话是13800138000，请联系我"
        result = handler.detect_pii(text)

        assert result.has_pii is True
        assert PIIType.PHONE in result.pii_types
        assert len(result.detections) >= 1

        phone_detection = next(
            d for d in result.detections if d.pii_type == PIIType.PHONE
        )
        assert phone_detection.value == "13800138000"

    def test_detect_id_card(self, handler):
        """测试检测身份证号"""
        text = "身份证号：110101199001011234"
        result = handler.detect_pii(text)

        assert result.has_pii is True
        assert PIIType.ID_CARD in result.pii_types

        id_detection = next(
            d for d in result.detections if d.pii_type == PIIType.ID_CARD
        )
        assert id_detection.value == "110101199001011234"

    def test_detect_email(self, handler):
        """测试检测邮箱"""
        text = "邮箱：zhangsan@example.com"
        result = handler.detect_pii(text)

        assert result.has_pii is True
        assert PIIType.EMAIL in result.pii_types

        email_detection = next(
            d for d in result.detections if d.pii_type == PIIType.EMAIL
        )
        assert email_detection.value == "zhangsan@example.com"

    def test_detect_bank_card(self, handler):
        """测试检测银行卡号"""
        text = "银行卡号：6222021234567890123"
        result = handler.detect_pii(text)

        assert result.has_pii is True
        assert PIIType.BANK_CARD in result.pii_types

    def test_detect_multiple_pii(self, handler):
        """测试检测多个 PII"""
        text = "姓名：张三，电话：13800138000，邮箱：zhangsan@example.com"
        result = handler.detect_pii(text)

        assert result.has_pii is True
        assert len(result.detections) >= 2
        assert PIIType.PHONE in result.pii_types
        assert PIIType.EMAIL in result.pii_types

    def test_detect_no_pii(self, handler):
        """测试没有 PII"""
        text = "这是一段没有 PII 的文本"
        result = handler.detect_pii(text)

        assert result.has_pii is False
        assert len(result.detections) == 0

    def test_encrypt_decrypt_roundtrip(self, handler):
        """测试加密解密往返"""
        data = {
            "personal_info": {
                "name": "张三",
                "phone": "13800138000",
                "email": "zhangsan@example.com",
            }
        }

        fields = ["personal_info.phone", "personal_info.email"]

        # 加密
        encrypted = handler.encrypt_pii_fields(data, fields)

        # 验证字段已加密
        assert encrypted["personal_info"]["phone"] != "13800138000"
        assert encrypted["personal_info"]["email"] != "zhangsan@example.com"
        assert encrypted["_encrypted_fields"] == fields

        # 解密
        decrypted = handler.decrypt_pii_fields(encrypted, fields)

        # 验证字段已解密
        assert decrypted["personal_info"]["phone"] == "13800138000"
        assert decrypted["personal_info"]["email"] == "zhangsan@example.com"

    def test_decrypt_with_access_log(self, handler):
        """测试解密时记录访问日志"""
        data = {
            "personal_info": {
                "phone": "13800138000",
            },
            "_encrypted_fields": ["personal_info.phone"],
        }

        # 先加密
        encrypted = handler.encrypt_pii_fields(data, ["personal_info.phone"])

        # 解密并记录日志
        handler.decrypt_pii_fields(
            encrypted,
            ["personal_info.phone"],
            user_id="user123",
            resume_id="resume456",
        )

        # 验证访问日志
        logs = handler.get_access_logs(user_id="user123")
        assert len(logs) >= 1
        assert logs[-1].user_id == "user123"
        assert logs[-1].resume_id == "resume456"
        assert "personal_info.phone" in logs[-1].fields

    def test_get_nested_value(self, handler):
        """测试获取嵌套值"""
        data = {
            "a": {
                "b": {
                    "c": "value",
                }
            }
        }

        assert handler._get_nested_value(data, "a.b.c") == "value"
        assert handler._get_nested_value(data, "a.b.d") is None
        assert handler._get_nested_value(data, "x.y.z") is None

    def test_set_nested_value(self, handler):
        """测试设置嵌套值"""
        data = {}

        handler._set_nested_value(data, "a.b.c", "value")

        assert data["a"]["b"]["c"] == "value"

    def test_get_pii_handler(self):
        """测试获取全局实例"""
        handler = get_pii_handler()
        assert isinstance(handler, PIIHandler)


class TestPIIDetectionResult:
    """PIIDetectionResult 测试"""

    def test_create_result(self):
        """测试创建结果"""
        result = PIIDetectionResult(
            detections=[
                PIIDetection(
                    pii_type=PIIType.PHONE,
                    value="13800138000",
                    start_pos=0,
                    end_pos=11,
                )
            ],
            has_pii=True,
            pii_types=[PIIType.PHONE],
        )

        assert result.has_pii is True
        assert len(result.detections) == 1
        assert PIIType.PHONE in result.pii_types
