from typing import List, Dict, Tuple

from pymilvus import AnnSearchRequest, Collection, WeightedRanker


def build_hybrid_search_requests(
        dense_vector: List[float],
        sparse_vector: Dict[int, float],
        top_k: int = 5,
) -> List[AnnSearchRequest]:
    """
    构建混合检索请求

    Args:
        dense_vector: 稠密向量
        sparse_vector: 稀疏向量（字典格式 {token_id: weight}）
        top_k: 每个请求返回的候选数

    Returns:
        AnnSearchRequest 列表 [dense_request, sparse_request]
    """
    # 稠密向量搜索请求
    dense_request = AnnSearchRequest(
        data=[dense_vector],
        anns_field="dense_vector",
        param={"metric_type": "IP", "params": {"nprobe": 10}},
        limit=top_k,
    )

    # 稀疏向量搜索请求
    sparse_request = AnnSearchRequest(
        data=[sparse_vector],
        anns_field="sparse_vector",
        param={"metric_type": "IP"},
        limit=top_k,
    )

    return [dense_request, sparse_request]

def execute_hybrid_search(
    client,
    collection_name: str,
    search_requests: List[AnnSearchRequest],
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







