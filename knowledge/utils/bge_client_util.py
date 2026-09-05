import os
import threading
from dotenv import load_dotenv
from FlagEmbedding import BGEM3FlagModel

load_dotenv()

# 全局单例缓存
_bgem3_client_cache = None
_bgem3_lock = threading.RLock()  # 必须是 RLock！warmup_bgem3 和 get_bgem3_client 在同一个线程嵌套拿锁
_warmup_done = False


def get_bgem3_client():
    """获取 BGE-M3 客户端（单例缓存，首次调用加载 ~12s，后续复用）。
    
    线程安全：多个线程同时调用不会重复加载模型。
    """
    global _bgem3_client_cache
    if _bgem3_client_cache is None:
        with _bgem3_lock:
            # double-check
            if _bgem3_client_cache is None:
                try:
                    model_path = os.getenv("BGE_M3_PATH", os.getenv("BGE_M3", "BAAI/bge-m3"))
                    device = os.getenv("BGE_DEVICE", "cpu")
                    model = BGEM3FlagModel(model_path, device=device, use_fp16=False)
                    _bgem3_client_cache = _Wrapper(model)
                except Exception as ex:
                    print(f"❌ BGE-M3 加载失败: {ex}")
                    raise
    return _bgem3_client_cache


class _Wrapper:
    """BGE-M3 模型包装器，保持接口一致。"""
    def __init__(self, model):
        self.model = model

    def encode_documents(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        result = self.model.encode(texts, return_dense=True, return_sparse=True, return_colbert_vecs=False)
        return {
            'dense': result['dense_vecs'],
            'sparse': result['lexical_weights'],
        }

    def encode_queries(self, texts):
        return self.encode_documents(texts)


def warmup_bgem3():
    """预热 BGE-M3 模型（后台线程调用，不阻塞主进程）。
    
    调用后模型常驻内存，后续查询不再有 12s 加载延迟。
    幂等、线程安全：多次调用只加载一次。
    """
    global _warmup_done
    if _warmup_done:
        return
    with _bgem3_lock:
        if _warmup_done:
            return
        try:
            print("[warmup] BGE-M3 预热开始...")
            client = get_bgem3_client()
            # 编一个空字符串验证模型就绪
            client.encode_documents(["warmup"])
            _warmup_done = True
            print("[warmup] BGE-M3 预热完成")
        except Exception as ex:
            print(f"[warmup] BGE-M3 预热失败（不影响运行，首次查询时会重试）: {ex}")


# 别名（可选）
get_bge_m3_model = get_bgem3_client
get_beg_m3_embedding_model = get_bgem3_client