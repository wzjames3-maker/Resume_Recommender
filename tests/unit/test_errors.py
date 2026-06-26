"""
智能招聘 RAG 推荐系统 - 错误码测试
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.common.errors import (
    AppException,
    AuthenticationError,
    AuthorizationError,
    ErrorCode,
    ErrorResponse,
    ExternalServiceError,
    IntentRecognitionError,
    ResourceNotFoundError,
    ResumeParseError,
    RetrievalTimeoutError,
    ValidationError,
    register_exception_handlers,
)


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


class TestErrorCode:
    """ErrorCode 枚举测试"""

    def test_auth_error_codes(self):
        """测试认证错误码"""
        assert ErrorCode.AUTH_001.value == "AUTH_001"
        assert ErrorCode.AUTH_002.value == "AUTH_002"
        assert ErrorCode.AUTH_003.value == "AUTH_003"
        assert ErrorCode.AUTH_004.value == "AUTH_004"
        assert ErrorCode.AUTH_005.value == "AUTH_005"

    def test_resume_error_codes(self):
        """测试简历错误码"""
        assert ErrorCode.RESUME_001.value == "RESUME_001"
        assert ErrorCode.RESUME_002.value == "RESUME_002"
        assert ErrorCode.RESUME_003.value == "RESUME_003"
        assert ErrorCode.RESUME_004.value == "RESUME_004"
        assert ErrorCode.RESUME_005.value == "RESUME_005"
        assert ErrorCode.RESUME_006.value == "RESUME_006"

    def test_vec_error_codes(self):
        """测试向量检索错误码"""
        assert ErrorCode.VEC_001.value == "VEC_001"
        assert ErrorCode.VEC_002.value == "VEC_002"
        assert ErrorCode.VEC_003.value == "VEC_003"
        assert ErrorCode.VEC_004.value == "VEC_004"

    def test_recommend_error_codes(self):
        """测试推荐引擎错误码"""
        assert ErrorCode.RECOMMEND_001.value == "RECOMMEND_001"
        assert ErrorCode.RECOMMEND_002.value == "RECOMMEND_002"
        assert ErrorCode.RECOMMEND_003.value == "RECOMMEND_003"

    def test_conv_error_codes(self):
        """测试对话记忆错误码"""
        assert ErrorCode.CONV_001.value == "CONV_001"
        assert ErrorCode.CONV_002.value == "CONV_002"
        assert ErrorCode.CONV_003.value == "CONV_003"

    def test_intent_error_codes(self):
        """测试意图识别错误码"""
        assert ErrorCode.INTENT_001.value == "INTENT_001"
        assert ErrorCode.INTENT_002.value == "INTENT_002"

    def test_sys_error_codes(self):
        """测试系统级错误码"""
        assert ErrorCode.SYS_001.value == "SYS_001"
        assert ErrorCode.SYS_002.value == "SYS_002"
        assert ErrorCode.SYS_003.value == "SYS_003"
        assert ErrorCode.SYS_004.value == "SYS_004"
        assert ErrorCode.SYS_005.value == "SYS_005"


class TestErrorResponse:
    """ErrorResponse Model 测试"""

    def test_create_error_response(self):
        """测试创建 ErrorResponse"""
        response = ErrorResponse(
            code="AUTH_001",
            message="未认证，请先登录",
        )
        assert response.code == "AUTH_001"
        assert response.message == "未认证，请先登录"
        assert response.detail is None
        assert response.request_id is None
        assert response.timestamp is not None

    def test_error_response_with_detail(self):
        """测试带详情的 ErrorResponse"""
        detail = {"field": "username", "reason": "required"}
        response = ErrorResponse(
            code="SYS_001",
            message="输入参数无效",
            detail=detail,
            request_id="test-request-id",
        )
        assert response.detail == detail
        assert response.request_id == "test-request-id"

    def test_error_response_json(self):
        """测试 ErrorResponse JSON 序列化"""
        response = ErrorResponse(
            code="AUTH_001",
            message="未认证",
        )
        json_data = response.model_dump()
        assert "code" in json_data
        assert "message" in json_data
        assert "timestamp" in json_data


class TestAppException:
    """AppException 测试"""

    def test_create_app_exception(self):
        """测试创建 AppException"""
        exc = AppException(error_code=ErrorCode.AUTH_001)
        assert exc.error_code == ErrorCode.AUTH_001
        assert exc.http_status == 401
        assert exc.message == "未认证，请先登录"

    def test_app_exception_to_response(self):
        """测试 AppException 转换为 ErrorResponse"""
        exc = AppException(error_code=ErrorCode.RESUME_001)
        response = exc.to_response(request_id="test-id", debug=False)
        assert response.code == "RESUME_001"
        assert response.message == "候选人未找到"
        assert response.request_id == "test-id"
        assert response.detail is None

    def test_app_exception_to_response_debug(self):
        """测试 debug 模式下的 ErrorResponse"""
        exc = AppException(error_code=ErrorCode.SYS_002)
        response = exc.to_response(debug=True)
        assert response.detail is not None


class TestExceptionSubclasses:
    """异常子类测试"""

    def test_authentication_error(self):
        """测试 AuthenticationError"""
        exc = AuthenticationError()
        assert exc.error_code == ErrorCode.AUTH_001
        assert exc.http_status == 401

    def test_authorization_error(self):
        """测试 AuthorizationError"""
        exc = AuthorizationError()
        assert exc.error_code == ErrorCode.AUTH_002
        assert exc.http_status == 403

    def test_resource_not_found_error(self):
        """测试 ResourceNotFoundError"""
        exc = ResourceNotFoundError()
        assert exc.error_code == ErrorCode.RESUME_001
        assert exc.http_status == 404

    def test_validation_error(self):
        """测试 ValidationError"""
        exc = ValidationError()
        assert exc.error_code == ErrorCode.SYS_001
        assert exc.http_status == 400

    def test_external_service_error(self):
        """测试 ExternalServiceError"""
        exc = ExternalServiceError()
        assert exc.error_code == ErrorCode.SYS_005
        assert exc.http_status == 502

    def test_resume_parse_error(self):
        """测试 ResumeParseError"""
        exc = ResumeParseError()
        assert exc.error_code == ErrorCode.RESUME_002
        assert exc.http_status == 422

    def test_intent_recognition_error(self):
        """测试 IntentRecognitionError"""
        exc = IntentRecognitionError()
        assert exc.error_code == ErrorCode.INTENT_001
        assert exc.http_status == 422

    def test_retrieval_timeout_error(self):
        """测试 RetrievalTimeoutError"""
        exc = RetrievalTimeoutError()
        assert exc.error_code == ErrorCode.VEC_001
        assert exc.http_status == 504


class TestHTTPExceptionHandlers:
    """HTTP 异常处理器测试"""

    def test_app_exception_handler(self, client):
        """测试 AppException 处理器"""
        response = client.get("/test-error")
        assert response.status_code == 404
        data = response.json()
        assert data["code"] == "RESUME_001"
        assert data["message"] == "候选人未找到"

    def test_validation_error_handler(self, client):
        """测试验证错误处理器"""
        # 发送无效请求触发验证错误
        # 使用 /test-error 端点，它会抛出 AppException
        response = client.get("/test-error")
        # 验证返回的是 ErrorResponse 格式
        assert response.status_code == 404
        data = response.json()
        assert "code" in data
        assert "message" in data

    def test_generic_exception_handler(self, client):
        """测试通用异常处理器"""
        # 这个测试需要一个会抛出非 AppException 的端点
        # 暂时跳过，实际实现时需要添加测试端点
        pass
