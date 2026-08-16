"""任务端点（对齐 docs/05 §13.4 契约）。"""
import asyncio

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.deps import get_current_user
from app.core.errors import AppError, ErrorCode
from app.core.task_states import TERMINAL
from app.infra.redis import get_async_redis
from app.schemas.events import sse_pack
from app.schemas.task import CancelOut, TaskCreate, TaskOut
from app.services import task_service
from app.workers.tasks import hello_agent_task, kb_import_task

router = APIRouter(prefix="/tasks", tags=["tasks"])

# 可通过 POST /tasks 直接提交的 agent 白名单（其余走各自业务端点）
_AGENT_WHITELIST = ("hello", "kb_import")

_SSE_SUBSCRIBE_TIMEOUT = 20.0


def _to_out(doc: dict) -> TaskOut:
    return TaskOut(
        task_id=doc["task_id"],
        status=doc["status"],
        agent=doc["agent"],
        intent=doc.get("intent"),
        plan=doc.get("plan") or [],
        current_step=doc.get("current_step"),
        result=doc.get("result"),
        error=doc.get("error"),
        cost=doc.get("cost"),
        created_at=doc.get("created_at"),
        started_at=doc.get("started_at"),
        finished_at=doc.get("finished_at"),
    )


@router.post("", response_model=TaskOut, status_code=202)
async def create_task(body: TaskCreate, user: dict = Depends(get_current_user)) -> TaskOut:
    if body.agent not in _AGENT_WHITELIST:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"不支持的 agent，可选: {', '.join(_AGENT_WHITELIST)}",
            status_code=422,
        )
    if body.agent == "kb_import" and not body.input.get("doc_id"):
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "kb_import 需要 input.doc_id", status_code=422
        )
    task_id = await task_service.create_task(user["_id"], body.agent, body.input, body.budget)
    if body.agent == "hello":
        hello_agent_task.delay(task_id, user["_id"])  # Celery 异步执行
    else:  # kb_import（直接提交时需在 input 中携带 space_id/file_key/domain）
        kb_import_task.delay(
            task_id,
            body.input["doc_id"],
            user["_id"],
            body.input.get("space_id", ""),
            body.input.get("domain", "general"),
            body.input.get("file_key", ""),
        )
    return _to_out(await task_service.get_task(task_id, user["_id"]))


@router.get("", response_model=dict)
async def list_tasks(
    user: dict = Depends(get_current_user),
    status: str | None = Query(default=None),
    agent: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return await task_service.list_tasks(user["_id"], status, agent, page, page_size)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, user: dict = Depends(get_current_user)) -> TaskOut:
    return _to_out(await task_service.get_task(task_id, user["_id"]))


@router.get("/{task_id}/events")
async def task_events(
    task_id: str,
    after_seq: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 事件流：先补发缓冲事件（seq>after_seq），未终态则订阅 Redis 通道。"""
    task = await task_service.get_task(task_id, user["_id"])

    async def _stream():
        events = await task_service.get_events_after(task_id, user["_id"], after_seq)
        for ev in events:
            yield sse_pack(ev["type"], ev["payload"])
        if task["status"] in TERMINAL:
            return
        r = get_async_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(f"task:{task_id}")
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + _SSE_SUBSCRIBE_TIMEOUT
            while loop.time() < deadline:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    yield msg["data"]
        finally:
            await pubsub.unsubscribe(f"task:{task_id}")
            await pubsub.close()

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/{task_id}/cancel", response_model=CancelOut)
async def cancel_task(task_id: str, user: dict = Depends(get_current_user)) -> CancelOut:
    task = await task_service.cancel_task(task_id, user["_id"])
    return CancelOut(task_id=task["task_id"], status=task["status"])
