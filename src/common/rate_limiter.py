"""登录限流模块（Redis 滑动窗口 + 内存降级）"""
import time
from collections import defaultdict
from typing import Dict

from src.common.config import Environment, get_settings
from src.common.logger import get_logger

logger = get_logger("rate_limiter")


class RateLimiter:
    """滑动窗口限流器（生产用 Redis，开发降级到内存）"""

    def __init__(self):
        self._windows: Dict[str, Dict[int, int]] = defaultdict(dict)
        self._redis = None

    def _use_redis(self) -> bool:
        try:
            return get_settings().app.APP_ENV == Environment.PROD
        except Exception:
            return False

    def _get_redis(self):
        if self._redis is None and self._use_redis():
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                get_settings().redis.redis_url,
                decode_responses=True,
            )
        return self._redis

    async def is_allowed(self, key: str, limit: int = 10, window: int = 60) -> bool:
        redis = self._get_redis()
        if redis:
            return await self._redis_is_allowed(redis, key, limit, window)
        return self._memory_is_allowed(key, limit, window)

    async def _redis_is_allowed(self, redis, key: str, limit: int, window: int) -> bool:
        now = int(time.time() * 1000)
        window_start = now - window * 1000
        rkey = f"ratelimit:{key}"
        try:
            async with redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(rkey, 0, window_start)
                pipe.zcard(rkey)
                results = await pipe.execute()
            current = results[1]
            if current >= limit:
                return False
            await redis.zadd(rkey, {str(now): now})
            await redis.expire(rkey, window)
            return True
        except Exception as e:
            logger.warning(f"Redis rate limit failed, falling back to memory: {e}")
            return self._memory_is_allowed(key, limit, window)

    def _memory_is_allowed(self, key: str, limit: int, window: int) -> bool:
        now = int(time.time())
        bucket = self._windows[key]
        expired = [t for t in bucket if now - t >= window]
        for t in expired:
            del bucket[t]
        count = sum(bucket.values())
        if count >= limit:
            return False
        bucket[now] = bucket.get(now, 0) + 1
        return True


# 全局限流器实例
_login_limiter = RateLimiter()
