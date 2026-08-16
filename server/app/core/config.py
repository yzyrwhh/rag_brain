"""全局配置（pydantic-settings，对齐 docs/02 §11.1 环境变量清单）。

.env 加载不依赖进程 CWD：固定从 server/ 目录读取，避免"从错误目录启动
导致配置缺失、BGE 模型静默回退远程下载"这类问题。
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# server/ 目录（本文件位于 app/core/ 下，向上两级）
_SERVER_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _SERVER_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

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
    # 向量维度：BGE-M3=1024（Phase 1 本地嵌入）；切 text-embedding-v4 时改 1536 并重建集合
    embedding_dim: int = 1024
    embedding_batch_size: int = 5

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

    # 文档导入（Phase 1，对齐 03 §3.8；阈值对齐旧 knowledge/processor/import_process/config.py）
    max_content_length: int = 2000   # 切片最大长度
    min_content_length: int = 500    # 短内容合并阈值
    # BGE-M3 嵌入模型（env: BGE_M3_PATH / BGE_DEVICE，旧 .env 为 D:\software\bgem3 / cpu）
    bge_m3_path: str = "BAAI/bge-m3"
    bge_device: str = "cpu"
    # MinerU 模型缓存（env: HF_ENDPOINT / MINERU_HF_HOME / MINERU_MODELSCOPE_CACHE，旧值为 D:\software\mineru）
    hf_endpoint: str = "https://hf-mirror.com"
    mineru_hf_home: str = r"D:\software\mineru"
    mineru_modelscope_cache: str = r"D:\software\mineru"

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

    # LLM / VLM（DashScope 兼容，复用旧 knowledge/.env 命名；07 模型矩阵）
    openai_api_key: str = ""              # env OPENAI_API_KEY
    openai_api_base: str = ""             # env OPENAI_API_BASE
    vl_model: str = "qwen3-vl-flash"      # env VL_MODEL（图片摘要，VLM）
    entity_model: str = "qwen-flash"      # env ITEM_MODEL（实体/主题抽取）
    qa_model: str = "qwen-flash"          # env QA_MODEL（知识问答生成，可切 qwen-plus）
    vlm_enabled: bool = True              # env VLM_ENABLED（图片摘要开关）
    vl_requests_per_minute: int = 12      # env VL_RPM（对齐旧配置速率限制）

    # 检索增强（对齐旧 query_process/config.py；08 §8.1 🧪 待评测校准）
    hyde_enabled: bool = True             # env HYDE_ENABLED（HyDE 假设文档检索）
    hyde_model: str = "qwen-flash"        # env HYDE_MODEL
    hyde_search_limit: int = 5            # env HYDE_SEARCH_LIMIT（HyDE 检索 topN）
    rerank_enabled: bool = True           # env RERANK_ENABLED（bge-reranker 精排）
    reranker_model: str = ""              # env BGE_RERANKER_LARGE（默认 D:\software\BAAI_bge-reranker_large）
    reranker_device: str = "cpu"          # env BGE_RERANKER_DEVICE
    rerank_max_topk: int = 10             # env RERANK_MAX_TOPK（重排输入上限）
    rerank_min_topk: int = 3              # env RERANK_MIN_TOPK（重排最少返回）


@lru_cache
def get_settings() -> Settings:
    return Settings()
