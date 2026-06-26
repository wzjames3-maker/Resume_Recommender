"""用户密码管理模块（bcrypt 哈希）"""
from typing import Dict, Optional

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """对密码进行 bcrypt 哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码与 bcrypt 哈希是否匹配"""
    return pwd_context.verify(plain_password, hashed_password)


# 默认用户（供开发/测试环境使用，哈希存储）
# 生产环境应从 MongoDB users collection 加载
DEFAULT_USERS: Dict[str, Dict[str, str]] = {}


def init_default_users():
    """初始化默认用户（仅首次调用时生效）"""
    global DEFAULT_USERS
    if not DEFAULT_USERS:
        DEFAULT_USERS = {
            "admin": {
                "user_id": "admin-001",
                "password_hash": hash_password("admin123"),
                "role": "admin",
            },
            "hr": {
                "user_id": "hr-001",
                "password_hash": hash_password("hr123"),
                "role": "hr",
            },
            "viewer": {
                "user_id": "viewer-001",
                "password_hash": hash_password("viewer123"),
                "role": "viewer",
            },
        }


def get_user_by_username(username: str) -> Optional[Dict[str, str]]:
    """
    按用户名查找用户。
    优先从 MongoDB users collection 查找，失败回退到内存字典。
    """
    # 尝试从 MongoDB 获取
    try:
        from src.resume_store.connection import mongodb_connection
        db = mongodb_connection.get_database()
        doc = db.users.find_one({"username": username})
        if doc:
            return {
                "user_id": doc.get("user_id", ""),
                "password_hash": doc.get("password_hash", ""),
                "role": doc.get("role", ""),
            }
    except Exception:
        pass

    # 回退到内存字典（开发/测试环境）
    init_default_users()
    return DEFAULT_USERS.get(username)
