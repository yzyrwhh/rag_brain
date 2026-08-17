"""清理测试产生的脏数据：未完成文档 + 多余测试空间（保留最新一个）。

用法: python scripts/cleanup_test_data.py
"""
from pymongo import MongoClient

OWNER = "b9e941ab-6520-49bd-8a79-b4b91efd7890"  # smoke 测试用户


def main() -> None:
    db = MongoClient("mongodb://localhost:27017")["shopkeer"]

    # 1) 删除所有未完成（pending/failed）的文档
    removed = 0
    for d in db.knowledge_documents.find({"status": {"$ne": "completed"}}):
        print(f"删除未完成文档: {d['doc_id']} {d.get('title', '')}")
        db.knowledge_documents.delete_one({"_id": d["_id"]})
        removed += 1

    # 2) 保留最新一个测试空间，删除其余（连带其中的文档）
    spaces = list(db.knowledge_spaces.find({"owner_id": OWNER}).sort("created_at", -1))
    for s in spaces[1:]:
        n = db.knowledge_documents.delete_many({"space_id": s["space_id"]}).deleted_count
        db.knowledge_spaces.delete_one({"_id": s["_id"]})
        print(f"删除空间 {s['space_id']}（连带 {n} 个文档）")

    print(f"完成：删除未完成文档 {removed}，保留空间 {len(spaces[:1])} 个")


if __name__ == "__main__":
    main()
