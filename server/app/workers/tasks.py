"""Celery 任务（对齐 08 §2.0 验收：Hello Agent 端到端）。worker 侧用同步 pymongo/redis。"""
import datetime

from app.infra.celery_app import celery_app
from app.infra.mongo import get_sync_db
from app.infra.redis import get_sync_redis
from app.schemas.events import SSEEvent, sse_pack

_UTC = datetime.timezone.utc


def _now() -> str:
    return datetime.datetime.now(_UTC).isoformat()


def _event_channel(task_id: str) -> str:
    return f"task:{task_id}"


def _append_event_sync(task_id: str, event_type: str, payload: dict) -> int:
    """同步版 append_event（worker 用）；seq 来自 Mongo，事件发布到 Redis 通道。"""
    db = get_sync_db()
    last = db["task_events"].find_one({"task_id": task_id}, sort=[("seq", -1)])
    seq = (last["seq"] + 1) if last else 1
    db["task_events"].insert_one(
        {
            "task_id": task_id,
            "seq": seq,
            "type": event_type,
            "payload": payload,
            "ts": _now(),
        }
    )
    get_sync_redis().publish(_event_channel(task_id), sse_pack(event_type, payload))
    return seq


def _set_status_sync(task_id: str, status: str, **extra) -> None:
    db = get_sync_db()
    update = {"status": status, "updated_at": _now(), **extra}
    if status == "EXECUTING":
        update.setdefault("started_at", _now())
    if status in {"COMPLETED", "FAILED", "CANCELLED"}:
        update["finished_at"] = _now()
    db["tasks"].update_one({"task_id": task_id}, {"$set": update})


@celery_app.task(bind=True, name="agents.hello")
def hello_agent_task(self, task_id: str, user_id: str) -> dict:
    """Phase 0 端到端验证任务：PENDING -> EXECUTING -> COMPLETED，全程发事件。"""
    _set_status_sync(task_id, "EXECUTING")
    _append_event_sync(task_id, SSEEvent.PLAN, {
        "plan": [{"step_id": "s1", "title": "Hello", "agent": "hello", "deps": []}],
    })
    _append_event_sync(task_id, SSEEvent.NODE_START, {"node": "hello", "step_id": "s1"})
    text = f"Hello, user {user_id}! 任务 {task_id} 已由 Celery worker 执行完成。"
    _append_event_sync(task_id, SSEEvent.DELTA, {"text": text})

    result = {"text": text}
    _set_status_sync(task_id, "COMPLETED", result=result, cost={"tokens": 0, "estimated_cost": 0.0})
    _append_event_sync(task_id, SSEEvent.COMPLETED, {
        "task_id": task_id,
        "cost": {"tokens": 0, "estimated_cost": 0.0},
    })
    return result


@celery_app.task(name="agents.memory_consolidate")
def memory_consolidate() -> None:
    """夜间记忆整理占位（FR-29 阶段二启用；Phase 0 仅确保 beat 调度不报错）。"""
    return None
