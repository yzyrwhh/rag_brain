import hashlib
import os
from datetime import datetime
from typing import Optional, Dict

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()


def compute_file_md5(file_path: str, chunk_size: int = 1024 * 1024) -> str:
    """计算文件 MD5（分块读取，避免大文件内存溢出）。"""
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            md5.update(block)
    return md5.hexdigest()


class FileRegistry:
    """文件登记表：记录已成功导入文件的 MD5，用于去重。"""

    def __init__(self):
        mongo_uri = os.getenv("MONGO_URL") or os.getenv("MONGO_URI") or "mongodb://localhost:27017"
        db_name = os.getenv("MONGO_DB_NAME") or "knowledge"
        self.client = MongoClient(mongo_uri)
        self.collection = self.client[db_name]["file_registry"]
        self._ensure_index()

    def _ensure_index(self):
        try:
            self.collection.create_index("file_md5", unique=True)
        except Exception:
            pass

    def find_by_md5(self, file_md5: str) -> Optional[Dict]:
        return self.collection.find_one({"file_md5": file_md5})

    def register(self, file_md5: str, file_title: str, task_id: str = "") -> bool:
        """登记成功导入的文件。MD5 重复时返回 False（不覆盖旧记录）。"""
        try:
            self.collection.insert_one({
                "file_md5": file_md5,
                "file_title": file_title,
                "task_id": task_id,
                "imported_at": datetime.now().isoformat(),
            })
            return True
        except Exception:
            return False


def get_file_registry() -> FileRegistry:
    return FileRegistry()
