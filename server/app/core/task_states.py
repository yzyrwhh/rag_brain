"""任务状态机（对齐 docs/02 §3.2 状态图与 docs/05 §6.1）。"""
from app.core.errors import AppError, ErrorCode

PENDING = "PENDING"
PLANNING = "PLANNING"
EXECUTING = "EXECUTING"
AWAITING_INPUT = "AWAITING_INPUT"
REVIEWING = "REVIEWING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

ALL_STATUSES = {
    PENDING, PLANNING, EXECUTING, AWAITING_INPUT,
    REVIEWING, COMPLETED, FAILED, CANCELLED,
}
TERMINAL = {COMPLETED, FAILED, CANCELLED}

# 允许的迁移：old -> set(new)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    PENDING: {PLANNING, EXECUTING, FAILED, CANCELLED},
    PLANNING: {EXECUTING, AWAITING_INPUT, FAILED, CANCELLED},
    EXECUTING: {REVIEWING, COMPLETED, AWAITING_INPUT, FAILED, CANCELLED},
    AWAITING_INPUT: {EXECUTING, FAILED, CANCELLED},
    REVIEWING: {COMPLETED, EXECUTING, FAILED, CANCELLED},
    COMPLETED: set(),
    FAILED: {EXECUTING},  # 重试
    CANCELLED: set(),
}


def validate_transition(old: str, new: str) -> None:
    if old not in ALL_STATUSES or new not in ALL_STATUSES:
        raise AppError(ErrorCode.TASK_BUSY, f"非法任务状态: {old} -> {new}", status_code=409)
    if new not in ALLOWED_TRANSITIONS.get(old, set()):
        raise AppError(
            ErrorCode.TASK_BUSY,
            f"任务状态不允许该操作: {old} -> {new}",
            status_code=409,
        )
