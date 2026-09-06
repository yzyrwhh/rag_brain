from typing import List, Dict, Tuple, Optional

from pymilvus import AnnSearchRequest, Collection, WeightedRanker

# ============ 向量索引 metric 统一配置（单一事实源：建索引与检索共用） ============
# 商品名集合：语义相似度对齐（余弦）
ITEM_NAME_DENSE_METRIC = "COSINE"
ITEM_NAME_SPARSE_METRIC = "IP"
# 切片集合：内积（BGE 向量 L2 归一化后与余弦等价，检索更高效）
CHUNK_DENSE_METRIC = "IP"
CHUNK_SPARSE_METRIC = "IP"


def build_hybrid_search_requests(
        dense_vector: List[float],
        sparse_vector: Dict[int, float],
        top_k: int = 5,
        dense_search_params={"metric_type": CHUNK_DENSE_METRIC},
        sparse_search_params={"metric_type": CHUNK_SPARSE_METRIC},
        filter_expr: Optional[str] = None,
        dense_field: str = "dense_vector",
        sparse_field: str = "sparse_vector",
) -> List[AnnSearchRequest]:
    """
    构建混合检索请求

    Args:
        dense_vector: 稠密向量
        sparse_vector: 稀疏向量（字典格式 {token_id: weight}）
        top_k: 每个请求返回的候选数
        dense_search_params: 稠密检索参数，默认与切片集合索引一致（CHUNK_DENSE_METRIC）
        sparse_search_params: 稀疏检索参数，默认与切片集合索引一致（CHUNK_SPARSE_METRIC）
    Returns:
        AnnSearchRequest 列表 [dense_request, sparse_request]
    """
    dense_params = {
        "metric_type": CHUNK_DENSE_METRIC,
        "params": {"nprobe": 10},
        **(dense_search_params or {}),
    }
    sparse_params = {
        "metric_type": CHUNK_SPARSE_METRIC,
        **(sparse_search_params or {}),
    }
    common_kwargs = {
        "limit": top_k,
        "expr": filter_expr,  # 如果为 None，Milvus 会忽略
    }

    # 稠密向量搜索请求
    dense_request = AnnSearchRequest(
        data=[dense_vector],
        anns_field=dense_field,
        param=dense_params,
        **common_kwargs,
    )

    # 稀疏向量搜索请求
    sparse_request = AnnSearchRequest(
        data=[sparse_vector],
        anns_field=sparse_field,
        param=sparse_params,
        **common_kwargs,
    )

    return [dense_request, sparse_request]

def execute_hybrid_search(
    client,
    collection_name: str,
    search_requests: List[AnnSearchRequest],            ############向量#################
    ranker_weights: Tuple[float, float] = (0.5, 0.5),
    top_k: int = 5,
    normalize_score: bool = True,
    output_fields: List[str] = None,
) -> List[List[Dict]]:
    """
       执行混合检索

       Args:
           client: Milvus 客户端（暂未使用，预留）
           collection_name: 集合名称
           search_requests: 搜索请求列表
           ranker_weights: 权重 (dense_weight, sparse_weight)
           top_k: 最终返回的候选数
           normalize_score: 是否归一化分数
           output_fields: 需要返回的字段

       Returns:
           搜索结果列表
       """

    if not client:
        raise RuntimeError("Milvus 客户端未连接")

    ranker = WeightedRanker(ranker_weights[0], ranker_weights[1])

    # 确保集合已加载（Milvus 重启/索引重建后可能未加载；检索前检查，已加载零开销，未加载自动恢复）
    try:
        state = client.get_load_state(collection_name)
        if getattr(state.get("state"), "name", None) != "Loaded":
            client.load_collection(collection_name)
    except Exception:
        pass

    results = client.hybrid_search(
        collection_name=collection_name,
        reqs=search_requests,
        ranker=ranker,
        limit=top_k,
        output_fields=output_fields or [],
    )

    # 格式化结果
    formatted_results = []
    for result in results:
        hits = []
        for hit in result:
            entity = {field: hit.get(field) for field in (output_fields or [])}

            # 归一化分数
            distance = hit.get("distance", 0)
            if normalize_score:
                distance = max(0, min(1, (distance + 1) / 2))

            hits.append({
                "id": hit.get("id"),
                "distance": distance,
                "entity": entity
            })
        formatted_results.append(hits)

    return formatted_results


def ensure_collection_index(
    client, collection_name, field, index_name, index_type, metric, params=None,
):
    """创建/重建指定字段的向量索引（供 reconcile_collection_indexes 使用）。"""
    ip = client.prepare_index_params()
    if params:
        ip.add_index(field_name=field, index_name=index_name, index_type=index_type,
                     metric_type=metric, params=params)
    else:
        ip.add_index(field_name=field, index_name=index_name, index_type=index_type,
                     metric_type=metric)
    client.create_index(collection_name, ip)


def reconcile_collection_indexes(client, collection_name, expected):
    """校验并修复集合向量索引（单一事实源自愈）。

    与期望 metric 不一致的索引会被原地重建（数据无损），并返回修复记录。
    幂等：索引一致时不做任何操作。

    Args:
        client: MilvusClient 实例
        collection_name: 集合名
        expected: 期望索引规格列表，每项形如
            {"field", "index_name", "index_type", "metric", "params"?}
    """
    rebuilt = []
    existing = {}
    for name in client.list_indexes(collection_name):
        try:
            info = client.describe_index(collection_name, name)
            existing[info["field_name"]] = (name, info["metric_type"])
        except Exception:
            continue

    for spec in expected:
        field = spec["field"]
        cur = existing.get(field)
        if cur and cur[1] == spec["metric"]:
            continue
        if cur:
            try:
                client.drop_index(collection_name, cur[0])
            except Exception:
                # 集合处于加载状态时可能拒绝删索引：先释放再重试
                try:
                    client.release_collection(collection_name)
                except Exception:
                    pass
                client.drop_index(collection_name, cur[0])
        ensure_collection_index(
            client, collection_name, field, spec["index_name"],
            spec["index_type"], spec["metric"], spec.get("params"),
        )
        # 重建后确保集合可检索（已加载则无副作用）
        try:
            client.load_collection(collection_name)
        except Exception:
            pass
        rebuilt.append({"field": field, "from": (cur[1] if cur else None), "to": spec["metric"]})
        print(f"[milvus_tool] 集合 {collection_name} 字段 {field} 索引重建: "
              f"{cur[1] if cur else '缺失'} -> {spec['metric']}")

    return rebuilt







