from typing import List, Dict, Any

from knowledge.utils.bge_client_util import get_bgem3_client


def generate_hybrid_embeddings(texts: List[str]) -> Dict[str, Any]:

    if not texts:
        return {"dense": [], "sparse": []}

    model = get_bgem3_client()
    result = model.encode_documents(texts)

    sparse_data = result['sparse']

    # 如果已经是列表（字典列表），直接使用
    if isinstance(sparse_data, list):
        final_sparse_vector = sparse_data
    # 如果是 csr_array，转换为字典列表
    elif hasattr(sparse_data, 'indptr'):
        final_sparse_vector = []
        csr = sparse_data
        for index in range(len(texts)):
            ind_ptr = csr.indptr
            start_ind = ind_ptr[index]
            end_ind = ind_ptr[index + 1]
            token_id = csr.indices[start_ind:end_ind].tolist()
            weight = csr.data[start_ind:end_ind].tolist()
            sparse_vector = dict(zip(token_id, weight))
            final_sparse_vector.append(sparse_vector)
    else:
        # 其他情况，当作空字典列表
        final_sparse_vector = [{} for _ in texts]

    return {
        "dense": [dense.tolist() for dense in result['dense']],
        "sparse": final_sparse_vector,
    }