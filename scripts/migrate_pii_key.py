"""
PII 密钥迁移脚本

用途：将旧密钥（sha256(JWT_SECRET_KEY)派生的 Fernet key）加密的 phone/email
     迁移为新密钥（PII_ENCRYPTION_KEY 直接作为 Fernet key）加密。

使用方法：
    1. 确认 .env 中已配置：
       - 旧的 JWT_SECRET_KEY（已退出使用的旧值）
       - 新的 PII_ENCRYPTION_KEY（当前使用的值）
    2. 运行: python scripts/migrate_pii_key.py
    3. 验证解密无误后，从 .env 中移除旧的 JWT_SECRET_KEY

安全：
    - 迁移脚本仅在本地运行，不走网络
    - 旧密钥应在迁移验证后从 .env 中移除
"""

import base64
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.fernet import Fernet

from src.common.config import get_settings
from src.resume_store.connection import get_resume_collection


def get_old_fernet_key(jwt_secret: str) -> bytes:
    """从旧的 JWT_SECRET_KEY 派生 Fernet key（sha256 方案）"""
    return base64.urlsafe_b64encode(hashlib.sha256(jwt_secret.encode()).digest())


def main():
    settings = get_settings()
    old_jwt_secret = os.environ.get("OLD_JWT_SECRET_KEY", "")
    if not old_jwt_secret:
        print("ERROR: 请设置环境变量 OLD_JWT_SECRET_KEY 为旧 JWT 密钥值")
        print("  示例: $env:OLD_JWT_SECRET_KEY='resume-rag-jwt-secret-key-2026'")
        print("  然后: python scripts/migrate_pii_key.py")
        sys.exit(1)

    new_key = settings.pii.PII_ENCRYPTION_KEY
    if isinstance(new_key, str):
        new_key = new_key.encode()

    old_fernet_key = get_old_fernet_key(old_jwt_secret)
    old_fernet = Fernet(old_fernet_key)
    new_fernet = Fernet(new_key)

    collection = get_resume_collection()
    encrypted_fields = ["personal_info.phone", "personal_info.email"]

    migrated = 0
    failed = 0

    print(f"开始迁移: 使用旧密钥派生自 sha256(OLD_JWT_SECRET_KEY)")
    print(f"新密钥来自 PII_ENCRYPTION_KEY")
    print()

    for doc in collection.find():
        if "_encrypted_fields" not in doc or not doc["_encrypted_fields"]:
            continue

        modified = False
        for field_path in doc["_encrypted_fields"]:
            # 支持 "personal_info.phone" → doc["personal_info"]["phone"]
            parts = field_path.split(".")
            value = doc
            for part in parts[:-1]:
                value = value.get(part, {})
            field_name = parts[-1]

            if field_name not in value or not value.get(field_name):
                continue

            ciphertext = value[field_name]
            try:
                # 先用新 key 尝试解密（已迁移的跳过）
                new_fernet.decrypt(ciphertext.encode())
                continue  # 已迁移，跳过
            except Exception:
                pass

            try:
                # 用旧 key 解密
                plaintext = old_fernet.decrypt(ciphertext.encode()).decode("utf-8")
                # 用新 key 重新加密
                new_ciphertext = new_fernet.encrypt(plaintext.encode()).decode("utf-8")
                # 更新文档
                current = doc
                for part in parts[:-1]:
                    current = current[part]
                current[field_name] = new_ciphertext
                modified = True
                print(f"  迁移: resume_id={doc.get('id', '?')}, field={field_path}")
            except Exception as e:
                failed += 1
                print(f"  失败: resume_id={doc.get('id', '?')}, field={field_path}, error={e}")

        if modified:
            collection.replace_one({"_id": doc["_id"]}, doc)
            migrated += 1

    print()
    print(f"迁移完成: {migrated} 份简历已更新, {failed} 个字段失败")

    # 验证：随机抽查一条已迁移记录可正常解密
    if migrated > 0:
        sample = collection.find_one({"_encrypted_fields": {"$exists": True, "$not": {"$size": 0}}})
        if sample:
            try:
                field_path = sample["_encrypted_fields"][0]
                parts = field_path.split(".")
                val = sample
                for p in parts:
                    val = val[p]
                new_fernet.decrypt(val.encode())
                print("验证通过: 新密钥可正常解密已迁移数据")
            except Exception as e:
                print(f"验证失败: {e}")


if __name__ == "__main__":
    main()
