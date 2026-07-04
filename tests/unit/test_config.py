"""
智能招聘 RAG 推荐系统 - 配置管理测试
"""

import os

import pytest

from src.common.config import (
    AppSettings,
    EmbeddingSettings,
    Environment,
    LLMSettings,
    MilvusSettings,
    MongoDBSettings,
    QueueSettings,
    RedisSettings,
    Settings,
    get_settings,
)


class TestAppSettings:
    """AppSettings 测试"""

    def test_default_values(self, monkeypatch):
        """测试默认值"""
        for key in ["APP_NAME", "APP_ENV", "DEBUG", "HOST", "PORT", "CORS_ORIGINS",
                     "LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL",
                     "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL",
                     "MONGODB_URL", "MONGODB_USER", "MONGODB_PASSWORD", "MONGODB_DATABASE",
                     "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD",
                     "MILVUS_URI", "MILVUS_TOKEN", "MILVUS_VERSION_COMPAT",
                     "PII_ENCRYPTION_KEY", "JWT_SECRET_KEY"]:
            monkeypatch.delenv(key, raising=False)

        settings = AppSettings(APP_ENV=Environment.DEV)
        assert settings.APP_NAME == "resume-rag"
        assert settings.APP_ENV == Environment.DEV
        assert settings.DEBUG is False
        assert settings.HOST == "0.0.0.0"
        assert settings.PORT == 8000

    def test_custom_values(self, monkeypatch):
        """测试自定义值"""
        monkeypatch.delenv("APP_NAME", raising=False)
        monkeypatch.setenv("APP_NAME", "test-app")
        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("PORT", "9000")

        settings = AppSettings()
        assert settings.APP_NAME == "test-app"
        assert settings.APP_ENV == Environment.PROD
        assert settings.DEBUG is False
        assert settings.PORT == 9000

    def test_invalid_env(self):
        """测试无效环境值"""
        with pytest.raises(ValueError):
            AppSettings(APP_ENV="invalid")


class TestLLMSettings:
    """LLMSettings 测试"""

    def test_default_values(self, monkeypatch):
        """测试默认值"""
        for key in ["LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL",
                     "LLM_TEMPERATURE", "LLM_MAX_TOKENS"]:
            monkeypatch.delenv(key, raising=False)

        settings = LLMSettings()
        assert settings.LLM_PROVIDER == "deepseek"
        assert settings.LLM_MODEL == "deepseek-chat"
        assert settings.LLM_TEMPERATURE == 0.7
        assert settings.LLM_MAX_TOKENS == 4096

    def test_custom_values(self, monkeypatch):
        """测试自定义值"""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("LLM_MODEL", "gpt-4")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.5")

        settings = LLMSettings()
        assert settings.LLM_PROVIDER == "openai"
        assert settings.LLM_MODEL == "gpt-4"
        assert settings.LLM_TEMPERATURE == 0.5

    def test_temperature_validation(self):
        """测试温度参数验证"""
        # 有效值
        LLMSettings(LLM_TEMPERATURE=0.0)
        LLMSettings(LLM_TEMPERATURE=2.0)

        # 无效值
        with pytest.raises(ValueError):
            LLMSettings(LLM_TEMPERATURE=-0.1)
        with pytest.raises(ValueError):
            LLMSettings(LLM_TEMPERATURE=2.1)


class TestEmbeddingSettings:
    """EmbeddingSettings 测试"""

    def test_default_values(self, monkeypatch):
        """测试默认值"""
        for key in ["EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_API_KEY",
                     "EMBEDDING_BASE_URL", "EMBEDDING_DIMENSION"]:
            monkeypatch.delenv(key, raising=False)

        settings = EmbeddingSettings()
        assert settings.EMBEDDING_PROVIDER == "bge-m3"
        assert settings.EMBEDDING_MODEL == "BAAI/bge-m3"
        assert settings.EMBEDDING_DIMENSION == 1024


class TestMilvusSettings:
    """MilvusSettings 测试"""

    def test_default_values(self, monkeypatch):
        """测试默认值"""
        for key in ["MILVUS_URI", "MILVUS_TOKEN", "MILVUS_COLLECTION_PREFIX",
                     "MILVUS_DIMENSION", "MILVUS_VERSION_COMPAT"]:
            monkeypatch.delenv(key, raising=False)

        settings = MilvusSettings()
        assert settings.MILVUS_URI == "http://localhost:19530"
        assert settings.MILVUS_COLLECTION_PREFIX == "resume_"
        assert settings.MILVUS_DIMENSION == 1024
        assert settings.MILVUS_VERSION_COMPAT == 2.4

    def test_version_compat(self, monkeypatch):
        """测试版本兼容性配置"""
        monkeypatch.delenv("MILVUS_VERSION_COMPAT", raising=False)
        monkeypatch.setenv("MILVUS_VERSION_COMPAT", "2.5")
        settings = MilvusSettings()
        assert settings.MILVUS_VERSION_COMPAT == 2.5


