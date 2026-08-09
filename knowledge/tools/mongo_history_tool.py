import os
from datetime import datetime
from typing import List, Dict

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient
from transformers.utils.hub import SESSION_ID

load_dotenv()

class MongoUtil:
    def __init__(self):
        self.client = MongoClient(os.getenv("MONGO_URI"))
        self.db = self.client[os.getenv("MONGO_DB_NAME")]
        self.collection = self.db["chat_message"]

def get_mongo_client() -> MongoUtil:
        return MongoUtil()




def get_recent_message(session_id: str, limit: int = 10) -> List[Dict]:
    # 获取MongoUtil对象
    mongo_client = get_mongo_client()
    # 构建查询条件
    query = {"session_id": session_id}
    # 执行查询
    cursor = mongo_client.collection.find({"session_id": session_id}).sort("ts", -1).limit(limit)

    message = list(cursor)
    return message

def save_chat_message(session_id: str,
                      role:str,
                      text:str,
                      item_names: List[str] = None,
                      rewritten_query: str = "",
                      message_id: str=None) -> str:

    mongo_client = get_mongo_client()

    ts = datetime.now().timestamp()

    data = {
        "session_id": session_id,
       " role": role,
        "text": text,
        "rewritten_query": rewritten_query,
        "item_names": item_names,
        "message_id": message_id,
        "ts": ts,
    }

    # 前置已拿到 mongo_client、入参 message_id、data
    if message_id:
        # 根据message_id更新指定单条消息文档
        mongo_client.collection.update_one(
            filter={"_id": ObjectId(message_id)},
            update={"$set": data},
        )
        return message_id
    else:
        # 无ID则新增一条消息记录
        result = mongo_client.collection.insert_one(data)
        return str(result.inserted_id)

def clear_chat_message(session_id: str):
    mongo_client = get_mongo_client()
    result = mongo_client.collection.delete_any({"session_id": session_id})
    return str(result.deleted_count)


def update_message_item_names(message_ids: List[str], item_names: List[str]):
    """批量更新消息的商品名称"""
    if not message_ids:
        return

    mongo_client = get_mongo_client()
    # 将字符串ID转换为ObjectId
    object_ids = [ObjectId(msg_id) for msg_id in message_ids]

    mongo_client.collection.update_many(
        filter={"_id": {"$in": object_ids}},
        update={"$set": {"item_names": item_names}}
    )















"""
from pymongo import MongoClient
client = MongoClient('mongodb://localhost:27017/')  # 连接MongoDB
db = client['database_name']  # 选择数据库
collection = db['collection_name']  # 选择集合

collection.insert_one({"name": "张三", "age": 20})  # 插入一条文档
collection.insert_many([{"name": "李四"}, {"name": "王五"}])  # 插入多条文档
collection.find()  # 查询所有文档（返回游标）
collection.find_one()  # 查询第一条文档
collection.find({"age": {"$gt": 18}})  # 条件查询（大于18岁）
collection.find().limit(5)  # 限制返回5条
collection.find().sort("age", -1)  # 排序（-1降序，1升序）
list(collection.find())  # 将游标转换为列表
db.list_collection_names()  # 查看所有集合名称
db.list_collections()  # 查看所有集合详细信息
db.command('collstats', 'collection_name')  # 查看集合状态
collection.count_documents({})  # 统计文档总数
collection.count_documents({"age": {"$gt": 18}})  # 条件统计
collection.update_one({"name": "张三"}, {"$set": {"age": 21}})  # 更新一条文档
collection.update_many({"age": {"$lt": 20}}, {"$set": {"status": "young"}})  # 更新多条文档
collection.delete_one({"name": "张三"})  # 删除一条文档
collection.delete_many({"age": {"$gt": 25}})  # 删除多条文档
collection.delete_many({})  # 删除所有文档
collection.drop()  # 删除整个集合
for doc in collection.find(): print(doc)  # 遍历游标打印文档
collection.find_one() is not None  # 检查集合是否有数据
"""
