"""Celery 应用（broker/result 走 Redis，对齐 02 §3 与 08 §2.0）。"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "shopkeer",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_max_tasks_per_child=200,
    broker_connection_retry_on_startup=True,
    # 夜间记忆整理（FR-29，阶段二按 03 §10.1 启用；Phase 0 仅占位）
    beat_schedule={
        "memory-consolidate": {
            "task": "agents.memory_consolidate",
            "schedule": crontab(minute=0, hour=3),
        },
    },
)
