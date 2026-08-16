"""知识库检索服务（检索增强切片：HyDE + dense/sparse 双路 + RRF 融合 + bge-reranker 精排）。

对齐旧 query_process 节点（04 §10 映射）：
- HyDE           -> 旧 search_embedding_hyde_node（假设文档检索，提升召回）
- dense+sparse   -> 旧 search_embedding_node（BGE-M3 双输出 + 混合检索）
- RRF 融合       -> 旧 rrf_node（自实现，03 §11.2，k=60）
- rerank         -> 旧 reranker_node（bge-reranker-large 本地精排）
权限与实体预过滤沿用：space_ids ⊆ 可访问空间；查询实体 -> Mongo -> doc_ids 过滤（替代旧 item_name）。
"""
import asyncio
import json
import os
import time

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.infra.milvus import get_client
from app.infra.mongo import get_async_db
from app.services.import_pipeline import embed_query
from app.services.llm_client import chat_json, chat_text

_QUERY_ENTITY_PROMPT = (
    "你是查询实体抽取器。从用户检索查询中抽取「指定对象/关键实体」（产品型号、框架名、专有名词等），"
    "用于在文档知识库中精准过滤。\n"
    "只输出 JSON：{\"entities\": [\"...\"]}；查询中没有明确实体时输出 {\"entities\": []}。"
)

_HYDE_PROMPT = (
    "你是文档检索助手。用户有一个检索查询，请用一段连贯的、信息丰富的假设性文档回答该查询，"
    "这段文档将被用于向量检索（HyDE 技术）。假设文档应包含查询中涉及的关键概念、专有名词与可能的描述，"
    "长度 100-200 字，不要提及这是假设文档。"
)

_RRF_K = 60.0


async def resolve_accessible_space_ids(user_id: str, requested: list[str]) -> list[str]:
    """校验请求的 space_ids 都属于用户可访问空间（owner 或成员）；空列表=全部可用空间。"""
    db = get_async_db()
    accessible: set[str] = set()
    async for s in db["knowledge_spaces"].find({"owner_id": user_id}):
        accessible.add(s["space_id"])
    async for m in db["space_members"].find({"user_id": user_id}):
        accessible.add(m["space_id"])

    if not requested:
        return sorted(accessible)
    bad = [sid for sid in requested if sid not in accessible]
    if bad:
        raise AppError(ErrorCode.AUTH_FORBIDDEN, "包含不可访问的知识空间", status_code=403)
    return list(dict.fromkeys(requested))


async def resolve_doc_ids_by_entities(query: str, space_ids: list[str]) -> list[str] | None:
    """查询实体预过滤：LLM 抽实体 -> Mongo 匹配 -> doc_ids；失败返回 None（不过滤）。"""
    if not query or not space_ids:
        return None
    try:
        result = await asyncio.to_thread(
            chat_json, _QUERY_ENTITY_PROMPT, f"用户查询：{query}", None, 200
        )
        entities = [str(e).strip() for e in (result.get("entities") or []) if str(e).strip()]
        if not entities:
            return None
    except Exception:  # noqa: BLE001 - LLM 失败则跳过预过滤
        return None

    db = get_async_db()
    doc_ids: set[str] = set()
    async for doc in db["knowledge_documents"].find(
        {"space_id": {"$in": space_ids}, "metadata.entities": {"$in": entities}},
        {"doc_id": 1},
    ).limit(200):
        doc_ids.add(doc["doc_id"])
    return list(doc_ids) if doc_ids else None


def _milvus_filter(space_ids: list[str], domain: str | None, doc_ids: list[str] | None) -> str:
    expr = f"space_id in {json.dumps(space_ids)}"
    if doc_ids:
        expr += f" and doc_id in {json.dumps(doc_ids)}"
    if domain:
        expr += f" and domain == {json.dumps(domain)}"
    return expr


def _hyde_query(query: str) -> str:
    """HyDE：LLM 生成假设性文档；失败降级为原查询（不阻断检索）。"""
    s = get_settings()
    if not s.hyde_enabled:
        return query
    try:
        hypo = chat_text(_HYDE_PROMPT, f"用户检索查询：{query}", s.hyde_model, 300)
        return hypo.strip() or query
    except Exception:  # noqa: BLE001 - HyDE 失败用原查询
        return query


