"""MinIO 客户端（同步，健康检查经线程池）。"""
import asyncio

from minio import Minio

from app.core.config import get_settings

_client: Minio | None = None


def get_minio() -> Minio:
    global _client
    if _client is None:
        s = get_settings()
        _client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
    return _client


def ensure_bucket() -> None:
    client = get_minio()
    bucket = get_settings().minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


async def ping() -> bool:
    await asyncio.to_thread(lambda: get_minio().bucket_exists(get_settings().minio_bucket))
    return True
