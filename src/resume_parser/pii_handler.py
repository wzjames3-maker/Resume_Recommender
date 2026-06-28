"""
智能招聘 RAG 推荐系统 - PII 检测与加密模块

PII 检测：正则 + NER 模型识别手机号、身份证号、邮箱、地址等
PII 加密：AES-256 加密 PII 字段
"""

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.resume_store.encryption import get_encryptor

logger = get_logger("pii_handler")


class PIIType(str, Enum):
    """PII 类型"""

    PHONE = "phone"  # 手机号
    ID_CARD = "id_card"  # 身份证号
    EMAIL = "email"  # 邮箱
    ADDRESS = "address"  # 地址
    BANK_CARD = "bank_card"  # 银行卡号
    NAME = "name"  # 姓名


class PIIDetection(BaseModel):
    """PII 检测结果"""

    pii_type: PIIType = Field(..., description="PII 类型")
    value: str = Field(..., description="PII 值")
    start_pos: int = Field(..., description="起始位置")
    end_pos: int = Field(..., description="结束位置")
    confidence: float = Field(1.0, description="置信度")


class PIIDetectionResult(BaseModel):
    """PII 检测结果"""

    detections: List[PIIDetection] = Field(
        default_factory=list, description="检测到的 PII 列表"
    )
    has_pii: bool = Field(False, description="是否包含 PII")
    pii_types: List[PIIType] = Field(
        default_factory=list, description="包含的 PII 类型列表"
    )


class PIIAccessLog(BaseModel):
    """PII 访问日志"""

    user_id: str = Field(..., description="访问用户 ID")
    resume_id: str = Field(..., description="简历 ID")
    fields: List[str] = Field(..., description="访问的字段列表")
    access_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="访问时间"
    )
    action: str = Field("decrypt", description="操作类型")


