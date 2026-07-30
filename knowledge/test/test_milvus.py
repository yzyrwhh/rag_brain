# clean_all.py
from pymilvus import connections, utility

connections.connect(host="localhost", port="19530")

# 要保留的集合（系统或重要数据）
keep_collections = []  # 如果你想保留某些集合，写在这里

collections = utility.list_collections()
print(f"当前集合: {collections}")

for col in collections:
    if col not in keep_collections:
        utility.drop_collection(col)
        print(f"✅ 已删除: {col}")

print(f"剩余集合: {utility.list_collections()}")