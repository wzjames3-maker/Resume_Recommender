import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_ENC_KEY_HEX = settings.model_key_enc_key
if len(_ENC_KEY_HEX) != 64 or _ENC_KEY_HEX == "0" * 64:
    raise RuntimeError("MODEL_KEY_ENC_KEY 必须设置为 32 字节（64 位 hex）密钥，禁止使用默认占位值")
KEY = AESGCM(bytes.fromhex(_ENC_KEY_HEX))

def encrypt_secret(plain: str) -> str:
    nonce = os.urandom(12)
    return (nonce + KEY.encrypt(nonce, plain.encode(), None)).hex()

def decrypt_secret(enc_hex: str) -> str:
    raw = bytes.fromhex(enc_hex)
    return KEY.decrypt(raw[:12], raw[12:], None).decode()

def mask_key(key: str) -> str:
    return key[:8] + "****" if len(key) > 8 else "****"