"""语义记忆服务（FR-35 写入时融合；对齐 03 §3.11 字段契约）。

写入策略（增量更新而非堆积，增删改查四分支）：
1. 先查相似（同 domain+type，bigram Dice 打分 + 共享英文技术词标记）
2. 等价(≥0.8) → 查：use_count+1 更新时间，不新增
3. 相关 → 改：LLM 语义决策（03 §10.6 写入时融合）：
   - merge（互补/多视角）→ 新旧全部要点合并为一条，merged_from 溯源，不覆盖
   - supersede（演进/替代）→ 整合演进脉络，旧条目归档记 supersedes
4. 无关 → 增：新增条目
场景累积：内容中的"X场景"提取追加 scenarios；LLM 兜底隐式场景
"""
import asyncio
import datetime
import re
import uuid

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.infra.mongo import get_async_db

_UTC = datetime.timezone.utc

# 显式用户输入最高信任；agent 推断次之；任务沉淀再次
_TRUST = {"user": 1.0, "agent": 0.7, "task": 0.6}

# 🧪 相似度阈值（08 §8.1 待评测校准；实测中文短文本 Dice 偏低：0.4 会漏融合，降至 0.25）
_EQUIVALENT = 0.8    # 等价：不新增，计数
_RELATED = 0.25      # 相关：触发融合
_CLIFF_GAP = 0.15    # 断崖检测阈值

_MERGE_SYSTEM_PROMPT = (
    "你是经验整合助手。判断「新经验」与「相关旧经验」的关系类型并融合。\n"
    "先判断关系：\n"
    "- **merge（互补/多视角）**：新旧经验是同一主题的不同方面（如一个是技术选型偏好、"
    "一个是状态设计经验），必须**全部保留**，合并为一条含多个要点的内容；\n"
    "- **supersede（演进/替代）**：新经验是旧经验的更优替代或时间演进（如方案 B 在同样场景"
    "下比方案 A 好），整合为演进后的内容（保留旧方案→新方案的脉络）。\n"
    "输出要求：\n"
    "1. 只输出 JSON：{\"action\": \"merge\" 或 \"supersede\", \"content\": \"融合后的单条经验\"}；\n"
    "2. content 不超过 500 字，明确适用场景，不编造；\n"
    "3. merge 时 content 必须包含新旧所有要点（可用「其一/其二」或分号组织）；"
    "supersede 时体现演进（旧方案 → 新方案及原因）。"
)


def _now() -> str:
    return datetime.datetime.now(_UTC).isoformat()


def _strip(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[\s，。、；：！？,.!?（）()：]+", text) if t]


def _extract_scenarios(content: str) -> list[str]:
    """从内容提取"适用场景"（宽松：取"X场景/X场景下"中的 X，无需触发词）。

    示例："高并发场景下用 Celery" → ["高并发"]；"离线批处理场景 arq 更轻量" → ["离线批处理"]。
    """
    found: list[str] = []
    for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9]{1,10}?)(?:场景|场景下|情况下)", content):
        word = m.group(1).strip()
        if word and len(word) <= 10 and word not in found:
            found.append(word)
    return found


_SCENARIO_LLM_PROMPT = (
    "你是场景识别器。从用户要记住的经验内容中识别**隐式适用场景**（正则难以提取的表达，"
    "如「什么情况下」「哪种项目」「什么时候用」等），补充到场景列表。\n"
    "规则：\n"
    "1. 场景是简短名词短语（≤8 字），如「高并发」「离线批处理」「移动端」「初创项目」「生产环境」；\n"
    "2. 只输出与内容真正相关的场景，宁缺毋滥；没有隐式场景时输出空数组；\n"
    "3. 只输出 JSON：{\"scenarios\": [\"...\"]}。"
)


def _extract_scenarios_llm(content: str) -> list[str]:
    """LLM 兜底场景识别（隐式表达；JSON 模式；失败降级为空，不阻断写入）。"""
    from app.services.llm_client import chat_json

    try:
        result = chat_json(
            _SCENARIO_LLM_PROMPT, f"待识别的经验内容：{content[:1000]}", None, 200
        )
        items = [str(s).strip()[:10] for s in (result.get("scenarios") or []) if str(s).strip()]
        return items[:5]
    except Exception:  # noqa: BLE001 - LLM 失败降级
        return []


