"""Milvus 客户端（pymilvus 3.x 使用 MilvusClient；健康检查经线程池）。"""
import asyncio

from pymilvus import MilvusClient

from app.core.config import get_settings

_client: MilvusClient | None = None


def get_client() -> MilvusClient:
    global _client
    if _client is None:
        s = get_settings()
        uri = s.milvus_url if s.milvus_url.startswith("http") else f"http://{s.milvus_url}"
        _client = MilvusClient(uri=uri)
    return _client


def ping_sync() -> bool:
    get_client().get_server_version()
    return True


async def ping() -> bool:
    await asyncio.to_thread(ping_sync)
    return True
