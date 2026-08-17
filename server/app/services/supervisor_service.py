"""Supervisor 雏形：意图识别 + 路由（对齐 04 §2.1 与 07 §2.2 意图 JSON schema）。

Phase 1：knowledge_query -> 知识问答；general_chat -> 通用对话；
knowledge_import -> 提示走上传；unclear -> 澄清；"记住"指令 -> 显式记忆写入。
其余域（dev/research/life）已登记意图，阶段二接到对应域 Agent。
"""
import asyncio
import logging
import time

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.intents import Domain, INTENT_ROUTES, Intent, RouteTarget
from app.schemas.events import SSEEvent
from app.services import chat_service, qa_service
from app.services.llm_client import chat_json, chat_text, chat_text_stream

_INTENT_SYSTEM_PROMPT = (
    "你是掌柜智库的意图识别器。根据用户输入输出 JSON：\n"
    "{\n"
    "  \"intent\": \"knowledge_query|knowledge_import|general_chat|dev_consult|"
    "research_paper_search|life_recommend|unclear\",\n"
    "  \"domain\": \"knowledge|dev|research|life|general\",\n"
    "  \"task_type\": \"sync|async\",\n"
    "  \"entities\": {\"topic\": \"\", \"limit\": 10, \"years\": \"\"},\n"
    "  \"confidence\": 0.0-1.0,\n"
    "  \"needs_clarification\": false\n"
    "}\n"
    "规则：问知识库/文档内容/产品资料 -> knowledge_query；要上传/导入文档 -> knowledge_import；"
    "寒暄/闲聊/无明确诉求 -> general_chat；开发技术问题 -> dev_consult；找论文/研究资料 -> "
    "research_paper_search；外卖/购物/生活推荐 -> life_recommend；意图不清且置信度低 -> unclear。"
    "只输出 JSON。"
)

_GENERAL_SYSTEM = (
    "你是掌柜智库的智能助手，简洁友好地回答用户。若用户问题需要知识库内容，"
    "请告知「可以尝试在知识库中搜索」；不要编造事实。"
)

_ROUTE_NOT_READY = {
    Intent.RESEARCH_PAPER: "研究域助手（论文检索）正在建设中。",
    Intent.LIFE_RECOMMEND: "生活域助手（比价推荐）正在建设中。",
}

# "记住"指令前缀（显式记忆写入，Route A 显式优先）
_REMEMBER_PREFIXES = ("记住", "帮我记住", "记一下", "帮我记一下")


async def classify(query: str) -> dict:
    """意图识别（LLM JSON 模式）；失败降级为 general_chat + 低置信度。"""
    s = get_settings()
    try:
        result = await asyncio.to_thread(
            chat_json, _INTENT_SYSTEM_PROMPT, f"用户输入：{query}", s.intent_model, 300
        )
        intent = result.get("intent") or "unclear"
        if intent not in {i.value for i in Intent}:
            intent = "unclear"
        return {
            "intent": intent,
            "domain": result.get("domain", "general"),
            "task_type": result.get("task_type", "sync"),
            "entities": result.get("entities") or {},
            "confidence": float(result.get("confidence", 0.0)),
            "needs_clarification": bool(result.get("needs_clarification", False)),
        }
    except Exception:  # noqa: BLE001 - 意图识别失败不阻断对话
        return {
            "intent": "general_chat",
            "domain": "general",
            "task_type": "sync",
            "entities": {},
            "confidence": 0.0,
            "needs_clarification": False,
        }


async def chat(
    query: str,
    user_id: str,
    space_ids: list[str] | None = None,
    top_k: int = 5,
) -> dict:
    """统一对话入口：意图识别 -> 路由到对应处理器。返回 {intent, domain, confidence, answer, sources}。"""
    start = time.perf_counter()
    intent_info = await classify(query)
    intent = Intent(intent_info["intent"])
    domain, route = INTENT_ROUTES[intent]
    s = get_settings()

    if route == RouteTarget.QA:
        result = await qa_service.answer(query, user_id, space_ids, None, top_k)
        answer, sources = result["answer"], result.get("sources", [])
    elif route == RouteTarget.UPLOAD:
        answer = "知识库导入请使用「上传文档」功能（POST /api/v1/knowledge/spaces/{sid}/documents）。"
        sources = []
    elif intent == Intent.DEV_CONSULT:
        # Phase 2：开发域方案咨询 = 检索 dev 域知识库 + 生成（domain=dev 过滤）
        result = await qa_service.answer(query, user_id, space_ids, "dev", top_k)
        answer, sources = result["answer"], result.get("sources", [])
    elif route == RouteTarget.CHAT and intent in _ROUTE_NOT_READY:
        answer = _ROUTE_NOT_READY[intent]
        sources = []
    elif route == RouteTarget.CLARIFY:
        answer = "我还没太明白你的需求，能否说得更具体一些？（比如：查资料、上传文档、找论文、点外卖）"
        sources = []
    else:  # general_chat
        try:
            answer = await asyncio.to_thread(
                chat_text, _GENERAL_SYSTEM, query, s.qa_model, 500
            )
        except Exception:  # noqa: BLE001
            answer = "抱歉，我暂时无法回答，请稍后再试。"
        sources = []

    return {
        "intent": intent.value,
        "domain": domain.value,
        "confidence": intent_info["confidence"],
        "task_type": intent_info["task_type"],
        "entities": intent_info["entities"],
        "answer": answer,
        "sources": sources,
        "elapsed_ms": int((time.perf_counter() - start) * 1000),
    }