_DOMAIN_LLM_PROMPT = (
    "你是领域归属判断器。判断一段经验/内容应归属到哪个**已有领域**。\n"
    "候选领域：{candidates}\n"
    "规则：\n"
    "1. 从候选领域中选最匹配的一个（如「Celery 任务队列」→ dev；「民法典条款」→ law）；\n"
    "2. 置信度 ≥ 0.8 才可归入指定领域；否则返回 general；\n"
    "3. 不得输出候选之外的新领域名（新领域需用户显式创建）；\n"
    "4. 只输出 JSON：{\"domain\": \"...\", \"confidence\": 0.0-1.0}。"
)


async def _judge_domain(user_id: str, content: str) -> str:
    """LLM 判断内容归属已有领域（高置信归入，低置信 general）。失败降级 general。"""
    from app.services.llm_client import chat_json

    db = get_async_db()
    try:
        # motor distinct 是协程（await 返回 list），不是游标
        raw_domains = await db["memories"].distinct("domain", {"user_id": user_id})
        candidates = ["general", *sorted(d for d in raw_domains if d and d != "general")]
    except Exception:  # noqa: BLE001 - 领域列表失败用 general
        candidates = ["general"]
    try:
        result = await asyncio.to_thread(
            chat_json,
            _DOMAIN_LLM_PROMPT.format(candidates=", ".join(candidates)),
            f"待归类内容：{content[:1000]}",
            None,
            200,
        )
        domain = str(result.get("domain") or "general").strip()
        confidence = float(result.get("confidence", 0.0))
        if domain in candidates and confidence >= 0.8:
            return domain
        return "general"
    except Exception:  # noqa: BLE001 - LLM 失败降级 general
        return "general"


def _bigrams(text: str) -> set[str]:
    """字符二元组（中文相似度基础；英文大小写归一化，提升中英混排匹配）。"""
    text = text.lower()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _dice_sim(a: str, b: str) -> float:
    """Dice 系数：2×交集 / (A+B)，对中文主题词敏感。"""
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0
    return round(2.0 * len(ba & bb) / (len(ba) + len(bb)), 3)


def _shared_english_tokens(a: str, b: str) -> set[str]:
    """共享英文技术词（≥3 字母，大小写不敏感）。中英混排时是"同主题"的强信号。"""
    ta = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", a.lower()))
    tb = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", b.lower()))
    return ta & tb


async def _find_similar(
    user_id: str, type_: str, content: str, domain: str = "general", limit: int = 5
) -> list[dict]:
    """找相似记忆（bigram Dice 打分 + 共享技术词标记；同 domain 限定）。"""
    db = get_async_db()
    q = {"user_id": user_id, "status": "active", "type": type_, "domain": domain}
    candidates = [doc async for doc in db["memories"].find(q).limit(100)]
    scored = []
    for c in candidates:
        old = c.get("content", "")
        sim = _dice_sim(content, old)
        if sim > 0 or _shared_english_tokens(content, old):
            scored.append({**c, "score": sim, "shared_topic": bool(_shared_english_tokens(content, old))})
    scored.sort(key=lambda x: (x["score"], 1 if x["shared_topic"] else 0), reverse=True)
    return scored[:limit]


def _cliff_cut(scored: list[dict]) -> list[dict]:
    """断崖截取：按相似度降序，相邻 gap 超过阈值处截断（只取高相关部分）。"""
    if len(scored) <= 1:
        return scored
    kept = [scored[0]]
    for i in range(1, len(scored)):
        if scored[i - 1]["score"] - scored[i]["score"] > _CLIFF_GAP:
            break
        kept.append(scored[i])
    return kept


