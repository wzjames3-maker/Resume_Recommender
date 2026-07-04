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


_DEFAULT_USERS: Dict[str, Dict[str, str]] = {}


def _init_default_users():
    """初始化默认用户（仅首次调用时生效）"""
    global _DEFAULT_USERS
    if not _DEFAULT_USERS:
        _DEFAULT_USERS = {
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
    优先从 MongoDB users collection 查找，失败时根据环境决定是否回退。
    """
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
    except Exception as e:
        from src.common.config import Environment, get_settings
        settings = get_settings()
        if settings.app.APP_ENV == Environment.PROD:
            raise RuntimeError(f"生产环境 MongoDB 用户查询失败，禁止回退默认用户: {e}") from e
        from src.common.logger import get_logger
        get_logger("user_store").warning(f"MongoDB 查询失败，回退到默认用户: {e}")

    _init_default_users()
    return _DEFAULT_USERS.get(username)
