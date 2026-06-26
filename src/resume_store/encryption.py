"""
智能招聘 RAG 推荐系统 - PII 加密模块

使用 Fernet 对称加密保护 PII 数据（手机号、邮箱）
"""

import base64
from typing import Optional

from cryptography.fernet import Fernet

from src.common.config import get_settings
from src.common.logger import get_logger

logger = get_logger("encryption")


class PIIEncryptor:
    """PII 数据加密器"""

    _instance: Optional["PIIEncryptor"] = None
    _fernet: Optional[Fernet] = None

    def __new__(cls) -> "PIIEncryptor":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_key(self) -> bytes:
        """获取 PII 加密密钥（独立于 JWT 密钥）"""
        settings = get_settings()
        key = settings.pii.PII_ENCRYPTION_KEY
        return key.encode() if isinstance(key, str) else key

    def _get_fernet(self) -> Fernet:
        """获取 Fernet 实例"""
        if self._fernet is None:
            key = self._get_key()
            self._fernet = Fernet(key)
        return self._fernet

    def reset(self) -> None:
        """重置加密器密钥缓存（用于密钥轮换后重新初始化）"""
        self._fernet = None

    def encrypt(self, plaintext: str) -> str:
        """
        加密明文

        Args:
            plaintext: 明文字符串

        Returns:
            str: 加密后的字符串（base64 编码）
        """
        if not plaintext:
            return ""

        try:
            fernet = self._get_fernet()
            encrypted = fernet.encrypt(plaintext.encode("utf-8"))
            return encrypted.decode("utf-8")
        except Exception as e:
            logger.error(f"加密失败: {str(e)}")
            raise

    def decrypt(self, ciphertext: str) -> str:
        """
        解密密文

        Args:
            ciphertext: 加密后的字符串（base64 编码）

        Returns:
            str: 解密后的明文字符串
        """
        if not ciphertext:
            return ""

        try:
            fernet = self._get_fernet()
            decrypted = fernet.decrypt(ciphertext.encode("utf-8"))
            return decrypted.decode("utf-8")
        except Exception as e:
            logger.error(f"解密失败: {str(e)}")
            raise

    def mask_phone(self, phone: str) -> str:
        """
        手机号脱敏

        Args:
            phone: 手机号

        Returns:
            str: 脱敏后的手机号（如 138****1234）
        """
        if not phone or len(phone) < 7:
            return phone

        # 保留前3位 + **** + 后4位（如果长度>=11），否则后3位
        suffix_len = 4 if len(phone) >= 11 else 3
        return phone[:3] + "****" + phone[-suffix_len:]

    def mask_email(self, email: str) -> str:
        """
        邮箱脱敏

        Args:
            email: 邮箱地址

        Returns:
            str: 脱敏后的邮箱（如 zhang***@gmail.com）
        """
        if not email or "@" not in email:
            return email

        local, domain = email.split("@", 1)

        # 保留前3字符（如果>=3），否则保留前2字符（如果>=2），否则保留前1字符
        if len(local) >= 3:
            masked_local = local[:3] + "***"
        elif len(local) >= 2:
            masked_local = local[:2] + "***"
        else:
            masked_local = local[0] + "***"

        return f"{masked_local}@{domain}"

    def encrypt_pii_fields(self, data: dict) -> dict:
        """
        加密数据中的 PII 字段

        Args:
            data: 包含 PII 字段的数据

        Returns:
            dict: 加密后的数据
        """
        result = data.copy()

        # 加密手机号
        if "phone" in result and result["phone"]:
            result["phone"] = self.encrypt(result["phone"])

        # 加密邮箱
        if "email" in result and result["email"]:
            result["email"] = self.encrypt(result["email"])

        return result

    def decrypt_pii_fields(self, data: dict) -> dict:
        """
        解密数据中的 PII 字段

        Args:
            data: 包含加密 PII 字段的数据

        Returns:
            dict: 解密后的数据
        """
        result = data.copy()

        # 解密手机号
        if "phone" in result and result["phone"]:
            try:
                result["phone"] = self.decrypt(result["phone"])
            except Exception:
                # 如果解密失败，可能是明文，保留原值
                pass

        # 解密邮箱
        if "email" in result and result["email"]:
            try:
                result["email"] = self.decrypt(result["email"])
            except Exception:
                # 如果解密失败，可能是明文，保留原值
                pass

        return result


# 全局加密器实例
pii_encryptor = PIIEncryptor()


def get_encryptor() -> PIIEncryptor:
    """获取 PII 加密器实例"""
    return pii_encryptor
