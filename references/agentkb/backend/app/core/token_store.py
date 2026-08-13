import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)


class TokenStoreUnavailable(Exception):
    pass


def _key(jti: str) -> str:
    return f"auth:refresh:{jti}"


async def store_refresh_token(user_id: int, jti: str, ttl_seconds: int) -> None:
    try:
        await _redis.set(_key(jti), str(user_id), ex=ttl_seconds)
    except Exception as exc:
        logger.error("refresh token 写入 Redis 失败: %s", exc)
        raise


async def is_refresh_token_valid(jti: str) -> bool:
    try:
        return await _redis.exists(_key(jti)) == 1
    except Exception as exc:
        logger.error("refresh token 校验访问 Redis 失败: %s", exc)
        raise TokenStoreUnavailable from exc


async def revoke_refresh_token(jti: str) -> None:
    try:
        await _redis.delete(_key(jti))
    except Exception as exc:
        logger.error("refresh token 撤销访问 Redis 失败: %s", exc)
        raise