async def _consolidate(
    user_id: str, type_: str, content: str, similar: list[dict], scenarios: list[str],
    domain: str = "general",
) -> str:
    """相关融合（增量更新，语义决策 merge/supersede）。

    - **merge**（互补/多视角，如"状态设计用字典"+"Agent 编排用 LangGraph"）：LLM 把新旧
      全部要点合并为一条内容；最相关旧条目就地更新（merged_from 记录来源），**不**归档；
    - **supersede**（演进/替代，如方案 B 取代方案 A）：整合演进内容，旧条目归档并记 supersedes；
    - LLM 失败降级：新内容直接并入最相关条目（不丢旧要点，也不归档）。
    返回 memory_id（始终返回最相关旧条目，不新增）。
    """
    from app.services.llm_client import chat_json

    db = get_async_db()
    kept = _cliff_cut(similar)
    if not kept:
        return await _insert_new(user_id, type_, content, scenarios, domain=domain)

    target = kept[0]
    target_id = target["memory_id"]
    now = _now()

    # 旧内容按时间序拼接（早 → 晚）
    ordered = sorted(kept, key=lambda x: x.get("created_at", ""))
    old_blocks = "\n".join(f"[旧经验 {i+1}] {c['content']}" for i, c in enumerate(ordered))

    action = "merge"  # 默认保守：合并不覆盖
    merged_text = content
    try:
        s = get_settings()
        user_prompt = f"新经验：{content}\n\n相关旧经验：\n{old_blocks}"
        result = await asyncio.to_thread(
            chat_json, _MERGE_SYSTEM_PROMPT, user_prompt, s.qa_model, 600
        )
        action = str(result.get("action") or "merge").strip().lower()
        if action not in ("merge", "supersede"):
            action = "merge"
        merged_text = str(result.get("content") or "").strip()
        if not merged_text:
            # content 缺失时保底：不丢旧要点，也不覆盖
            merged_text = content + ("；" if content else "") + "；".join(
                c["content"] for c in ordered if c["content"] not in (content, "")
            )
    except Exception:  # noqa: BLE001 - 提纯失败保底：新内容并入旧条目（不覆盖不归档）
        old_points = [c["content"] for c in ordered if c["content"] not in (content, "")]
        if old_points:
            merged_text = content + "；" + "；".join(old_points)

    # 场景合并：旧条目 scenarios 并集 + 提取 + 新增
    merged_scenarios = list(dict.fromkeys([
        *(target.get("scenarios") or []),
        *_extract_scenarios(merged_text),
        *scenarios,
    ]))

    update = {
        "content": merged_text[:2000],
        "scenarios": merged_scenarios,
        "importance": max(target.get("importance", 3), 3),
        "updated_at": now,
    }
    others = [c["memory_id"] for c in kept[1:] if c["memory_id"] != target_id]
    if others:
        if action == "merge":
            # 互补合并：其他相关条目并入后归档，来源记入 merged_from（不标记 supersede）
            update["merged_from"] = list(dict.fromkeys([
                *(target.get("merged_from") or []), *others
            ]))
            await db["memories"].update_many(
                {"memory_id": {"$in": others}},
                {"$set": {"status": "archived", "updated_at": now}},
            )
        else:
            # 演进替代：旧条目归档并记入 supersedes（检索时降权）
            update["supersedes"] = list(dict.fromkeys([
                *(target.get("supersedes") or []), *others
            ]))
            await db["memories"].update_many(
                {"memory_id": {"$in": others}},
                {"$set": {"status": "archived", "updated_at": now}},
            )
    await db["memories"].update_one({"memory_id": target_id}, {"$set": update})
    return target_id


