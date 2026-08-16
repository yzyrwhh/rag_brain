"""Celery 任务（对齐 08 §2.0 验收：Hello Agent 端到端 + Phase 1 kb_import）。worker 侧用同步 pymongo/redis。

同步事件/状态助手（_append_event_sync / _set_status_sync / _now）已移入
app.services.kb_import_service，本模块直接引用，避免重复实现。
"""
import logging

from app.core.errors import ErrorCode
from app.core.task_states import validate_transition
from app.infra.celery_app import celery_app
from app.infra.mongo import get_sync_db
from app.schemas.events import SSEEvent
from app.services.kb_import_service import (
    _append_event_sync,
    _now,
    _set_status_sync,
    run_import_pipeline_sync,
)


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


@celery_app.task(bind=True, name="agents.kb_import")
def kb_import_task(
    self, task_id: str, doc_id: str, user_id: str, space_id: str, domain: str, file_key: str
) -> dict:
    """知识库文档导入任务：内部执行 kb_import_service.run_import_pipeline_sync。

    异常兜底：置任务 FAILED（写 tasks.error + 文档 failed + 发 task.failed 事件）后重抛。
    """
    try:
        return run_import_pipeline_sync(task_id, doc_id, user_id, space_id, domain, file_key)
    except Exception as exc:  # noqa: BLE001 - worker 必须兜底一切异常
        _mark_failed(task_id, doc_id, exc)
        raise


def _mark_failed(task_id: str, doc_id: str, exc: Exception) -> None:
    """失败兜底：文档 failed + 任务 FAILED（含 error 字段）+ task.failed 事件。"""
    try:
        db = get_sync_db()
        db["knowledge_documents"].update_one(
            {"doc_id": doc_id}, {"$set": {"status": "failed", "updated_at": _now()}}
        )
        task_doc = db["tasks"].find_one({"task_id": task_id})
        if task_doc is not None and task_doc["status"] != "FAILED":
            validate_transition(task_doc["status"], "FAILED")
        code = getattr(exc, "code", ErrorCode.INTERNAL)
        if isinstance(code, ErrorCode):
            code = code.value
        error = {"code": code, "message": str(exc) or exc.__class__.__name__}
        _set_status_sync(task_id, "FAILED", error=error)
        _append_event_sync(task_id, SSEEvent.FAILED, {"task_id": task_id, "error": error})
    except Exception:  # noqa: BLE001 - 兜底本身失败不再抛出，避免掩盖原始异常
        logging.getLogger(__name__).exception("标记任务失败时出错 task_id=%s", task_id)


@celery_app.task(name="agents.memory_consolidate")
def memory_consolidate() -> None:
    """夜间记忆整理占位（FR-29 阶段二启用；Phase 0 仅确保 beat 调度不报错）。"""
    return None
