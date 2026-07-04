"""
智能招聘 RAG 推荐系统 - 测试配置
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 设置测试环境变量
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-testing-purposes"
os.environ["JWT_EXPIRATION_HOURS"] = "2"
os.environ["LLM_API_KEY"] = "test-api-key"
os.environ["EMBEDDING_API_KEY"] = "test-api-key"
os.environ["APP_DEBUG"] = "true"
os.environ["LLM_MODEL"] = "deepseek-chat"


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """设置测试环境"""
    # 清除 settings 缓存
    from src.common.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def client():
    """创建测试客户端（session 级别）"""
    from fastapi.testclient import TestClient
    from src.api.main import app
    return TestClient(app)


@pytest.fixture(scope="function")
def fresh_client():
    """创建测试客户端（函数级别，每个测试函数独立）"""
    from fastapi.testclient import TestClient
    from src.api.main import app
    return TestClient(app)


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_mongodb():
    """模拟 MongoDB 连接"""
    with patch("src.resume_store.connection.get_resume_collection") as mock:
        yield mock


@pytest.fixture
def mock_milvus():
    """模拟 Milvus 连接"""
    with patch("src.vector_index.connection.get_milvus_connection") as mock:
        yield mock


@pytest.fixture
def mock_redis():
    """模拟 Redis 连接"""
    with patch("redis.Redis") as mock:
        yield mock


@pytest.fixture
def sample_resume():
    """示例简历数据"""
    return {
        "name": "张三",
        "phone": "13800138000",
        "email": "zhangsan@example.com",
        "education": [
            {
                "school": "北京大学",
                "degree": "本科",
                "major": "计算机科学与技术",
                "start_date": "2018-09",
                "end_date": "2022-06",
            }
        ],
        "experience": [
            {
                "company": "字节跳动",
                "position": "后端工程师",
                "start_date": "2022-07",
                "end_date": "2024-06",
                "description": "负责推荐系统后端开发",
            }
        ],
        "skills": ["Python", "Java", "Go", "MySQL", "Redis", "Kafka"],
    }
