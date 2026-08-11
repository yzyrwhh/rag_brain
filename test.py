from modelscope import snapshot_download

str = snapshot_download(model_id="BAAI/bge-reranker-large",local_dir="D:\software\BAAI_bge-reranker_large")

print(str)