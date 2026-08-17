"""会话与消息服务（对齐 03 §3.2 sessions / §3.3 messages；多轮历史注入）。

- ensure_session: 无 session_id 则创建（title=首条消息前缀）
- get_history: 会话最近 N 条消息（role/text），供历史注入（补旧 answer_output 的 history 能力）
- save_message: 用户/助手消息落库
"""
import datetime
import uuid

from app.core.config import get_settings
from app.infra.mongo import get_async_db

_UTC = datetime.timezone.utc
_HISTORY_LIMIT = 6


def _now() -> str:
    return datetime.datetime.now(_UTC).isoformat()


async def ensure_session(user_id: str, session_id: str | None, first_query: str) -> str:
    """返回 session_id；不存在则创建。"""
    db = get_async_db()
    if session_id:
        session = await db["sessions"].find_one({"session_id": session_id, "user_id": user_id})
        if session is not None:
            return session_id
    new_id = str(uuid.uuid4())
    now = _now()
    await db["sessions"].insert_one(
        {
            "session_id": new_id,
            "user_id": user_id,
            "title": first_query[:30] or "新会话",
            "agent": "supervisor",
            "context": {},
            "deleted": False,
            "created_at": now,
            "updated_at": now,
        }
    )
    return new_id


async def get_history(user_id: str, session_id: str, limit: int = _HISTORY_LIMIT) -> list[dict]:
    """最近 limit 条消息（升序）。"""
    if not session_id:
        return []
    db = get_async_db()
    cursor = (
        db["messages"]
        .find({"session_id": session_id, "user_id": user_id, "role": {"$in": ["user", "assistant"]}})
        .sort("ts", 1)
        .limit(limit)
    )
    msgs = [doc async for doc in cursor]
    return [{"role": m["role"], "text": m.get("text", "")} for m in msgs]


async def save_message(
    user_id: str, session_id: str, role: str, text: str, metadata: dict | None = None
) -> None:
    db = get_async_db()
    await db["messages"].insert_one(
        {
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "text": text,
            "task_id": None,
            "metadata": metadata or {},
            "ts": _now(),
        }
    )
    await db["sessions"].update_one(
        {"session_id": session_id}, {"$set": {"updated_at": _now()}}
    )