class PIIHandler:
    """PII 处理器"""

    # 中国大陆手机号正则
    PHONE_PATTERN = re.compile(
        r"(?<!\d)1[3-9]\d{9}(?!\d)"
    )

    # 身份证号正则（18 位）
    ID_CARD_PATTERN = re.compile(
        r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
    )

    # 邮箱正则
    EMAIL_PATTERN = re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    )

    # 银行卡号正则（16-19 位）
    BANK_CARD_PATTERN = re.compile(
        r"(?<!\d)[1-9]\d{15,18}(?!\d)"
    )

    # 地址关键词
    ADDRESS_KEYWORDS = [
        "省", "市", "区", "县", "镇", "乡", "村",
        "路", "街", "巷", "号", "楼", "室",
        "小区", "公寓", "大厦", "广场",
    ]

    def __init__(self):
        """初始化 PII 处理器"""
        self.encryptor = get_encryptor()
        self._access_logs: List[PIIAccessLog] = []

    def detect_pii(self, text: str) -> PIIDetectionResult:
        """
        检测文本中的 PII

        Args:
            text: 文本内容

        Returns:
            PIIDetectionResult: 检测结果
        """
        detections = []
        pii_types = set()

        # 检测手机号
        for match in self.PHONE_PATTERN.finditer(text):
            detections.append(PIIDetection(
                pii_type=PIIType.PHONE,
                value=match.group(),
                start_pos=match.start(),
                end_pos=match.end(),
            ))
            pii_types.add(PIIType.PHONE)

        # 检测身份证号
        for match in self.ID_CARD_PATTERN.finditer(text):
            detections.append(PIIDetection(
                pii_type=PIIType.ID_CARD,
                value=match.group(),
                start_pos=match.start(),
                end_pos=match.end(),
            ))
            pii_types.add(PIIType.ID_CARD)

        # 检测邮箱
        for match in self.EMAIL_PATTERN.finditer(text):
            detections.append(PIIDetection(
                pii_type=PIIType.EMAIL,
                value=match.group(),
                start_pos=match.start(),
                end_pos=match.end(),
            ))
            pii_types.add(PIIType.EMAIL)

        # 检测银行卡号
        for match in self.BANK_CARD_PATTERN.finditer(text):
            detections.append(PIIDetection(
                pii_type=PIIType.BANK_CARD,
                value=match.group(),
                start_pos=match.start(),
                end_pos=match.end(),
            ))
            pii_types.add(PIIType.BANK_CARD)

        logger.info(f"PII 检测完成: {len(detections)} 个 PII, 类型: {pii_types}")

        return PIIDetectionResult(
            detections=detections,
            has_pii=len(detections) > 0,
            pii_types=list(pii_types),
        )

    def encrypt_pii_fields(
        self, data: Dict[str, Any], fields: List[str]
    ) -> Dict[str, Any]:
        """
        加密数据中的 PII 字段

        Args:
            data: 数据字典
            fields: 需要加密的字段列表

        Returns:
            Dict: 加密后的数据
        """
        result = data.copy()
        encrypted_fields = []

        for field in fields:
            value = self._get_nested_value(result, field)
            if value and isinstance(value, str):
                encrypted_value = self.encryptor.encrypt(value)
                self._set_nested_value(result, field, encrypted_value)
                encrypted_fields.append(field)

        # 记录加密的字段
        result["_encrypted_fields"] = encrypted_fields

        logger.info(f"PII 加密完成: {encrypted_fields}")

        return result

    def decrypt_pii_fields(
        self,
        data: Dict[str, Any],
        fields: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        resume_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        解密数据中的 PII 字段

        Args:
            data: 数据字典
            fields: 需要解密的字段列表（None 则解密所有加密字段）
            user_id: 访问用户 ID
            resume_id: 简历 ID

        Returns:
            Dict: 解密后的数据
        """
        result = data.copy()

        # 获取需要解密的字段
        encrypted_fields = data.get("_encrypted_fields", [])
        if fields is None:
            fields = encrypted_fields

        decrypted_fields = []

        for field in fields:
            if field in encrypted_fields:
                value = self._get_nested_value(result, field)
                if value and isinstance(value, str):
                    try:
                        decrypted_value = self.encryptor.decrypt(value)
                        self._set_nested_value(result, field, decrypted_value)
                        decrypted_fields.append(field)
                    except Exception as e:
                        logger.error(f"字段 {field} 解密失败: {str(e)}")

        # 记录访问日志
        if user_id and resume_id and decrypted_fields:
            self._log_access(user_id, resume_id, decrypted_fields)

        logger.info(f"PII 解密完成: {decrypted_fields}")

        return result

    def _get_nested_value(self, data: Dict[str, Any], field: str) -> Any:
        """
        获取嵌套字段值

        Args:
            data: 数据字典
            field: 字段路径（如 "personal_info.phone"）

        Returns:
            Any: 字段值
        """
        parts = field.split(".")
        current = data

        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None

        return current

    def _set_nested_value(
        self, data: Dict[str, Any], field: str, value: Any
    ) -> None:
        """
        设置嵌套字段值

        Args:
            data: 数据字典
            field: 字段路径
            value: 字段值
        """
        parts = field.split(".")
        current = data

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value

    def _log_access(
        self, user_id: str, resume_id: str, fields: List[str]
    ) -> None:
        log = PIIAccessLog(
            user_id=user_id,
            resume_id=resume_id,
            fields=fields,
        )
        self._access_logs.append(log)

        logger.info(
            f"PII 访问记录: user={user_id}, resume={resume_id}, fields={fields}"
        )

        try:
            from src.resume_store.connection import mongodb_connection
            db = mongodb_connection.get_database()
            db.pii_access_logs.insert_one(log.model_dump(mode="json"))
        except Exception as e:
            logger.error(f"PII 访问日志写入 MongoDB 失败: {e}")

    def get_access_logs(
        self,
        user_id: Optional[str] = None,
        resume_id: Optional[str] = None,
    ) -> List[PIIAccessLog]:
        """
        获取 PII 访问日志

        Args:
            user_id: 用户 ID（可选）
            resume_id: 简历 ID（可选）

        Returns:
            List[PIIAccessLog]: 访问日志列表
        """
        logs = self._access_logs

        if user_id:
            logs = [log for log in logs if log.user_id == user_id]

        if resume_id:
            logs = [log for log in logs if log.resume_id == resume_id]

        return logs


# 全局 PII 处理器实例
pii_handler = PIIHandler()


def get_pii_handler() -> PIIHandler:
    """获取 PII 处理器实例"""
    return pii_handler
