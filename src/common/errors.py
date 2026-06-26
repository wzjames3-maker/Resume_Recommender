"""
智能招聘 RAG 推荐系统 - 统一错误码体系

对齐 PRD 附录B 错误码定义
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    """
    错误码枚举

    格式：模块前缀_数字
    模块前缀：
    - AUTH: 认证授权
    - RESUME: 简历相关
    - VEC: 向量检索
    - RECOMMEND: 推荐引擎
    - CONV: 对话记忆
    - SYS: 系统级
    """

    # ==================== 认证授权 (AUTH) ====================
    AUTH_001 = "AUTH_001"  # 未认证
    AUTH_002 = "AUTH_002"  # 权限不足
    AUTH_003 = "AUTH_003"  # Token 过期
    AUTH_004 = "AUTH_004"  # Token 无效
    AUTH_005 = "AUTH_005"  # 用户名或密码错误

    # ==================== 简历相关 (RESUME) ====================
    RESUME_001 = "RESUME_001"  # 候选人未找到
    RESUME_002 = "RESUME_002"  # 简历解析失败
    RESUME_003 = "RESUME_003"  # 简历格式不支持
    RESUME_004 = "RESUME_004"  # 简历文件过大
    RESUME_005 = "RESUME_005"  # 简历上传失败
    RESUME_006 = "RESUME_006"  # 简历已存在

    # ==================== 向量检索 (VEC) ====================
    VEC_001 = "VEC_001"  # 向量检索超时
    VEC_002 = "VEC_002"  # 向量索引创建失败
    VEC_003 = "VEC_003"  # Embedding 生成失败
    VEC_004 = "VEC_004"  # Milvus 连接失败

    # ==================== 推荐引擎 (RECOMMEND) ====================
    RECOMMEND_001 = "RECOMMEND_001"  # 推荐结果为空
    RECOMMEND_002 = "RECOMMEND_002"  # Rerank 失败
    RECOMMEND_003 = "RECOMMEND_003"  # 推荐理由生成失败

    # ==================== 对话记忆 (CONV) ====================
    CONV_001 = "CONV_001"  # 会话未找到
    CONV_002 = "CONV_002"  # 会话创建失败
    CONV_003 = "CONV_003"  # 槽位合并失败

    # ==================== 意图识别 (INTENT) ====================
    INTENT_001 = "INTENT_001"  # 意图识别失败
    INTENT_002 = "INTENT_002"  # 槽位提取失败

    # ==================== 系统级 (SYS) ====================
    SYS_001 = "SYS_001"  # 输入参数无效
    SYS_002 = "SYS_002"  # 内部错误
    SYS_003 = "SYS_003"  # 服务不可用
    SYS_004 = "SYS_004"  # 请求超时
    SYS_005 = "SYS_005"  # LLM 调用失败


# 错误码详细信息映射
ERROR_DETAILS: dict[ErrorCode, dict[str, Any]] = {
    # 认证授权
    ErrorCode.AUTH_001: {
        "message": "未认证，请先登录",
        "http_status": 401,
    },
    ErrorCode.AUTH_002: {
        "message": "权限不足，无法执行此操作",
        "http_status": 403,
    },
    ErrorCode.AUTH_003: {
        "message": "Token 已过期，请重新登录",
        "http_status": 401,
    },
    ErrorCode.AUTH_004: {
        "message": "Token 无效",
        "http_status": 401,
    },
    ErrorCode.AUTH_005: {
        "message": "用户名或密码错误",
        "http_status": 401,
    },
    # 简历相关
    ErrorCode.RESUME_001: {
        "message": "候选人未找到",
        "http_status": 404,
    },
    ErrorCode.RESUME_002: {
        "message": "简历解析失败",
        "http_status": 422,
    },
    ErrorCode.RESUME_003: {
        "message": "不支持的简历格式",
        "http_status": 422,
    },
    ErrorCode.RESUME_004: {
        "message": "简历文件过大，最大支持 10MB",
        "http_status": 413,
    },
    ErrorCode.RESUME_005: {
        "message": "简历上传失败",
        "http_status": 500,
    },
    ErrorCode.RESUME_006: {
        "message": "简历已存在",
        "http_status": 409,
    },
    # 向量检索
    ErrorCode.VEC_001: {
        "message": "向量检索超时，请稍后重试",
        "http_status": 504,
    },
    ErrorCode.VEC_002: {
        "message": "向量索引创建失败",
        "http_status": 500,
    },
    ErrorCode.VEC_003: {
        "message": "Embedding 生成失败",
        "http_status": 500,
    },
    ErrorCode.VEC_004: {
        "message": "Milvus 连接失败",
        "http_status": 503,
    },
    # 推荐引擎
    ErrorCode.RECOMMEND_001: {
        "message": "未找到符合条件的候选人",
        "http_status": 404,
    },
    ErrorCode.RECOMMEND_002: {
        "message": "推荐排序失败",
        "http_status": 500,
    },
    ErrorCode.RECOMMEND_003: {
        "message": "推荐理由生成失败",
        "http_status": 500,
    },
    # 对话记忆
    ErrorCode.CONV_001: {
        "message": "会话未找到",
        "http_status": 404,
    },
    ErrorCode.CONV_002: {
        "message": "会话创建失败",
        "http_status": 500,
    },
    ErrorCode.CONV_003: {
        "message": "槽位合并失败",
        "http_status": 500,
    },
    # 意图识别
    ErrorCode.INTENT_001: {
        "message": "意图识别失败，请重新描述您的需求",
        "http_status": 422,
    },
    ErrorCode.INTENT_002: {
        "message": "槽位提取失败",
        "http_status": 422,
    },
    # 系统级
    ErrorCode.SYS_001: {
        "message": "输入参数无效",
        "http_status": 400,
    },
    ErrorCode.SYS_002: {
        "message": "内部错误，请稍后重试",
        "http_status": 500,
    },
    ErrorCode.SYS_003: {
        "message": "服务暂不可用",
        "http_status": 503,
    },
    ErrorCode.SYS_004: {
        "message": "请求超时",
        "http_status": 504,
    },
    ErrorCode.SYS_005: {
        "message": "LLM 调用失败",
        "http_status": 502,
    },
}


class ErrorResponse(BaseModel):
    """统一错误响应格式"""

    code: str = Field(..., description="错误码")
    message: str = Field(..., description="错误描述")
    detail: Optional[Any] = Field(None, description="调试详情（仅 dev 环境返回）")
    request_id: Optional[str] = Field(None, description="请求追踪 ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="错误发生时间")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class AppException(HTTPException):
    """应用异常基类"""

    def __init__(
        self,
        error_code: ErrorCode,
        detail: Optional[Any] = None,
        headers: Optional[dict[str, str]] = None,
    ):
        self.error_code = error_code
        self.error_detail = ERROR_DETAILS.get(error_code, {})
        self.http_status = self.error_detail.get("http_status", 500)
        self.message = detail or self.error_detail.get("message", "未知错误")

        super().__init__(
            status_code=self.http_status,
            detail=self.message,
            headers=headers,
        )

    def to_response(self, request_id: Optional[str] = None, debug: bool = False) -> ErrorResponse:
        """转换为 ErrorResponse"""
        return ErrorResponse(
            code=self.error_code.value,
            message=self.message,
            detail=self.error_detail if debug else None,
            request_id=request_id,
        )


class AuthenticationError(AppException):
    """认证错误"""

    def __init__(self, error_code: ErrorCode = ErrorCode.AUTH_001, detail: Optional[Any] = None):
        super().__init__(error_code=error_code, detail=detail)


class AuthorizationError(AppException):
    """授权错误"""

    def __init__(self, error_code: ErrorCode = ErrorCode.AUTH_002, detail: Optional[Any] = None):
        super().__init__(error_code=error_code, detail=detail)


class ResourceNotFoundError(AppException):
    """资源未找到错误"""

    def __init__(self, error_code: ErrorCode = ErrorCode.RESUME_001, detail: Optional[Any] = None):
        super().__init__(error_code=error_code, detail=detail)


class ValidationError(AppException):
    """验证错误"""

    def __init__(self, error_code: ErrorCode = ErrorCode.SYS_001, detail: Optional[Any] = None):
        super().__init__(error_code=error_code, detail=detail)


class ExternalServiceError(AppException):
    """外部服务错误"""

    def __init__(self, error_code: ErrorCode = ErrorCode.SYS_005, detail: Optional[Any] = None):
        super().__init__(error_code=error_code, detail=detail)


class ResumeParseError(AppException):
    """简历解析错误"""

    def __init__(self, error_code: ErrorCode = ErrorCode.RESUME_002, detail: Optional[Any] = None):
        super().__init__(error_code=error_code, detail=detail)


class IntentRecognitionError(AppException):
    """意图识别错误"""

    def __init__(self, error_code: ErrorCode = ErrorCode.INTENT_001, detail: Optional[Any] = None):
        super().__init__(error_code=error_code, detail=detail)


class RetrievalTimeoutError(AppException):
    """检索超时错误"""

    def __init__(self, error_code: ErrorCode = ErrorCode.VEC_001, detail: Optional[Any] = None):
        super().__init__(error_code=error_code, detail=detail)


async def app_exception_handler(request: Request, exc: AppException):
    """AppException 全局异常处理器"""
    from fastapi.responses import JSONResponse

    request_id = request.headers.get("X-Request-ID")
    # 从配置中获取是否为 debug 模式
    debug = request.app.state.debug if hasattr(request.app.state, "debug") else False
    response = exc.to_response(request_id=request_id, debug=debug)
    return JSONResponse(
        status_code=exc.http_status,
        content=response.model_dump(mode="json"),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """RequestValidationError 全局异常处理器"""
    from fastapi.responses import JSONResponse

    request_id = request.headers.get("X-Request-ID")

    # 提取验证错误详情
    errors = []
    for error in exc.errors():
        errors.append({
            "loc": error.get("loc", []),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        })

    response = ErrorResponse(
        code=ErrorCode.SYS_001.value,
        message="输入参数无效",
        detail=errors,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=400,
        content=response.model_dump(mode="json"),
    )


async def generic_exception_handler(request: Request, exc: Exception):
    """通用异常处理器"""
    from fastapi.responses import JSONResponse

    request_id = request.headers.get("X-Request-ID")
    debug = request.app.state.debug if hasattr(request.app.state, "debug") else False

    response = ErrorResponse(
        code=ErrorCode.SYS_002.value,
        message="内部错误，请稍后重试",
        detail=str(exc) if debug else None,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=500,
        content=response.model_dump(mode="json"),
    )


def register_exception_handlers(app) -> None:
    """注册全局异常处理器到 FastAPI app"""
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
