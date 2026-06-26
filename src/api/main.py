"""
智能招聘 RAG 推荐系统 - FastAPI 主应用
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.common.config import get_settings
from src.common.errors import register_exception_handlers
from src.common.middleware.audit_log import register_audit_log_middleware
from src.api.v1 import chat, auth, upload, conversations

settings = get_settings()

app = FastAPI(
    title="智能招聘 RAG 推荐系统",
    description="基于 RAG 的企业智能招聘助手 API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 配置 — 从环境变量读取，禁止 * + credentials 组合
origins = [o.strip() for o in settings.app.CORS_ORIGINS.split(",") if o.strip()] or ["http://localhost:8501"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 注册全局异常处理器
register_exception_handlers(app)

# 注册审计日志中间件
register_audit_log_middleware(app)

# 注册 API 路由
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(conversations.router)

# debug 模式从配置读取，生产默认 False
app.state.debug = settings.app.DEBUG


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "service": "resume-rag", "version": "0.1.0"}


@app.get("/")
async def root():
    """根路径"""
    return {"message": "智能招聘 RAG 推荐系统 API", "docs": "/docs", "health": "/health"}


@app.get("/test-error")
async def test_error():
    """测试错误处理端点"""
    from src.common.errors import AppException, ErrorCode
    raise AppException(error_code=ErrorCode.RESUME_001)
