"""
智能招聘 RAG 推荐系统 - 统一配置管理

使用 pydantic-settings 的 BaseSettings，所有配置从环境变量读取
"""

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """应用环境"""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"
    TEST = "test"


class AppSettings(BaseSettings):
    """应用基础配置"""

    model_config = SettingsConfigDict(
                env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = Field(default="resume-rag", description="应用名称")
    APP_ENV: Environment = Field(default=Environment.DEV, description="运行环境")
    DEBUG: bool = Field(default=False, description="调试模式")
    HOST: str = Field(default="0.0.0.0", description="监听地址")
    PORT: int = Field(default=8000, description="监听端口")

    CORS_ORIGINS: str = Field(default="", description="允许的 CORS 来源，逗号分隔")

    @field_validator("APP_ENV", mode="before")
    @classmethod
    def validate_env(cls, v: str) -> Environment:
        if isinstance(v, str):
            return Environment(v.lower())
        return v


class LLMSettings(BaseSettings):
    """LLM 配置"""

    model_config = SettingsConfigDict(
                env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    LLM_PROVIDER: str = Field(default="deepseek", description="LLM 提供商")
    LLM_MODEL: str = Field(default="deepseek-chat", description="模型名称")
    LLM_API_KEY: str = Field(default="", description="API Key")
    LLM_BASE_URL: str = Field(
        default="https://api.deepseek.com/v1", description="API Base URL"
    )
    LLM_TEMPERATURE: float = Field(default=0.7, description="温度参数", ge=0.0, le=2.0)
    LLM_MAX_TOKENS: int = Field(default=4096, description="最大 Token 数", gt=0)


class EmbeddingSettings(BaseSettings):
    """Embedding 配置"""

    model_config = SettingsConfigDict(
                env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    EMBEDDING_PROVIDER: str = Field(default="bge-m3", description="Embedding 提供商")
    EMBEDDING_MODEL: str = Field(default="BAAI/bge-m3", description="模型名称")
    EMBEDDING_API_KEY: str = Field(default="", description="API Key")
    EMBEDDING_BASE_URL: str = Field(
        default="https://api.siliconflow.cn/v1", description="API Base URL"
    )
    EMBEDDING_DIMENSION: int = Field(default=1024, description="向量维度", gt=0)


class MilvusSettings(BaseSettings):
    """Milvus 配置"""

    model_config = SettingsConfigDict(
                env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    MILVUS_URI: str = Field(
        default="http://localhost:19530", description="Milvus 连接地址"
    )
    MILVUS_TOKEN: str = Field(default="", description="Milvus 认证 Token")
    MILVUS_COLLECTION_PREFIX: str = Field(
        default="resume_", description="Collection 名称前缀"
    )
    MILVUS_DIMENSION: int = Field(default=1024, description="向量维度", gt=0)
    MILVUS_VERSION_COMPAT: float = Field(
        default=2.4, description="目标 Milvus 版本，用于运行时版本对齐检查"
    )


class MongoDBSettings(BaseSettings):
    """MongoDB 配置"""

    model_config = SettingsConfigDict(
                env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    MONGODB_URL: str = Field(
        default="mongodb://localhost:27017", description="MongoDB 连接地址"
    )
    MONGODB_USER: str = Field(default="admin", description="MongoDB 用户名")
    MONGODB_PASSWORD: str = Field(default=..., description="MongoDB 密码（必填）")
    MONGODB_DATABASE: str = Field(default="resume_rag", description="数据库名称")


class RedisSettings(BaseSettings):
    """Redis 配置（用于会话缓存 + ARQ 任务队列 + 分布式缓存）"""

    model_config = SettingsConfigDict(
                env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    REDIS_HOST: str = Field(default="localhost", description="Redis 主机")
    REDIS_PORT: int = Field(default=6379, description="Redis 端口", gt=0, le=65535)
    REDIS_DB: int = Field(default=0, description="Redis 数据库编号", ge=0, le=15)
    REDIS_PASSWORD: str = Field(default=..., description="Redis 密码（必填）")

    @property
    def redis_url(self) -> str:
        """构建 Redis 连接 URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


class PIISettings(BaseSettings):
    """PII 加密配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PII_ENCRYPTION_KEY: str = Field(
        default=..., description="PII 加密密钥（Fernet 原生 base64 key，必填）"
    )


class QueueSettings(BaseSettings):
    """ARQ 异步任务队列配置"""

    model_config = SettingsConfigDict(
                env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    QUEUE_NAME: str = Field(default="resume-rag", description="队列名称")
    QUEUE_MAX_JOBS: int = Field(default=10, description="最大并发任务数", gt=0)
    QUEUE_RETRY: int = Field(default=3, description="任务重试次数", ge=0)
    QUEUE_JOB_TIMEOUT: int = Field(default=300, description="任务超时时间（秒）", gt=0)
    QUEUE_RESULT_EXPIRATION: int = Field(
        default=3600, description="任务结果保留时间（秒）", gt=0
    )


class JWTSettings(BaseSettings):
    """JWT 认证配置"""

    model_config = SettingsConfigDict(
                env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    JWT_SECRET_KEY: str = Field(
        default=..., description="JWT 密钥（必填）"
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT 算法")
    JWT_EXPIRATION_HOURS: int = Field(default=24, description="Token 有效期（小时）", gt=0)

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        import os

        weak_keys = [
            "resume-rag-jwt-secret-key-2026",
            "your-secret-key",
            "changeme",
            "secret",
        ]
        is_weak = v.lower() in [k.lower() for k in weak_keys]
        is_prod = os.environ.get("APP_ENV", "").lower() == "prod"

        if is_prod:
            if len(v) < 32:
                raise ValueError("生产环境 JWT_SECRET_KEY 长度不能少于 32 字符")
            if is_weak:
                raise ValueError(
                    f"JWT_SECRET_KEY 为已知弱密钥，请使用 python -c "
                    f'"import secrets; print(secrets.token_hex(64))" 生成'
                )
        elif is_weak:
            import logging
            logging.getLogger("config").warning(
                "JWT_SECRET_KEY 为已知弱密钥，生产环境请更换"
            )
        return v


class Settings(BaseSettings):
    """全局配置聚合"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用配置
    app: AppSettings = Field(default_factory=AppSettings)

    # LLM 配置
    llm: LLMSettings = Field(default_factory=LLMSettings)

    # Embedding 配置
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)

    # Milvus 配置
    milvus: MilvusSettings = Field(default_factory=MilvusSettings)

    # MongoDB 配置
    mongodb: MongoDBSettings = Field(default_factory=MongoDBSettings)

    # Redis 配置
    redis: RedisSettings = Field(default_factory=RedisSettings)

    # 队列配置
    queue: QueueSettings = Field(default_factory=QueueSettings)

    # PII 加密配置
    pii: PIISettings = Field(default_factory=PIISettings)

    # JWT 配置
    jwt: JWTSettings = Field(default_factory=JWTSettings)


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置（单例模式）"""
    return Settings()
