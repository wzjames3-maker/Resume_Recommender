"""
智能招聘 RAG 推荐系统 - 数据脱敏模块

可配置的脱敏规则
"""

import re
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from src.common.logger import get_logger

logger = get_logger("desensitizer")


class DesensitizeRule(BaseModel):
    """脱敏规则"""

    field: str = Field(..., description="字段路径")
    method: str = Field(..., description="脱敏方法")
    pattern: Optional[str] = Field(None, description="正则表达式")
    replacement: Optional[str] = Field(None, description="替换字符串")
    prefix_len: int = Field(0, description="保留前缀长度")
    suffix_len: int = Field(0, description="保留后缀长度")


class DesensitizeConfig(BaseModel):
    """脱敏配置"""

    rules: List[DesensitizeRule] = Field(
        default_factory=list, description="脱敏规则列表"
    )


class Desensitizer:
    """数据脱敏器"""

    # 默认脱敏规则
    DEFAULT_RULES = {
        "phone": {
            "method": "mask",
            "prefix_len": 3,
            "suffix_len": 4,
            "mask_char": "*",
        },
        "email": {
            "method": "email_mask",
            "prefix_len": 3,
            "suffix_len": 0,
            "mask_char": "*",
        },
        "id_card": {
            "method": "mask",
            "prefix_len": 6,
            "suffix_len": 4,
            "mask_char": "*",
        },
        "bank_card": {
            "method": "mask",
            "prefix_len": 4,
            "suffix_len": 4,
            "mask_char": "*",
        },
    }

    def __init__(self, config: Optional[DesensitizeConfig] = None):
        """
        初始化脱敏器

        Args:
            config: 脱敏配置
        """
        self.config = config or DesensitizeConfig()
        self._custom_methods: Dict[str, Callable] = {}

    def desensitize(
        self, data: Dict[str, Any], rules: Optional[List[DesensitizeRule]] = None
    ) -> Dict[str, Any]:
        """
        对数据进行脱敏

        Args:
            data: 原始数据
            rules: 脱敏规则列表（可选，覆盖默认规则）

        Returns:
            Dict: 脱敏后的数据
        """
        result = data.copy()

        # 使用指定规则或默认规则
        if rules:
            for rule in rules:
                result = self._apply_rule(result, rule)
        else:
            # 应用配置中的规则
            for rule in self.config.rules:
                result = self._apply_rule(result, rule)

        return result

    def _apply_rule(
        self, data: Dict[str, Any], rule: DesensitizeRule
    ) -> Dict[str, Any]:
        """
        应用单条脱敏规则

        Args:
            data: 数据
            rule: 脱敏规则

        Returns:
            Dict: 处理后的数据
        """
        # 获取字段值
        value = self._get_nested_value(data, rule.field)

        if value is None or not isinstance(value, str):
            return data

        # 执行脱敏
        desensitized_value = self._desensitize_value(
            value, rule.method, rule.prefix_len, rule.suffix_len
        )

        # 设置脱敏后的值
        result = data.copy()
        self._set_nested_value(result, rule.field, desensitized_value)

        return result

    def _desensitize_value(
        self,
        value: str,
        method: str,
        prefix_len: int,
        suffix_len: int,
    ) -> str:
        """
        对值进行脱敏

        Args:
            value: 原始值
            method: 脱敏方法
            prefix_len: 保留前缀长度
            suffix_len: 保留后缀长度

        Returns:
            str: 脱敏后的值
        """
        # 检查是否有自定义方法
        if method in self._custom_methods:
            return self._custom_methods[method](value)

        # 使用内置方法
        if method == "mask":
            return self._mask(value, prefix_len, suffix_len)
        elif method == "email_mask":
            return self._email_mask(value, prefix_len)
        elif method == "phone_mask":
            return self._phone_mask(value)
        elif method == "id_card_mask":
            return self._id_card_mask(value)
        elif method == "full_mask":
            return "*" * len(value)
        else:
            logger.warning(f"未知的脱敏方法: {method}")
            return value

    def _mask(
        self, value: str, prefix_len: int, suffix_len: int, mask_char: str = "*"
    ) -> str:
        """
        通用脱敏方法

        Args:
            value: 原始值
            prefix_len: 保留前缀长度
            suffix_len: 保留后缀长度
            mask_char: 掩码字符

        Returns:
            str: 脱敏后的值
        """
        if not value:
            return value

        total_len = len(value)

        # 如果总长度小于等于前缀+后缀长度，直接返回
        if total_len <= prefix_len + suffix_len:
            return value

        # 计算掩码长度
        mask_len = total_len - prefix_len - suffix_len

        # 构建脱敏后的值
        prefix = value[:prefix_len] if prefix_len > 0 else ""
        suffix = value[-suffix_len:] if suffix_len > 0 else ""
        mask = mask_char * mask_len

        return f"{prefix}{mask}{suffix}"

    def _email_mask(self, email: str, prefix_len: int = 3) -> str:
        """
        邮箱脱敏

        Args:
            email: 邮箱
            prefix_len: 保留前缀长度

        Returns:
            str: 脱敏后的邮箱
        """
        if not email or "@" not in email:
            return email

        local, domain = email.split("@", 1)

        # 保留前prefix_len字符（如果足够），否则保留前2字符（如果>=2），否则保留前1字符
        if len(local) >= prefix_len:
            masked_local = local[:prefix_len] + "***"
        elif len(local) >= 2:
            masked_local = local[:2] + "***"
        else:
            masked_local = local[0] + "***"

        return f"{masked_local}@{domain}"

    def _phone_mask(self, phone: str) -> str:
        """
        手机号脱敏

        Args:
            phone: 手机号

        Returns:
            str: 脱敏后的手机号
        """
        if not phone or len(phone) < 7:
            return phone

        # 保留前3位 + **** + 后4位（如果长度>=11），否则后3位
        suffix_len = 4 if len(phone) >= 11 else 3
        return phone[:3] + "****" + phone[-suffix_len:]

    def _id_card_mask(self, id_card: str) -> str:
        """
        身份证号脱敏

        Args:
            id_card: 身份证号

        Returns:
            str: 脱敏后的身份证号
        """
        if not id_card or len(id_card) < 10:
            return id_card

        return id_card[:6] + "********" + id_card[-4:]

    def register_method(self, name: str, method: Callable[[str], str]) -> None:
        """
        注册自定义脱敏方法

        Args:
            name: 方法名
            method: 方法实现
        """
        self._custom_methods[name] = method
        logger.info(f"注册自定义脱敏方法: {name}")

    def _get_nested_value(self, data: Dict[str, Any], field: str) -> Any:
        """
        获取嵌套字段值

        Args:
            data: 数据字典
            field: 字段路径

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


# 默认脱敏配置
DEFAULT_DESENSITIZE_CONFIG = DesensitizeConfig(
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
        DesensitizeRule(
            field="personal_info.id_card",
            method="id_card_mask",
            prefix_len=6,
            suffix_len=4,
        ),
    ]
)

# 全局脱敏器实例
desensitizer = Desensitizer(config=DEFAULT_DESENSITIZE_CONFIG)


def get_desensitizer() -> Desensitizer:
    """获取脱敏器实例"""
    return desensitizer