class TestMongoDBSettings:
    """MongoDBSettings 测试"""

    def test_default_values(self, monkeypatch):
        """测试默认值"""
        for key in ["MONGODB_URL", "MONGODB_USER", "MONGODB_PASSWORD",
                     "MONGODB_DATABASE"]:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MONGODB_PASSWORD", "password")

        settings = MongoDBSettings()
        assert settings.MONGODB_URL == "mongodb://localhost:27017"
        assert settings.MONGODB_USER == "admin"
        assert settings.MONGODB_PASSWORD == "password"
        assert settings.MONGODB_DATABASE == "resume_rag"


class TestRedisSettings:
    """RedisSettings 测试"""

    def test_default_values(self, monkeypatch):
        """测试默认值"""
        for key in ["REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_PASSWORD"]:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("REDIS_PASSWORD", "password")

        settings = RedisSettings()
        assert settings.REDIS_HOST == "localhost"
        assert settings.REDIS_PORT == 6379
        assert settings.REDIS_DB == 0
        assert settings.REDIS_PASSWORD == "password"

    def test_redis_url_with_password(self):
        """测试带密码的 Redis URL"""
        settings = RedisSettings(
            REDIS_HOST="redis-server",
            REDIS_PORT=6380,
            REDIS_DB=1,
            REDIS_PASSWORD="secret",
        )
        expected = "redis://:secret@redis-server:6380/1"
        assert settings.redis_url == expected

    def test_redis_url_without_password(self):
        """测试不带密码的 Redis URL"""
        settings = RedisSettings(
            REDIS_HOST="redis-server",
            REDIS_PORT=6379,
            REDIS_DB=0,
            REDIS_PASSWORD="",
        )
        expected = "redis://redis-server:6379/0"
        assert settings.redis_url == expected

    def test_port_validation(self):
        """测试端口验证"""
        # 有效端口
        RedisSettings(REDIS_PORT=1)
        RedisSettings(REDIS_PORT=65535)

        # 无效端口
        with pytest.raises(ValueError):
            RedisSettings(REDIS_PORT=0)
        with pytest.raises(ValueError):
            RedisSettings(REDIS_PORT=65536)

    def test_db_validation(self):
        """测试数据库编号验证"""
        # 有效值
        RedisSettings(REDIS_DB=0)
        RedisSettings(REDIS_DB=15)

        # 无效值
        with pytest.raises(ValueError):
            RedisSettings(REDIS_DB=-1)
        with pytest.raises(ValueError):
            RedisSettings(REDIS_DB=16)


class TestQueueSettings:
    """QueueSettings 测试"""

    def test_default_values(self):
        """测试默认值"""
        settings = QueueSettings()
        assert settings.QUEUE_NAME == "resume-rag"
        assert settings.QUEUE_MAX_JOBS == 10
        assert settings.QUEUE_RETRY == 3
        assert settings.QUEUE_JOB_TIMEOUT == 300
        assert settings.QUEUE_RESULT_EXPIRATION == 3600


class TestSettings:
    """Settings 聚合测试"""

    def test_settings_initialization(self):
        """测试配置初始化"""
        settings = Settings()
        assert isinstance(settings.app, AppSettings)
        assert isinstance(settings.llm, LLMSettings)
        assert isinstance(settings.embedding, EmbeddingSettings)
        assert isinstance(settings.milvus, MilvusSettings)
        assert isinstance(settings.mongodb, MongoDBSettings)
        assert isinstance(settings.redis, RedisSettings)
        assert isinstance(settings.queue, QueueSettings)

    def test_get_settings_singleton(self):
        """测试 get_settings 单例模式"""
        # 清除缓存
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2


class TestEnvironmentIntegration:
    """环境变量集成测试"""

    def test_env_file_loading(self, monkeypatch):
        """测试 .env 文件加载"""
        monkeypatch.delenv("APP_NAME", raising=False)
        monkeypatch.setenv("APP_NAME", "test-from-env")
        monkeypatch.setenv("PORT", "9999")

        settings = AppSettings()
        assert settings.APP_NAME == "test-from-env"
        assert settings.PORT == 9999
