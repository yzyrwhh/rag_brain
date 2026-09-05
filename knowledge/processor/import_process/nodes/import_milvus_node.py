import json
import os
from typing import List, Dict

from pymilvus import DataType

from knowledge.processor.import_process.base import BaseNode, setup_logging
from knowledge.processor.import_process.config import get_config
from knowledge.processor.import_process.exceptions import MilvusError
from knowledge.processor.import_process.state import ImportGraphState
from knowledge.utils.milvus_utils import get_milvus_client


class ImportMilvusNode(BaseNode):
    name = "import_milvus"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        config = get_config()
        chunks = state.get("chunks", [])

        if not chunks:
            self.logger.warning("chunks 为空，跳过导入")
            return state

        vector_dim = self._get_vector_dim(chunks)
        self.log_step("step_1", f"准备导入 {len(chunks)} 条数据，向量维度: {vector_dim}")

        try:
            client = get_milvus_client()
            collection_name = config.chunks_collection

            # 3. 创建集合（如不存在）
            if not client.has_collection(collection_name=collection_name):
                self.log_step("step_2", f"创建集合: {collection_name}")
                self._create_collection(client, collection_name, vector_dim)


            self.log_step("step_3", "执行插入")
            self._insert_and_backfill_ids(client, collection_name, chunks)

        except MilvusError:
            raise
        except Exception as e:
            raise MilvusError(f"Milvus 操作失败: {e}", node_name=self.name, cause=e)

        return state





    @staticmethod
    def _get_vector_dim(chunks: List[Dict]) -> int:

        dim = len(chunks[0].get("dense_vector", []))
        if dim == 0:
            raise MilvusError("切片数据不包含 dense_vector", node_name="import_milvus")
        return dim

    def _create_collection(self, client, collection_name: str, vector_dim: int):
        schema = self._build_schema(client, vector_dim)
        index_params = self._build_index_params(client)

        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )

        self.logger.info(f"集合 {collection_name} 创建成功")

    def _build_schema(self, client, vector_dim: int):
        schema = client.create_schema(enable_dynamic_fields=True)

        schema.add_field(field_name="chunk_id",datatype=DataType.INT64,is_primary=True,auto_id=True)

        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="parent_title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="part", datatype=DataType.INT8)
        schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=65535)

        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=vector_dim)

        return schema

    def _build_index_params(self, client):
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_name="dense_vector_index",
            index_type="AUTOINDEX",
            metric_type="IP",
        )
        index_params.add_index(
            field_name="sparse_vector",
            index_name="sparse_inverted_index",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="IP",
            params={"inverted_index_algo": "DAAT_MAXSCORE"},
        )
        return index_params

    def _insert_and_backfill_ids(
            self,
            client,
            collection_name: str,
            chunks: List[Dict],
    ):

        result = client.insert(collection_name=collection_name, data=chunks)
        insert_count = result.get("insert_count", 0)
        self.logger.info(f"成功插入 {insert_count} 条数据")

        inserted_ids = result.get("ids", [])
        if inserted_ids and len(inserted_ids) == len(chunks):
            for chunk, chunk_id in zip(chunks, inserted_ids):
                chunk["chunk_id"] = str(chunk_id)

        inserted_ids = result.get("ids", [])

        if inserted_ids and len(inserted_ids) == len(chunks):
            for chunk, chunk_id in zip(chunks, inserted_ids):
                chunk["chunk_id"] = str(chunk_id)
        else:
            self.logger.warning(
                f"回填 chunk_id 失败: 返回 {len(inserted_ids)} 个 ID，"
                f"期望 {len(chunks)} 个"
            )

import_milvus_node = ImportMilvusNode()

if __name__ == "__main__":
    setup_logging()
    temp_dir = r"examples/out"

    input_path = os.path.join(temp_dir, "chunks_item_name_vector.json")
    output_path = os.path.join(temp_dir, "chunks_item_name_vector_ids.json")

    print(f"正在读取输入文件: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        content = json.load(f)

    chunks = content.get('chunks', [])
    print(f"读取到 {len(chunks)} 个切片")

    state = {
        "chunks": chunks
    }

    print("\n开始执行 Milvus 导入...")
    result_state = import_milvus_node.process(state)

    output_chunks = result_state.get("chunks", [])
    print(f"\n处理完成，共 {len(output_chunks)} 个切片")

    # 检查 chunk_id 回填情况
    chunks_with_id = sum(1 for c in output_chunks if c.get("chunk_id"))
    chunks_without_id = len(output_chunks) - chunks_with_id

    print(f"\n回填统计:")
    print(f"  - 成功回填 chunk_id: {chunks_with_id} 个")
    print(f"  - 未回填 chunk_id: {chunks_without_id} 个")

    print("\n前 3 个切片信息:")
    for i, chunk in enumerate(output_chunks[:3]):
        print(f"\n  切片 {i + 1}:")
        print(f"    chunk_id: {chunk.get('chunk_id', '无')}")
        print(f"    title: {chunk.get('title', '')}")
        print(f"    item_name: {chunk.get('item_name', '')}")
        print(f"    content: {chunk.get('content', '')[:50]}...")

    # ----------------------------------------------------------------
    # Step 5: 保存输出文件
    # ----------------------------------------------------------------
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_state, f, ensure_ascii=False, indent=4)

    print(f"\n已保存到: {output_path}")


