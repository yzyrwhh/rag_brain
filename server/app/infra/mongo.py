"""MongoDB 客户端：API 用 motor（异步），worker 用 pymongo（同步）。"""
import asyncio

import pymongo
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings

_async_client: AsyncIOMotorClient | None = None
_sync_client: pymongo.MongoClient | None = None


def get_async_client() -> AsyncIOMotorClient:
    global _async_client
    if _async_client is None:
        _async_client = AsyncIOMotorClient(
            get_settings().mongo_url, serverSelectionTimeoutMS=2000
        )
    return _async_client


def get_async_db():
    return get_async_client()[get_settings().mongo_db]


def get_sync_client() -> pymongo.MongoClient:
    global _sync_client
    if _sync_client is None:
        _sync_client = pymongo.MongoClient(
            get_settings().mongo_url, serverSelectionTimeoutMS=2000
        )
    return _sync_client


def get_sync_db():
    return get_sync_client()[get_settings().mongo_db]


async def ping() -> bool:
    await asyncio.to_thread(lambda: get_sync_client().admin.command("ping"))
    return True
