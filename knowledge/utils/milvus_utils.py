import os

from dotenv import load_dotenv
from pymilvus import MilvusClient

load_dotenv()
def get_milvus_client():
    try:
        milvuscilent = MilvusClient(
            uri=os.getenv("MILVUS_URL"),
        )
        return milvuscilent
    except Exception as ex:
        raise ex