def _match_remember(query: str) -> str | None:
    """匹配"记住"指令，返回去掉前缀与标点的记忆内容；不匹配返回 None。"""
    for p in _REMEMBER_PREFIXES:
        if query.startswith(p):
            content = query[len(p):].strip().lstrip("：:,， ").strip()
            if content:
                return content
    return None


async def chat_stream(
    query: str,
    user_id: str,
    session_id: str | None = None,
    space_ids: list[str] | None = None,
    top_k: int = 5,
):
    """SSE 流式对话（05 §3.2/§8 契约）：session -> 历史 -> 意图 -> 路由 -> 流式生成 -> 落库。

    yield {"type": SSEEvent 事件名, "payload": {...}}；由端点 sse_pack 输出。
    所有分支把文本收集进 parts，最终统一落库与发 FINAL 事件。
    """
    s = get_settings()
    # 1) 会话与消息落库
    sid = await chat_service.ensure_session(user_id, session_id, query)
    history = await chat_service.get_history(user_id, sid)
    await chat_service.save_message(user_id, sid, "user", query)

    # 2) "记住"指令：优先处理，不走意图识别（避免误路由 + 省一次 LLM）
    remember_text = _match_remember(query)
    if remember_text is not None:
        yield {"type": SSEEvent.THINKING, "payload": {"text": "正在记录…"}}
        from app.services import memory_service

        try:
            await memory_service.memory_write(user_id, "fact", remember_text, source="user")
            text = f"已记住：{remember_text}"
        except AppError as e:
            # 业务错误透传真实 message（统一错误体系）
            logging.getLogger(__name__).warning("记住指令业务错误: %s", e.message)
            text = e.message
        except Exception:  # noqa: BLE001 - 未知异常记日志 + 通用文案
            logging.getLogger(__name__).exception("记住指令写入失败 user_id=%s", user_id)
            text = "抱歉，记录时遇到问题，请稍后在「知识库-记忆」页重试。"
        yield {"type": SSEEvent.DELTA, "payload": {"text": text}}
        yield {
            "type": SSEEvent.FINAL,
            "payload": {"text": text, "sources": [], "intent": "general_chat"},
        }
        return

    # 3) 意图识别
    yield {"type": SSEEvent.THINKING, "payload": {"text": "正在理解你的问题..."}}
    intent_info = await classify(query)
    intent = Intent(intent_info["intent"])
    domain, route = INTENT_ROUTES[intent]

    async def _stream_generate(
        system: str, user_prompt: str, model: str, parts: list[str], max_tokens: int = 1024
    ):
        """流式生成：逐片 yield DELTA 事件并收集到 parts。"""
        gen = chat_text_stream(system, user_prompt, model, max_tokens)
        while True:
            piece = await asyncio.to_thread(next, gen, None)
            if piece is None:
                break
            parts.append(piece)
            yield {"type": SSEEvent.DELTA, "payload": {"text": piece}}

    parts: list[str] = []
    sources: list[dict] = []
    try:
        if route == RouteTarget.QA:
            yield {"type": SSEEvent.THINKING, "payload": {"text": "正在检索知识库..."}}
            user_prompt, sources = await qa_service.retrieve_context(
                query, user_id, space_ids, None, top_k, history
            )
            if not user_prompt:
                parts.append("根据现有资料未找到相关内容。")
                yield {"type": SSEEvent.DELTA, "payload": {"text": parts[-1]}}
            else:
                async for ev in _stream_generate(
                    _QA_SYSTEM_PROMPT, user_prompt, s.qa_model, parts, 1024
                ):
                    yield ev
        elif route == RouteTarget.UPLOAD:
            parts.append(
                "知识库导入请使用「上传文档」功能（POST /api/v1/knowledge/spaces/{sid}/documents）。"
            )
            yield {"type": SSEEvent.DELTA, "payload": {"text": parts[-1]}}
        elif route == RouteTarget.CHAT and intent in _ROUTE_NOT_READY:
            parts.append(_ROUTE_NOT_READY[intent])
            yield {"type": SSEEvent.DELTA, "payload": {"text": parts[-1]}}
        elif route == RouteTarget.CLARIFY:
            parts.append(
                "我还没太明白你的需求，能否说得更具体一些？（比如：查资料、上传文档、找论文、点外卖）"
            )
            yield {"type": SSEEvent.DELTA, "payload": {"text": parts[-1]}}
        else:  # general_chat（含历史）
            history_block = ""
            if history:
                history_block = "\n".join(
                    f"{'用户' if h.get('role') == 'user' else '助手'}: {h.get('text', '')}"
                    for h in history[-4:]
                )
            user_prompt = f"{query}\n\n历史对话：\n{history_block}" if history_block else query
            async for ev in _stream_generate(
                _GENERAL_SYSTEM, user_prompt, s.qa_model, parts, 500
            ):
                yield ev
    except AppError as e:  # 业务错误：透传真实 message
        logging.getLogger(__name__).warning("chat_stream 业务错误: %s", e.message)
        parts.append(e.message)
        yield {"type": SSEEvent.DELTA, "payload": {"text": parts[-1]}}
    except Exception:  # noqa: BLE001 - 未知异常：记日志 + 通用文案
        logging.getLogger(__name__).exception("chat_stream 异常 user_id=%s", user_id)
        parts.append("抱歉，回答生成失败，请稍后再试。")
        yield {"type": SSEEvent.DELTA, "payload": {"text": parts[-1]}}

    answer_text = "".join(parts)

    # 3) 落库助手消息 + 结束事件
    await chat_service.save_message(
        user_id, sid, "assistant", answer_text,
        metadata={"intent": intent.value, "domain": domain.value, "sources": sources},
    )
    yield {
        "type": SSEEvent.FINAL,
        "payload": {"text": answer_text, "sources": sources, "intent": intent.value},
    }
