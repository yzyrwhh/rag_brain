"""知识库端点（Phase 1：空间 + 文档导入 + 检索，对齐 03 §3.6/§3.8/§4.1 与 05 §5）。"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.core.deps import get_current_user
from app.core.errors import AppError, ErrorCode
from app.infra.mongo import get_async_db
from app.services import kb_import_service, kb_retrieve_service, qa_service
from app.workers.tasks import kb_import_task

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class SpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    type: str = "personal"  # personal | shared
    domain_hint: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    space_ids: list[str] = Field(default_factory=list)  # 空 = 全部可访问空间
    domain: str | None = None
    top_k: int = Field(default=10, ge=1, le=20)
    mode: str = "chunk"  # chunk | full（阶段一仅 chunk）
    filters: dict | None = None  # {"tags": ["..."], "entities": ["..."]}（05 §5.3 filters）


async def _check_space_access(space_id: str, user_id: str) -> None:
    """校验空间存在且用户是 owner 或 space_members 成员。"""
    db = get_async_db()
    space = await db["knowledge_spaces"].find_one({"space_id": space_id})
    if space is None:
        raise AppError(ErrorCode.NOT_FOUND, "知识空间不存在", status_code=404)
    if space.get("owner_id") == user_id:
        return
    member = await db["space_members"].find_one({"space_id": space_id, "user_id": user_id})
    if member is None:
        raise AppError(ErrorCode.AUTH_FORBIDDEN, "无权访问该知识空间", status_code=403)


def _strip_id(doc: dict) -> dict:
    """移除 Mongo 内部 _id（ObjectId 不可 JSON 序列化）。"""
    doc.pop("_id", None)
    return doc


@router.get("/spaces")
async def list_spaces(user: dict = Depends(get_current_user)) -> dict:
    """我的空间列表（owner + 我加入的共享空间）。"""
    db = get_async_db()
    owned = db["knowledge_spaces"].find({"owner_id": user["_id"]}).sort("created_at", -1)
    owned_list = [_strip_id(doc) async for doc in owned]
    member_cursor = db["space_members"].find({"user_id": user["_id"]})
    member_space_ids = [m["space_id"] async for m in member_cursor]
    shared = []
    if member_space_ids:
        shared_cursor = db["knowledge_spaces"].find({"space_id": {"$in": member_space_ids}})
        shared = [_strip_id(doc) async for doc in shared_cursor]
    return {"items": owned_list + shared, "total": len(owned_list) + len(shared)}


@router.post("/spaces", status_code=201)
async def create_space(body: SpaceCreate, user: dict = Depends(get_current_user)) -> dict:
    """创建知识空间（owner=当前用户）。"""
    db = get_async_db()
    now = datetime.now(timezone.utc).isoformat()
    space = {
        "space_id": str(uuid.uuid4()),
        "owner_id": user["_id"],
        "name": body.name,
        "description": body.description,
        "type": body.type,
        "visibility": "private",
        "domain_hint": body.domain_hint,
        "settings": {},
        "created_at": now,
        "updated_at": now,
    }
    await db["knowledge_spaces"].insert_one(space)
    return _strip_id(space)


@router.post("/search")
async def search_knowledge(
    body: SearchRequest, user: dict = Depends(get_current_user)
) -> dict:
    """混合检索入口（05 §5.3 契约：space_ids 必须 ⊆ 可访问空间，否则 403）。

    精准过滤（替代旧 item_name 的"指定对象过滤"能力）：
    1) filters.tags/entities 显式过滤 -> Mongo 匹配文档 -> doc_ids；
    2) 未提供 filters 时按查询做 LLM 实体预抽取 -> 命中则按实体过滤（失败降级为不过滤）。
    """
    if body.mode != "chunk":
        raise AppError(ErrorCode.VALIDATION_ERROR, "阶段一仅支持 mode=chunk", status_code=422)
    space_ids = await kb_retrieve_service.resolve_accessible_space_ids(
        user["_id"], body.space_ids
    )

    # 计算 doc_ids 预过滤
    doc_ids: list[str] | None = None
    filters = body.filters or {}
    filter_tags = filters.get("tags") or []
    filter_entities = filters.get("entities") or []
    if filter_tags or filter_entities:
        db = get_async_db()
        q: dict = {"space_id": {"$in": space_ids}}
        or_clause: list[dict] = []
        if filter_tags:
            or_clause.append({"tags": {"$in": filter_tags}})
        if filter_entities:
            or_clause.append({"metadata.entities": {"$in": filter_entities}})
        q["$or"] = or_clause
        found = {doc["doc_id"] async for doc in db["knowledge_documents"].find(q, {"doc_id": 1})}
        doc_ids = list(found) if found else []
    else:
        doc_ids = await kb_retrieve_service.resolve_doc_ids_by_entities(body.query, space_ids)

    results, elapsed_ms = await asyncio.to_thread(
        kb_retrieve_service.search_sync,
        body.query, user["_id"], space_ids, body.domain, body.top_k, doc_ids,
    )
    return {"results": results, "elapsed_ms": elapsed_ms, "filtered_doc_ids": doc_ids}


@router.post("/ask")
async def ask_knowledge(
    body: SearchRequest, user: dict = Depends(get_current_user)
) -> dict:
    """知识问答（检索 + LLM 生成带引用答案，FR-08；第一个 Agent 行为切片）。"""
    result = await qa_service.answer(
        body.query, user["_id"], body.space_ids, body.domain, body.top_k
    )
    return result


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, user: dict = Depends(get_current_user)) -> dict:
    """文档详情（含导入状态；owner 或空间成员可读）。"""
    db = get_async_db()
    doc = await db["knowledge_documents"].find_one({"doc_id": doc_id})
    if doc is None:
        raise AppError(ErrorCode.NOT_FOUND, "文档不存在", status_code=404)
    await _check_space_access(doc["space_id"], user["_id"])
    return _strip_id(doc)


@router.post("/spaces/{space_id}/documents", status_code=202)
async def upload_document(
    space_id: str,
    file: UploadFile = File(...),
    domain: str = Form("general"),
    user: dict = Depends(get_current_user),
) -> dict:
    """上传文档并排队 kb_import 导入任务（202 返回 {doc_id, task_id}）。"""
    await _check_space_access(space_id, user["_id"])

    filename = os.path.basename(file.filename or "untitled")
    file_bytes = await file.read()
    if not file_bytes:
        raise AppError(ErrorCode.VALIDATION_ERROR, "文件内容为空", status_code=422)

    doc_id, task_id, file_key = await kb_import_service.create_document(
        user["_id"], space_id, domain, filename, file_bytes
    )
    kb_import_task.delay(task_id, doc_id, user["_id"], space_id, domain, file_key)
    return {"doc_id": doc_id, "task_id": task_id}