async def _insert_new(
    user_id: str, type_: str, content: str, scenarios: list[str],
    tags: list[str] | None = None, importance: int = 3, source: str = "user",
    linked_ids: list[str] | None = None, domain: str = "general",
) -> str:
    db = get_async_db()
    memory_id = str(uuid.uuid4())
    now = _now()
    doc = {
        "memory_id": memory_id,
        "user_id": user_id,
        "layer": "l1",
        "type": type_,
        "domain": domain,
        "content": content.strip()[:2000],
        "scene_name": None,
        "scenarios": list(dict.fromkeys(scenarios)),
        "source": source,
        "source_message_ids": [],
        "trust": _TRUST.get(source, 0.6),
        "tags": tags or [],
        "importance": max(1, min(5, importance)),
        "use_count": 0,
        "last_used_at": None,
        "avg_rating": None,
        "supersedes": [],
        "merged_from": [],
        "linked_ids": linked_ids or [],
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    await db["memories"].insert_one(doc)
    return memory_id


async def memory_write(
    user_id: str,
    type_: str,
    content: str,
    tags: list[str] | None = None,
    importance: int = 3,
    source: str = "user",
    linked_ids: list[str] | None = None,
    scenarios: list[str] | None = None,
    domain: str | None = None,
) -> str:
    """写入语义记忆（FR-35 写入时融合 + FR-37/38 场景/领域智能识别）。返回 memory_id。"""
    if not content or not content.strip():
        raise AppError(ErrorCode.VALIDATION_ERROR, "记忆内容不能为空", status_code=422)
    content = content.strip()

    # 场景：正则优先（零成本），正则为空则 LLM 兜底（隐式表达）
    if scenarios is None:
        scenarios = _extract_scenarios(content)
        if not scenarios:
            scenarios = _extract_scenarios_llm(content)

    # 领域：未显式指定则由 LLM 判断归属（高置信归已有域，否则 general；不自动新建）
    if domain is None:
        domain = await _judge_domain(user_id, content)

    # 1) 查相似（同 domain + 同 type）
    similar = await _find_similar(user_id, type_, content, domain)
    if similar:
        best = similar[0]
        # 2) 等价 → 计数更新时间，不新增
        if best["score"] >= _EQUIVALENT:
            db = get_async_db()
            await db["memories"].update_one(
                {"memory_id": best["memory_id"]},
                {"$inc": {"use_count": 1}, "$set": {"last_used_at": _now()}},
            )
            return best["memory_id"]
        # 3) 相关 → 融合提纯（增量更新）。
        #    Dice 达阈值，或共享英文技术词（同主题不同方面，如"状态设计"vs"框架选型"）
        if best["score"] >= _RELATED or best.get("shared_topic"):
            return await _consolidate(user_id, type_, content, similar, scenarios, domain)
    # 4) 无关 → 新增
    return await _insert_new(
        user_id, type_, content, scenarios, tags, importance, source, linked_ids, domain
    )


async def memory_search(
    user_id: str, query: str, kind: str | None = None, limit: int = 5
) -> list[dict]:
    """关键词检索语义记忆。"""
    db = get_async_db()
    q: dict = {"user_id": user_id, "status": "active"}
    if kind:
        q["type"] = kind
    terms = _tokenize(query)[:5]
    if terms:
        q["$or"] = [{"content": {"$regex": re.escape(t), "$options": "i"}} for t in terms]
    cursor = db["memories"].find(q).sort("updated_at", -1).limit(limit)
    return [_strip(doc) async for doc in cursor]


async def memory_list(
    user_id: str, kind: str | None = None, page: int = 1, page_size: int = 20
) -> dict:
    db = get_async_db()
    q: dict = {"user_id": user_id, "status": "active"}
    if kind:
        q["type"] = kind
    cursor = (
        db["memories"].find(q).sort("updated_at", -1)
        .skip((page - 1) * page_size).limit(page_size)
    )
    items = [_strip(doc) async for doc in cursor]
    total = await db["memories"].count_documents(q)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def memory_delete(user_id: str, memory_id: str) -> None:
    db = get_async_db()
    r = await db["memories"].delete_one({"memory_id": memory_id, "user_id": user_id})
    if r.deleted_count == 0:
        raise AppError(ErrorCode.NOT_FOUND, "记忆不存在", status_code=404)


async def save_from_task(
    user_id: str, task_id: str, kind: str = "dev_case", tags: list[str] | None = None
) -> str:
    """任务结果沉淀为经验（DevAgent 经验沉淀入口）。"""
    db = get_async_db()
    task = await db["tasks"].find_one({"task_id": task_id, "user_id": user_id})
    if task is None:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在", status_code=404)
    result = task.get("result") or {}
    text = result.get("text") or result.get("answer") or ""
    if not text:
        raise AppError(ErrorCode.VALIDATION_ERROR, "该任务没有可沉淀的文本结果", status_code=422)
    return await memory_write(
        user_id, kind, text[:2000], tags, importance=3,
        source="task", linked_ids=[task_id],
    )
