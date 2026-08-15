from pymilvus import connections, Collection

connections.connect(
    alias="default",
    host="localhost",
    port="19530"
)

collection = Collection("kb_item_names_v2")

# 1. 释放集合（必须）
collection.release()
print("✅ 已释放集合")

# 2. 查看当前索引
print("\n=== 当前索引 ===")
for idx in collection.indexes:
    print(f"索引名: {idx.index_name}, 字段: {idx.field_name}, 参数: {idx.params}")

# 3. 按索引名删除（不影响数据）
collection.drop_index(index_name="dense_vector_index")  # ✅ 只删索引，数据保留
print("✅ 已删除 dense_vector 索引（数据保留）")

# 4. 用 IP 重建索引
dense_index_params = {
    "metric_type": "IP",
    "index_type": "AUTOINDEX",
}
collection.create_index(
    field_name="dense_vector",
    index_params=dense_index_params,
    index_name="dense_vector_index"
)
print("✅ dense_vector 索引已重建为 IP")

# 5. 重新加载
collection.load()
print("✅ 集合已重新加载")

# 6. 验证
print("\n=== 更新后的索引 ===")
for idx in collection.indexes:
    print(f"字段: {idx.field_name}, 参数: {idx.params}")

# 7. 确认数据还在
print(f"\n✅ 数据条数: {collection.num_entities}")