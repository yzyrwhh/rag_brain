"""全局配置（pydantic-settings，对齐 docs/02 §11.1 环境变量清单）。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 基础
    app_env: str = "dev"
    app_debug: bool = True

    # 安全（05 §2）
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl: int = 900        # 15min
    jwt_refresh_ttl: int = 604800    # 7d

    # 存储（03）
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "shopkeer"

    milvus_url: str = "localhost:19530"
    milvus_chunks_collection: str = "kb_chunks_v3"
    milvus_memory_collection: str = "memory_vectors"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change-me"
    # Route A：图谱验证后才启用（03 §8 / 08 §1.6）；Phase 0-3 默认关闭
    neo4j_enabled: bool = False

    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "shopkeer"
    minio_secure: bool = False

    # 队列（02 §3）
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # 任务预算（🧪 08 §8.1）
    task_budget_max_tokens: int = 50000
    task_budget_max_steps: int = 30
    task_budget_timeout: int = 900

    # 记忆召回（🧪 08 §8.1）
    recall_max_results: int = 5
    recall_score_threshold: float = 0.3
    recall_max_total_chars: int = 2000
    recall_timeout_ms: int = 5000

    # 追踪（07 §6）
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "zhanggui-biz"


@lru_cache
def get_settings() -> Settings:
    return Settings()
