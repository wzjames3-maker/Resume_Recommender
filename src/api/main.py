"""
智能招聘 RAG 推荐系统 - FastAPI 主应用
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.common.config import Environment, get_settings
from src.common.logger import get_logger
from src.common.errors import register_exception_handlers
from src.common.middleware.audit_log import register_audit_log_middleware
from src.api.v1 import chat, auth, upload, conversations

settings = get_settings()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"应用启动: env={settings.app.APP_ENV}")

    try:
        from src.resume_store.connection import mongodb_connection
        mongodb_connection.connect()
        logger.info("MongoDB 连接已建立")
    except Exception as e:
        logger.warning(f"MongoDB 连接失败（非致命）: {e}")

    yield

    logger.info("应用关闭，清理资源...")
    try:
        from src.resume_store.connection import mongodb_connection
        mongodb_connection.disconnect()
    except Exception:
        pass
    try:
        from src.intent_router.classifier import intent_classifier
        intent_classifier._client.close()
    except Exception:
        pass
    try:
        from src.recommendation_engine.reranker import reranker
        reranker._client.close()
    except Exception:
        pass
    try:
        from src.vector_index.embedding_generator import embedding_generator
        embedding_generator._client.close()
    except Exception:
        pass

app = FastAPI(
    title="智能招聘 RAG 推荐系统",
    description="基于 RAG 的企业智能招聘助手 API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS 配置 — 解析环境变量，兼容带方括号的 JSON 数组格式
_origins_raw = settings.app.CORS_ORIGINS
if _origins_raw:
    import json
    _origins_raw = _origins_raw.strip()
    if _origins_raw.startswith("["):
        try:
            origins = json.loads(_origins_raw)
        except json.JSONDecodeError:
            origins = [o.strip() for o in _origins_raw.strip("[]").split(",") if o.strip()]
    else:
        origins = [o.strip() for o in _origins_raw.split(",") if o.strip()]
else:
    origins = ["http://localhost:8501"]
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
    status = {"status": "healthy", "service": "resume-rag", "version": "0.1.0"}

    try:
        from src.resume_store.connection import mongodb_connection
        mongo_ok = mongodb_connection.health_check()
        status["mongodb"] = "ok" if mongo_ok else "unavailable"
    except Exception:
        status["mongodb"] = "unavailable"

    try:
        from src.common.config import get_settings
        import redis
        r = redis.from_url(get_settings().redis.redis_url, socket_connect_timeout=2)
        r.ping()
        r.close()
        status["redis"] = "ok"
    except Exception:
        status["redis"] = "unavailable"

    try:
        from pymilvus import MilvusClient
        client = MilvusClient(uri=get_settings().milvus.MILVUS_URI, timeout=3)
        status["milvus"] = "ok" if client.get_server_version() else "unavailable"
    except Exception:
        status["milvus"] = "unavailable"

    return status


@app.get("/")
async def root():
    """根路径"""
    return {"message": "智能招聘 RAG 推荐系统 API", "docs": "/docs", "health": "/health"}


@app.get("/test-error")
async def test_error():
    """测试错误处理端点（仅非生产环境可用）"""
    if settings.app.APP_ENV == Environment.PROD:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    from src.common.errors import AppException, ErrorCode
    raise AppException(error_code=ErrorCode.RESUME_001)
