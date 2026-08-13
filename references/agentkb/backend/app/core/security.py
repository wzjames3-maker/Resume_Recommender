from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_access_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "type": "access", "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def create_refresh_token(user_id: int) -> tuple[str, str]:
    jti = uuid4().hex
    payload = {"sub": str(user_id), "type": "refresh", "jti": jti, "exp": datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), jti

def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])