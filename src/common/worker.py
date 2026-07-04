"""
智能招聘 RAG 推荐系统 - ARQ Worker 配置
"""

from arq import cron
from arq.connections import RedisSettings
from src.common.config import get_settings
from src.common.logger import get_logger

_settings = get_settings()
_logger = get_logger("worker")


async def startup(ctx):
    """Worker 启动时执行"""
    ctx["logger"] = "arq-worker"
    print("ARQ Worker started")


async def shutdown(ctx):
    """Worker 关闭时执行"""
    print("ARQ Worker shutdown")


async def process_resume(ctx, resume_id: str):
    """处理简历解析任务（桩函数，尚未实现真实逻辑）"""
    _logger.warning("process_resume 是桩函数，尚未实现真实逻辑")
    print(f"Processing resume: {resume_id}")
    return {"status": "stub", "resume_id": resume_id}


class WorkerSettings:
    """ARQ Worker 配置"""

    functions = [process_resume]

    on_startup = startup
    on_shutdown = shutdown

    redis_settings = RedisSettings(
        host=_settings.redis.REDIS_HOST,
        port=_settings.redis.REDIS_PORT,
        database=_settings.redis.REDIS_DB,
        password=_settings.redis.REDIS_PASSWORD,
    )

    # 任务超时时间（秒）
    job_timeout = 300
    # 任务重试次数
    max_tries = 3
    # 任务结果保留时间（秒）
    result_expiration = 3600
