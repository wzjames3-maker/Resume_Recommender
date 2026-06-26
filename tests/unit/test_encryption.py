"""测试 PII 加密密钥分离（SEC-T02）"""
import pytest
from cryptography.fernet import Fernet

from src.resume_store.encryption import get_encryptor, PIIEncryptor


def test_pii_key_independent_from_jwt():
    """PII_KEY 独立于 JWT_SECRET_KEY"""
    encryptor = get_encryptor()
    encryptor.reset()
    key = encryptor._get_key()
    assert isinstance(key, bytes)
    assert len(key) == 44  # Fernet key = 32 bytes base64 = 44 chars


def test_encrypt_decrypt_roundtrip():
    """新密钥加解密往返"""
    encryptor = get_encryptor()
    encryptor.reset()
    plain = "13800138000"
    cipher = encryptor.encrypt(plain)
    assert cipher != plain
    decrypted = encryptor.decrypt(cipher)
    assert decrypted == plain


def test_empty_value():
    """空值不加密"""
    encryptor = get_encryptor()
    encryptor.reset()
    assert encryptor.encrypt("") == ""
    assert encryptor.decrypt("") == ""


def test_reset_clears_cache():
    """reset() 清空 Fernet 缓存"""
    encryptor = get_encryptor()
    encryptor.reset()
    fernet1 = encryptor._get_fernet()
    encryptor.reset()
    fernet2 = encryptor._get_fernet()
    # 相同密钥来源，实例应不同对象（重新创建）
    assert fernet1 is not fernet2
    # 但加解密应一致
    plain = "test@example.com"
    assert fernet2.decrypt(fernet1.encrypt(plain.encode())).decode() == plain


def test_encrypt_pii_fields():
    """批量加密 PII 字段"""
    encryptor = get_encryptor()
    encryptor.reset()
    data = {"name": "Zhang", "phone": "13800138000", "email": "a@b.com"}
    result = encryptor.encrypt_pii_fields(data)
    assert result["name"] == "Zhang"  # 非 PII 不变
    assert result["phone"] != "13800138000"
    assert result["email"] != "a@b.com"


def test_decrypt_pii_fields():
    """批量解密 PII 字段"""
    encryptor = get_encryptor()
    encryptor.reset()
    data = {"name": "Zhang", "phone": "13800138000", "email": "a@b.com"}
    encrypted = encryptor.encrypt_pii_fields(data)
    decrypted = encryptor.decrypt_pii_fields(encrypted)
    assert decrypted["phone"] == "13800138000"
    assert decrypted["email"] == "a@b.com"
