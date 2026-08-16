"""SSE 事件协议（对齐 docs/05 §8 事件表，实现契约）。"""
import json


class SSEEvent:
    READY = "task.ready"
    PLAN = "task.plan"
    NODE_START = "node.start"
    NODE_END = "node.end"
    THINKING = "agent.thinking"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    CLARIFY = "clarify"
    CLARIFY_ANSWERED = "clarify.answered"
    ASYNC_UPGRADED = "task.async_upgraded"
    DELTA = "message.delta"
    FINAL = "message.final"
    COMPLETED = "task.completed"
    FAILED = "task.failed"
    CANCELLED = "task.cancelled"


def sse_pack(event_type: str, payload: dict) -> str:
    """打包一条 SSE 消息：event: <type>\ndata: <json>\n\n"""
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"
