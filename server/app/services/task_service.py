"""任务服务（异步，API 侧）：创建/查询/状态迁移/事件（对齐 03 §3.4/3.5 与 05 §4）。"""
import datetime
import uuid

from app.core.errors import AppError, ErrorCode
from app.core.task_states import TERMINAL, validate_transition
from app.infra.mongo import get_async_db
from app.infra.redis import get_async_redis
from app.schemas.events import SSEEvent, sse_pack

_UTC = datetime.timezone.utc


def _now() -> str:
    return datetime.datetime.now(_UTC).isoformat()


def _event_channel(task_id: str) -> str:
    return f"task:{task_id}"


async def create_task(user_id: str, agent: str, input_: dict, budget: dict | None) -> str:
    db = get_async_db()
    task_id = str(uuid.uuid4())
    doc = {
        "task_id": task_id,
        "user_id": user_id,
        "agent": agent,
        "intent": None,
        "status": "PENDING",
        "plan": [],
        "current_step": None,
        "input": input_,
        "result": None,
        "error": None,
        "cost": None,
        "retry_count": 0,
        "budget": budget or {},
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
    }
    await db["tasks"].insert_one(doc)
    await append_event(task_id, user_id, SSEEvent.READY, {"task_id": task_id, "session_id": None})
    return task_id


async def get_task(task_id: str, user_id: str) -> dict:
    db = get_async_db()
    doc = await db["tasks"].find_one({"task_id": task_id, "user_id": user_id})
    if doc is None:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在", status_code=404)
    return doc


async def list_tasks(
    user_id: str, status: str | None = None, agent: str | None = None,
    page: int = 1, page_size: int = 20,
) -> dict:
    db = get_async_db()
    query: dict = {"user_id": user_id}
    if status:
        query["status"] = status
    if agent:
        query["agent"] = agent
    cursor = (
        db["tasks"].find(query).sort("created_at", -1)
        .skip((page - 1) * page_size).limit(page_size)
    )
    items = [doc async for doc in cursor]
    total = await db["tasks"].count_documents(query)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def update_status(task_id: str, user_id: str, new_status: str, error: dict | None = None) -> dict:
    db = get_async_db()
    doc = await db["tasks"].find_one({"task_id": task_id, "user_id": user_id})
    if doc is None:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在", status_code=404)
    validate_transition(doc["status"], new_status)

    update: dict = {"status": new_status, "updated_at": _now()}
    if new_status == "EXECUTING" and not doc.get("started_at"):
        update["started_at"] = _now()
    if new_status in TERMINAL:
        update["finished_at"] = _now()
    if error is not None:
        update["error"] = error
    await db["tasks"].update_one({"task_id": task_id}, {"$set": update})
    return await get_task(task_id, user_id)


async def append_event(task_id: str, user_id: str, event_type: str, payload: dict) -> int:
    db = get_async_db()
    last = await db["task_events"].find_one(
        {"task_id": task_id}, sort=[("seq", -1)]
    )
    seq = (last["seq"] + 1) if last else 1
    await db["task_events"].insert_one(
        {
            "task_id": task_id,
            "user_id": user_id,
            "seq": seq,
            "type": event_type,
            "payload": payload,
            "ts": _now(),
        }
    )
    r = get_async_redis()
    await r.publish(_event_channel(task_id), sse_pack(event_type, payload))
    return seq


async def get_events_after(task_id: str, user_id: str, after_seq: int = 0) -> list[dict]:
    db = get_async_db()
    cursor = (
        db["task_events"].find(
            {"task_id": task_id, "user_id": user_id, "seq": {"$gt": after_seq}}
        ).sort("seq", 1)
    )
    return [doc async for doc in cursor]


async def cancel_task(task_id: str, user_id: str) -> dict:
    task = await update_status(task_id, user_id, "CANCELLED")
    await append_event(task_id, user_id, SSEEvent.CANCELLED, {"task_id": task_id})
    return task