def _rrf_merge(rank_lists: list[list[dict]], k: float = _RRF_K) -> list[dict]:
    """RRF 融合（03 §11.2）：多路 id 排序 -> 融合排序；命中多路的加分。"""
    scores: dict[str, float] = {}
    holder: dict[str, dict] = {}
    for lst in rank_lists:
        for rank, item in enumerate(lst):
            rid = item["chunk_id"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)
            if rid not in holder:
                holder[rid] = item
    return [holder[rid] for rid in sorted(scores, key=scores.get, reverse=True)]


def _rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """bge-reranker-large 本地精排；未启用/失败时按候选顺序截断返回。"""
    s = get_settings()
    if not s.rerank_enabled or not candidates:
        return candidates[:top_k]
    try:
        reranker = _get_reranker()
        pairs = [(query, c["text"]) for c in candidates]
        scores = reranker.compute_score(pairs, normalize=True)
        if isinstance(scores, float):
            scores = [scores]
        scored = sorted(
            zip(candidates, scores), key=lambda x: float(x[1]), reverse=True
        )
        return [c for c, _ in scored[:top_k]]
    except Exception:  # noqa: BLE001 - 精排失败降级为原顺序
        return candidates[:top_k]


_reranker_model = None


def _get_reranker():
    global _reranker_model
    if _reranker_model is None:
        from FlagEmbedding import FlagReranker  # noqa: PLC0415 - 惰性加载重型依赖

        s = get_settings()
        model_path = s.reranker_model or r"D:\software\BAAI_bge-reranker_large"
        if not os.path.isdir(model_path):
            raise RuntimeError(f"reranker 模型目录不存在: {model_path}")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")  # 防误下载（同 BGE 护栏）
        _reranker_model = FlagReranker(model_path, device=s.reranker_device)
    return _reranker_model


def search_sync(
    query: str,
    user_id: str,
    space_ids: list[str],
    domain: str | None,
    top_k: int,
    doc_ids: list[str] | None = None,
) -> tuple[list[dict], int]:
    """同步检索（HyDE -> dense+sparse 双路 ANN -> RRF 融合 -> Rerank）。

    API 经线程池调用；后续 Agent 的 kb_retrieve 工具直接复用。
    """
    start = time.perf_counter()
    if not space_ids:
        return [], int((time.perf_counter() - start) * 1000)

    s = get_settings()
    client = get_client()
    expr = _milvus_filter(space_ids, domain, doc_ids)

    # 1) HyDE：假设文档（可选）
    search_query = _hyde_query(query)
    dense_vec, sparse_vec = embed_query(search_query)
    if not dense_vec:
        return [], int((time.perf_counter() - start) * 1000)

    # 2) 双路 ANN（各取 top_k*2 供 RRF 融合）
    n_cand = max(top_k * 2, s.rerank_min_topk)
    dense_res = client.search(
        collection_name=s.milvus_chunks_collection,
        data=[dense_vec],
        anns_field="dense_vector",
        search_params={"metric_type": "IP"},
        filter=expr,
        limit=n_cand,
        output_fields=["chunk_id", "doc_id", "text", "domain", "space_id"],
    )
    sparse_res = client.search(
        collection_name=s.milvus_chunks_collection,
        data=[sparse_vec],
        anns_field="sparse_vector",
        search_params={"metric_type": "IP"},
        filter=expr,
        limit=n_cand,
        output_fields=["chunk_id", "doc_id", "text", "domain", "space_id"],
    )

    def _to_items(res) -> list[dict]:
        hits = res[0] if res else []
        return [
            {
                "chunk_id": h.get("entity", {}).get("chunk_id"),
                "doc_id": h.get("entity", {}).get("doc_id"),
                "text": h.get("entity", {}).get("text"),
                "score": round(float(h.get("distance", 0.0)), 4),
            }
            for h in hits
        ]

    dense_items, sparse_items = _to_items(dense_res), _to_items(sparse_res)

    # 3) RRF 融合
    merged = _rrf_merge([dense_items, sparse_items])

    # 4) Rerank（本地精排，取 top_k）
    results = _rerank(query, merged, top_k)
    results = [
        {**r, "source": "upload", "score": round(float(r.get("score", 0.0)), 4)} for r in results
    ]

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return results, elapsed_ms
