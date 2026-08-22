import hmac
import hashlib
import pickle
import os
import sys
from kombu.serialization import register

_local_secret_key = os.environ.get('MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY')
if not _local_secret_key:
    try:
        from xpack import get_md5  # 闭源发行版提供随机密钥

        _local_secret_key = get_md5()
    except ImportError:
        _local_secret_key = None
if not _local_secret_key:
    # 未显式注入随机 HMAC 键 → fail-closed（生产）；测试/迁移允许显式放行
    _allow_insecure = os.environ.get("MAXKB_ALLOW_INSECURE_HMAC") == "1" or any(
        a in sys.argv for a in ("test", "migrate", "collectstatic", "makemigrations", "shell", "check")
    )
    # 兼容：DEBUG=true 的本地开发也允许临时放行，但需显式告警
    _debug_env = os.environ.get("MAXKB_DEBUG", "")
    _is_debug = _debug_env.strip().lower() in ("true", "1", "yes", "on") if _debug_env else False
    if not _allow_insecure and not _is_debug:
        raise RuntimeError(
            "MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY must be set to a strong random value "
            "(or provide xpack.get_md5). Generate with: python -c \"import secrets; print(secrets.token_urlsafe(50))\" "
            "and set env MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY. For local tests set MAXKB_ALLOW_INSECURE_HMAC=1."
        )
    # 开发/测试放行：使用一次性随机密钥（进程内一致，跨进程/重启不共享 → 仅本地单机可用）
    import secrets as _secrets

    _local_secret_key = _secrets.token_urlsafe(32)
    # 仅在非测试时告警，避免刷屏
    if "test" not in sys.argv:
        import warnings as _warnings

        _warnings.warn(
            "MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY not set; using ephemeral random key (dev/test only). "
            "Set a persistent key for production.",
            UserWarning,
            stacklevel=2,
        )

def secure_dumps(obj):
    data = pickle.dumps(obj)
    signature = hmac.new(_local_secret_key.encode(), data, hashlib.sha256).digest()
    return signature + data

def secure_loads(signed_data):
    if len(signed_data) < 32:
        raise ValueError("Invalid signed data packet")
    signature = signed_data[:32]
    payload = signed_data[32:]
    expected_signature = hmac.new(_local_secret_key.encode(), payload, hashlib.sha256).digest()
    if hmac.compare_digest(signature, expected_signature):
        return pickle.loads(payload)
    else:
        raise ValueError("Security Alert: Task signature mismatch! Potential tampering detected.")

def register_hmac_signed_serializer():
    register(
        'hmac_signed_serializer',
        secure_dumps,
        secure_loads,
        content_type='application/x-python-hmac-signed-serialize',
        content_encoding='binary'
    )