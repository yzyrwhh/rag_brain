"""Redis 客户端：API 用 redis.asyncio，worker 用同步 redis。"""
import redis
import redis.asyncio as aioredis

from app.core.config import get_settings

_async: aioredis.Redis | None = None
_sync: redis.Redis | None = None


def get_async_redis() -> aioredis.Redis:
    global _async
    if _async is None:
        _async = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _async


def get_sync_redis() -> redis.Redis:
    global _sync
    if _sync is None:
        _sync = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _sync


async def ping() -> bool:
    await get_async_redis().ping()
    return True
