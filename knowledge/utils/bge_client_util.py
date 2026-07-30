import os
from dotenv import load_dotenv
from FlagEmbedding import BGEM3FlagModel

load_dotenv()


def get_bgem3_client():
    try:
        model_path = os.getenv("BGE_M3_PATH", os.getenv("BGE_M3", "BAAI/bge-m3"))
        device = os.getenv("BGE_DEVICE", "cpu")

        model = BGEM3FlagModel(model_path, device=device, use_fp16=False)

        # 简单的包装，保持接口一致
        class Wrapper:
            def __init__(self, model):
                self.model = model

            def encode_documents(self, texts):
                if isinstance(texts, str):
                    texts = [texts]
                result = self.model.encode(texts, return_dense=True, return_sparse=True, return_colbert_vecs=False)
                return {
                    'dense': result['dense_vecs'],
                    'sparse': result['lexical_weights']  # 直接返回字典列表
                }

            def encode_queries(self, texts):
                return self.encode_documents(texts)

        return Wrapper(model)

    except Exception as ex:
        print(f"❌ 加载失败: {ex}")
        raise ex


# 别名（可选）
get_bge_m3_model = get_bgem3_client
get_beg_m3_embedding_model = get_bgem3_client