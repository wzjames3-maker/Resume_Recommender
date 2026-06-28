"""
智能招聘 RAG 推荐系统 - 审计日志中间件

记录 HTTP 请求信息，用于审计和调试
"""

import time
import uuid
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.common.logger import get_logger

logger = get_logger("audit-log")

# 敏感路径列表（不记录请求体）
SENSITIVE_PATHS = [
    "/auth/login",
    "/auth/register",
    "/auth/change-password",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
]


class AuditLogMiddleware(BaseHTTPMiddleware):
    """审计日志中间件"""

    def __init__(self, app: ASGIApp, exclude_paths: Optional[list[str]] = None):
        """
        初始化审计日志中间件

        Args:
            app: ASGI 应用
            exclude_paths: 排除的路径列表（不记录日志）
        """
        super().__init__(app)
        self.exclude_paths = exclude_paths or []

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求并记录审计日志

        Args:
            request: 请求对象
            call_next: 下一个中间件或路由处理函数

        Returns:
            Response: 响应对象
        """
        # 检查是否排除该路径
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        # 生成请求 ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # 记录开始时间
        start_time = time.time()

        # 获取用户 ID（从认证信息中提取，如果没有则为匿名）
        user_id = self._extract_user_id(request)

        # 构建请求上下文
        request_context = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query_params": str(request.query_params) if request.query_params else None,
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("User-Agent"),
            "user_id": user_id,
        }

        # 检查是否为敏感路径
        is_sensitive = any(
            request.url.path.startswith(path) for path in SENSITIVE_PATHS
        )

        # 记录请求体（非敏感路径）
        if not is_sensitive and request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    request_context["request_body_size"] = len(body)
            except Exception:
                pass

        # 记录请求开始日志
        logger.info(
            "请求开始",
            extra={
                "event": "request_start",
                **request_context,
            },
        )

        try:
            # 调用下一个处理器
            response = await call_next(request)

            # 计算耗时
            duration = time.time() - start_time

            # 构建响应上下文
            response_context = {
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            }

            # 记录请求完成日志
            logger.info(
                "请求完成",
                extra={
                    "event": "request_end",
                    **request_context,
                    **response_context,
                },
            )

            # 添加请求 ID 到响应头
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            # 计算耗时
            duration = time.time() - start_time

            # 记录请求失败日志
            logger.error(
                "请求失败",
                extra={
                    "event": "request_error",
                    **request_context,
                    "duration_ms": round(duration * 1000, 2),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

            # 重新抛出异常
            raise

    def _extract_user_id(self, request: Request) -> Optional[str]:
        """
        从请求中提取用户 ID

        Args:
            request: 请求对象

        Returns:
            Optional[str]: 用户 ID，如果没有则返回 None
        """
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            try:
                from src.common.auth import decode_access_token
                token = auth_header.split(" ", 1)[1]
                payload = decode_access_token(token)
                return payload.get("sub")
            except Exception:
                pass

        return None


class RequestIDMiddleware(BaseHTTPMiddleware):
    """请求 ID 中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求，确保请求 ID 存在

        Args:
            request: 请求对象
            call_next: 下一个中间件或路由处理函数

        Returns:
            Response: 响应对象
        """
        # 获取或生成请求 ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # 将请求 ID 添加到请求状态中
        request.state.request_id = request_id

        # 调用下一个处理器
        response = await call_next(request)

        # 添加请求 ID 到响应头
        response.headers["X-Request-ID"] = request_id

        return response


def register_audit_log_middleware(app, exclude_paths: Optional[list[str]] = None) -> None:
    """
    注册审计日志中间件到 FastAPI app

    Args:
        app: FastAPI 应用
        exclude_paths: 排除的路径列表
    """
    # 先添加请求 ID 中间件
    app.add_middleware(RequestIDMiddleware)

    # 再添加审计日志中间件
    app.add_middleware(AuditLogMiddleware, exclude_paths=exclude_paths or [])
