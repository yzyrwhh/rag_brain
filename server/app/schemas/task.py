"""任务相关 DTO（对齐 docs/05 §13.4 契约与 03 §3.4 tasks 集合）。"""
from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    agent: str = "hello"                  # Phase 0 仅 "hello"；后续 supervisor/knowledge/...
    input: dict = Field(default_factory=dict)
    budget: dict | None = None            # {max_tokens, max_steps, timeout}


class TaskOut(BaseModel):
    task_id: str
    status: str
    agent: str
    intent: str | None = None
    plan: list = Field(default_factory=list)
    current_step: str | None = None
    result: dict | None = None
    error: dict | None = None
    cost: dict | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class CancelOut(BaseModel):
    task_id: str
    status: str
