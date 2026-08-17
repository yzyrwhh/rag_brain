"""对话端点（Supervisor 雏形）：POST /api/v1/chat（非流式）与 /chat/stream（SSE 流式）。"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.deps import get_current_user
from app.schemas.events import sse_pack
from app.services import supervisor_service

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    context: dict | None = None  # {"use_memory": bool, "spaces": [space_id]}


@router.post("")
async def chat(body: ChatRequest, user: dict = Depends(get_current_user)) -> dict:
    """统一对话入口：意图识别 -> 路由（知识问答/通用对话/澄清/上传提示）。"""
    spaces = (body.context or {}).get("spaces") if body.context else None
    result = await supervisor_service.chat(body.query, user["_id"], spaces, top_k=5)
    result["session_id"] = body.session_id
    return result


@router.post("/stream")
async def chat_stream(body: ChatRequest, user: dict = Depends(get_current_user)):
    """SSE 流式对话（05 §3.2/§8 契约：agent.thinking -> message.delta* -> message.final）。"""
    spaces = (body.context or {}).get("spaces") if body.context else None

    async def _events():
        async for ev in supervisor_service.chat_stream(
            body.query, user["_id"], body.session_id, spaces, top_k=5
        ):
            yield sse_pack(ev["type"], ev["payload"])

    return StreamingResponse(_events(), media_type="text/event-stream")


@router.get("/sessions")
async def list_sessions(user: dict = Depends(get_current_user)) -> dict:
    """我的会话列表（按更新时间倒序）。"""
    from app.infra.mongo import get_async_db

    db = get_async_db()
    cursor = (
        db["sessions"]
        .find({"user_id": user["_id"], "deleted": {"$ne": True}})
        .sort("updated_at", -1)
        .limit(50)
    )
    items = []
    async for s in cursor:
        items.append(
            {
                "session_id": s["session_id"],
                "title": s.get("title", ""),
                "updated_at": s.get("updated_at", ""),
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str, user: dict = Depends(get_current_user)
) -> dict:
    """会话历史消息（升序）。"""
    from app.infra.mongo import get_async_db

    db = get_async_db()
    session = await db["sessions"].find_one(
        {"session_id": session_id, "user_id": user["_id"]}
    )
    if session is None:
        from app.core.errors import AppError, ErrorCode

        raise AppError(ErrorCode.NOT_FOUND, "会话不存在", status_code=404)
    cursor = (
        db["messages"]
        .find({"session_id": session_id, "user_id": user["_id"]})
        .sort("ts", 1)
        .limit(200)
    )
    items = []
    async for m in cursor:
        items.append(
            {
                "role": m.get("role", ""),
                "text": m.get("text", ""),
                "metadata": m.get("metadata") or {},
                "ts": m.get("ts", ""),
            }
        )
    return {"items": items, "total": len(items)}
