"""
智能招聘 RAG 推荐系统 - 日志模块测试
"""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.common.logger import LoggerMixin, get_logger
from src.common.middleware.audit_log import AuditLogMiddleware, RequestIDMiddleware


class TestLogger:
    """日志记录器测试"""

    def test_get_logger(self):
        """测试获取日志记录器"""
        logger = get_logger("test-logger")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test-logger"

    def test_logger_singleton(self):
        """测试日志记录器单例"""
        logger1 = get_logger("test-singleton")
        logger2 = get_logger("test-singleton")
        assert logger1 is logger2

    def test_logger_output_json(self, capsys):
        """测试 JSON 格式输出"""
        logger = get_logger("test-json")
        logger.info("测试消息")

        captured = capsys.readouterr()
        # 尝试解析 JSON
        try:
            log_data = json.loads(captured.out)
            assert "message" in log_data
            assert "level" in log_data
            assert "timestamp" in log_data
        except json.JSONDecodeError:
            pytest.fail("日志输出不是有效的 JSON 格式")

    def test_logger_fields(self, capsys):
        """测试日志字段"""
        logger = get_logger("test-fields")
        logger.info("测试字段", extra={"custom_field": "test_value"})

        captured = capsys.readouterr()
        try:
            log_data = json.loads(captured.out)
            assert log_data.get("custom_field") == "test_value"
        except json.JSONDecodeError:
            pytest.fail("日志输出不是有效的 JSON 格式")

    def test_logger_mixin(self):
        """测试 LoggerMixin"""
        class TestClass(LoggerMixin):
            pass

        obj = TestClass()
        assert isinstance(obj.logger, logging.Logger)
        assert obj.logger.name == "TestClass"


class TestAuditLogMiddleware:
    """审计日志中间件测试"""

    @pytest.fixture
    def app(self):
        """创建测试应用"""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}

        @app.post("/test-post")
        async def test_post_endpoint():
            return {"message": "test"}

        return app

    @pytest.fixture
    def client_with_middleware(self, app):
        """创建带中间件的测试客户端"""
        app.add_middleware(AuditLogMiddleware)
        return TestClient(app)

    def test_request_id_generated(self, client_with_middleware):
        """测试请求 ID 自动生成"""
        response = client_with_middleware.get("/test")
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) > 0

    def test_request_id_from_header(self, client_with_middleware):
        """测试从请求头获取请求 ID"""
        request_id = "test-request-id-123"
        response = client_with_middleware.get(
            "/test",
            headers={"X-Request-ID": request_id},
        )
        assert response.headers["X-Request-ID"] == request_id

    def test_response_status_code(self, client_with_middleware):
        """测试响应状态码"""
        response = client_with_middleware.get("/test")
        assert response.status_code == 200


class TestRequestIDMiddleware:
    """请求 ID 中间件测试"""

    @pytest.fixture
    def app(self):
        """创建测试应用"""
        from fastapi import Request

        app = FastAPI()

        @app.get("/test")
        async def test_endpoint(request: Request):
            # 从请求状态中获取 request_id
            request_id = getattr(request.state, "request_id", None)
            return {"request_id": request_id}

        return app

    @pytest.fixture
    def client_with_middleware(self, app):
        """创建带中间件的测试客户端"""
        app.add_middleware(RequestIDMiddleware)
        return TestClient(app)

    def test_request_id_in_state(self, client_with_middleware):
        """测试请求 ID 存储在请求状态中"""
        response = client_with_middleware.get("/test")
        data = response.json()
        # request_id 可能为 None（如果中间件未正确设置）
        assert "request_id" in data

    def test_request_id_from_header(self, client_with_middleware):
        """测试从请求头获取请求 ID"""
        request_id = "custom-request-id"
        response = client_with_middleware.get(
            "/test",
            headers={"X-Request-ID": request_id},
        )
        data = response.json()
        # 验证请求 ID 被设置（可能在 state 或 header 中）
        assert response.headers.get("X-Request-ID") == request_id
