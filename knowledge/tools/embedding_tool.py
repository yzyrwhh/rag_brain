from typing import List, Dict, Any

from knowledge.utils.bge_client_util import get_bgem3_client


def generate_hybrid_embeddings(texts: List[str]) -> Dict[str, Any]:

    if not texts:
        return {"dense": [], "sparse": []}

    model = get_bgem3_client()
    result = model.encode_documents(texts)

    return {
        "dense": result["dense"],
        "sparse": result["sparse"]
    }