"""数据库初始化脚本（幂等）：Mongo 索引 / Milvus 集合 / Neo4j 约束。

对齐 docs/03 集合契约。运行：python scripts/init_db.py
"""
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

import pymongo  # noqa: E402
from pymilvus import DataType, MilvusClient  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402

from app.core.config import get_settings  # noqa: E402


# ---------------- Mongo ----------------
MONGO_COLLECTIONS: dict[str, list[tuple]] = {
    "users": [("username", {"unique": True}), ("email", {"unique": True, "sparse": True})],
    "sessions": [("user_id", {}), ("updated_at", {})],
    "messages": [("session_id", {}), ("user_id", {})],
    "tasks": [
        ("task_id", {"unique": True}),
        ("user_id", {}),
        ("status", {}),
    ],
    "task_events": [
        ("task_id", {}),
        ("seq", {}),
        ("task_id_seq", {"unique": True, "is_composite": True, "fields": ["task_id", "seq"]}),
    ],
    "knowledge_spaces": [("space_id", {"unique": True}), ("owner_id", {})],
    "space_members": [("space_id_user_id", {"unique": True, "is_composite": True, "fields": ["space_id", "user_id"]})],
    "knowledge_documents": [("doc_id", {"unique": True}), ("space_id", {}), ("user_id", {})],
    "document_texts": [("doc_id", {"unique": True}), ("space_id", {})],
    "memories": [("memory_id", {"unique": True}), ("user_id", {}), ("scene_name", {})],
    "scenes": [("scene_id", {"unique": True}), ("user_id", {})],
    "skills": [("skill_id_version", {"unique": True, "is_composite": True, "fields": ["skill_id", "version"]}), ("is_head", {})],
    "memory_generation_logs": [("memory_id", {"unique": True}), ("layer", {})],
    "memory_prompts": [("prompt_id", {"unique": True})],
    "knowledge_assets": [("asset_id", {"unique": True})],
    "integrations": [("user_id_provider", {"unique": True, "is_composite": True, "fields": ["user_id", "provider"]})],
    "feedback": [("task_id", {"unique": True}), ("user_id", {})],
    "audit_logs": [("user_id", {}), ("action", {})],
}


def init_mongo() -> None:
    s = get_settings()
    client = pymongo.MongoClient(s.mongo_url, serverSelectionTimeoutMS=3000)
    db = client[s.mongo_db]
    for coll, indexes in MONGO_COLLECTIONS.items():
        for name, opts in indexes:
            fields = opts.pop("fields", [name])
            is_comp = opts.pop("is_composite", False)
            key = [(f, 1) for f in fields]
            idx_name = name if is_comp else None
            db[coll].create_index(key, name=idx_name, **opts)
    print(f"[mongo] {len(MONGO_COLLECTIONS)} collections indexed on {s.mongo_db}")


# ---------------- Milvus（pymilvus 3.x 使用 MilvusClient API） ----------------
def init_milvus() -> None:
    s = get_settings()
    uri = s.milvus_url if s.milvus_url.startswith("http") else f"http://{s.milvus_url}"
    client = MilvusClient(uri=uri)

    def ensure(name: str, fields: list[dict], desc: str) -> None:
        if client.has_collection(name):
            print(f"[milvus] exists: {name}")
            return
        schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
        for f in fields:
            schema.add_field(**f)
        index_params = client.prepare_index_params()
        index_params.add_index(field_name="dense_vector", index_type="AUTOINDEX", metric_type="IP")
        client.create_collection(collection_name=name, schema=schema, index_params=index_params)
        client.load_collection(name)
        print(f"[milvus] created: {name} ({desc})")

    chunks_fields = [
        {"field_name": "pk", "datatype": DataType.INT64, "is_primary": True, "auto_id": True},
        {"field_name": "chunk_id", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "doc_id", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "space_id", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "user_id", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "domain", "datatype": DataType.VARCHAR, "max_length": 16},
        {"field_name": "visibility", "datatype": DataType.INT8},
        {"field_name": "chunk_index", "datatype": DataType.INT64},
        {"field_name": "text", "datatype": DataType.VARCHAR, "max_length": 65535},
        {"field_name": "dense_vector", "datatype": DataType.FLOAT_VECTOR, "dim": 1536},
    ]
    ensure(s.milvus_chunks_collection, chunks_fields, "统一知识切片 kb_chunks_v3，对齐 03 §4.1")

    memory_fields = [
        {"field_name": "pk", "datatype": DataType.INT64, "is_primary": True, "auto_id": True},
        {"field_name": "memory_id", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "user_id", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "layer", "datatype": DataType.VARCHAR, "max_length": 8},
        {"field_name": "type", "datatype": DataType.VARCHAR, "max_length": 32},
        {"field_name": "scene_name", "datatype": DataType.VARCHAR, "max_length": 128},
        {"field_name": "content", "datatype": DataType.VARCHAR, "max_length": 2000},
        {"field_name": "dense_vector", "datatype": DataType.FLOAT_VECTOR, "dim": 1536},
        {"field_name": "importance", "datatype": DataType.INT8},
        {"field_name": "trust", "datatype": DataType.FLOAT},
        {"field_name": "status", "datatype": DataType.INT8},
    ]
    ensure(s.milvus_memory_collection, memory_fields, "记忆向量 memory_vectors，对齐 03 §4.2")

    print(f"[milvus] ensured {s.milvus_chunks_collection} / {s.milvus_memory_collection}")


# ---------------- Neo4j ----------------
def init_neo4j() -> None:
    s = get_settings()
    driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    with driver.session() as session:
        for stmt in [
            "CREATE CONSTRAINT entity_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE",
            "CREATE CONSTRAINT doc_unique IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
            "CREATE INDEX entity_name_idx IF NOT EXISTS FOR (e:Entity) ON (e.name)",
        ]:
            session.run(stmt)
    driver.close()
    print("[neo4j] constraints/indexes ensured")


if __name__ == "__main__":
    # 各存储独立初始化，单个失败不阻断其余
    steps = [
        ("mongo", init_mongo),
        ("milvus", init_milvus),
    ]
    if get_settings().neo4j_enabled:
        steps.append(("neo4j", init_neo4j))
    else:
        print("[neo4j] 已跳过（NEO4J_ENABLED=false，Route A：图谱验证后启用；届时起 neo4j 容器并置 true 后重跑）")

    failed = []
    for name, fn in steps:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"[{name}] 初始化失败（可稍后重跑）: {type(exc).__name__}: {exc}")
    if failed:
        print(f"init_db 部分失败: {failed}（不影响其余存储）")
    else:
        print("init_db done: 全部完成")
