from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AgentKB Platform"
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/agentkb"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 30
    refresh_token_ttl_days: int = 7
    model_key_enc_key: str = ""
    resume_max_auto_retries: int = 2  # 生产最多自动重试 2 次；评测 manifest 运行时设 1（A-2）
    model_config = {"env_file": ".env"}

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_must_be_strong(cls, v: str) -> str:
        if not v or v == "change-me":
            raise ValueError("JWT_SECRET must be set to a strong secret, not the placeholder 'change-me'")
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 chars")
        return v

    @field_validator("model_key_enc_key")
    @classmethod
    def _model_key_enc_key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("MODEL_KEY_ENC_KEY must be set (64 hex chars)")
        if len(v) != 64:
            raise ValueError("MODEL_KEY_ENC_KEY must be exactly 64 hex chars")
        if v == "0" * 64:
            raise ValueError("MODEL_KEY_ENC_KEY must not be all zeros")
        return v

settings = Settings()