# knowledge/utils/minio_utils.py

import os
import threading
from minio import Minio

# MinIO 配置（支持环境变量覆盖）
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "knowledge")

_minio_client = None
_minio_lock = threading.RLock()


def get_minio_client():
    """获取 MinIO 客户端单例（惰性初始化，避免模块导入时阻塞）。"""
    global _minio_client
    if _minio_client is not None:
        return _minio_client
    with _minio_lock:
        if _minio_client is not None:
            return _minio_client
        try:
            client = Minio(
                MINIO_ENDPOINT,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                secure=False,  # 本地开发不使用 HTTPS
            )
            # 确保 Bucket 存在
            if not client.bucket_exists(MINIO_BUCKET_NAME):
                client.make_bucket(MINIO_BUCKET_NAME)
            _minio_client = client
        except Exception as e:
            print(f"MinIO initialization failed: {e}")
            _minio_client = None
    return _minio_client