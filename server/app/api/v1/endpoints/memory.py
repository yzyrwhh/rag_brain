"""记忆端点（对齐 05 §7 契约：CRUD + 检索 + 任务沉淀）。"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.deps import get_current_user
from app.services import memory_service

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryCreate(BaseModel):
    kind: str = Field(default="fact")  # fact/preference/idea/insight/progress/dev_case/...
    content: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list)
    importance: int = Field(default=3, ge=1, le=5)
    domain: str = Field(default="general")  # 领域隔离（general/dev/law/audit…）


class SaveFromTask(BaseModel):
    task_id: str
    kind: str = "dev_case"
    tags: list[str] = Field(default_factory=list)


@router.get("")
async def list_memories(
    user: dict = Depends(get_current_user),
    kind: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return await memory_service.memory_list(user["_id"], kind, page, page_size)


@router.get("/search")
async def search_memories(
    user: dict = Depends(get_current_user),
    q: str = Query(min_length=1),
    kind: str | None = Query(default=None),
) -> dict:
    items = await memory_service.memory_search(user["_id"], q, kind, limit=5)
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
async def create_memory(
    body: MemoryCreate, user: dict = Depends(get_current_user)
) -> dict:
    memory_id = await memory_service.memory_write(
        user["_id"], body.kind, body.content, body.tags, body.importance,
        source="user", domain=body.domain,
    )
    return {"memory_id": memory_id}


@router.post("/save-from-task", status_code=201)
async def save_from_task(
    body: SaveFromTask, user: dict = Depends(get_current_user)
) -> dict:
    memory_id = await memory_service.save_from_task(
        user["_id"], body.task_id, body.kind, body.tags
    )
    return {"memory_id": memory_id}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, user: dict = Depends(get_current_user)) -> dict:
    await memory_service.memory_delete(user["_id"], memory_id)
    return {"status": "ok"}
