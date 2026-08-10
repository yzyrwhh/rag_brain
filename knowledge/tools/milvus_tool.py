from typing import List, Dict, Tuple, Optional

from pymilvus import AnnSearchRequest, Collection, WeightedRanker


def build_hybrid_search_requests(
        dense_vector: List[float],
        sparse_vector: Dict[int, float],
        top_k: int = 5,
        dense_search_params={"metric_type": "IP"},
        sparse_search_params={"metric_type": "IP"},
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
        dense_search_params: 稠密检索参数，默认 {"metric_type": "IP", "params": {"nprobe": 10}}
        sparse_search_params: 稀疏检索参数，默认 {"metric_type": "IP"}
    Returns:
        AnnSearchRequest 列表 [dense_request, sparse_request]
    """
    dense_params = {
        "metric_type": "IP",
        "params": {"nprobe": 10},
        **(dense_search_params or {}),
    }
    sparse_params = {
        "metric_type": "IP",
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







