from typing import List, Optional, Dict, Any, Tuple

from pymilvus import DataType
from langchain_core.messages import SystemMessage, HumanMessage

from knowledge.processor.import_process.base import BaseNode
from knowledge.processor.import_process.config import get_config
from knowledge.processor.import_process.exceptions import ValidationError, EmbeddingError
from knowledge.processor.import_process.state import ImportGraphState
from knowledge.utils.bge_client_util import get_bgem3_client
from knowledge.utils.llm_utils import get_llm_client
from knowledge.prompt.upload.import_prompt import ITEM_NAME_USER_PROMPT_TEMPLATE, ITEM_NAME_SYSTEM_PROMPT
from knowledge.utils.milvus_utils import get_milvus_client


class ItemNameRecognitionNode(BaseNode):
    name = "item_name_recognition"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        file_title, chunks, config = self._validate_inputs(state)

        item_name_context = self._prepare_item_name_context(chunks, config)

        item_name = self._recognition_item_name_by_llm(file_title, item_name_context)

        dense_vector, sparse_vector = self._embedding_item_name(item_name)

        self._save_to_milvus(file_title, item_name, dense_vector, sparse_vector, config)

        self._fill_item_name(item_name, state, chunks)

        return state



    def _validate_inputs(self, state: ImportGraphState):
        self.log_step("step1", "检验输入参数")

        config = get_config()
        file_title = state.get('file_title')
        chunks = state.get('chunks')

        if not file_title:
            raise ValidationError("文件标题为空", self.name)

        if not chunks or not isinstance(chunks, list):
            raise ValidationError("chunk为空或者无效", self.name)

        item_name_chunk_k = config.item_name_chunk_k
        if not item_name_chunk_k or item_name_chunk_k <= 0:
            raise ValidationError("item_name_chunk_k为空或者无效", self.name)

        self.logger.info(f"检测到文件：{file_title},对应的切片长度:{len(chunks)}")
        return file_title, chunks, config

    def _prepare_item_name_context(self, chunks: Optional[List[Dict[str, Any]]], config):
        self.log_step("step2", "构建商品名提取的上下文")

        result = []
        total = 0

        for index, chunk in enumerate(chunks[:config.item_name_chunk_k]):
            if not isinstance(chunk, dict):
                continue

            content = chunk.get('content')
            spices = f"【切片】- {index + 1} - {content}"

            total += len(spices)
            result.append(spices)

            if total > config.item_name_chunk_k:
                break

        return "\n\n".join(result)[:config.item_name_chunk_k]

    def _recognition_item_name_by_llm(self, file_title: str, item_name_context: str) -> str:
        self.log_step("step3", "LLM识别商品名")

        llm_client = get_llm_client()

        if llm_client is None:
            self.logger.error(f"LLM初始化失败,商品名安全回退到标题名：{file_title}")
            return file_title


        prompt = ITEM_NAME_USER_PROMPT_TEMPLATE.format(file_title=file_title, context=item_name_context)
        try:
            llm_response = llm_client.invoke([
                SystemMessage(content=ITEM_NAME_SYSTEM_PROMPT),
                HumanMessage(content=prompt)
            ])

            item_name = getattr(llm_response, 'content', '').strip()

            if not item_name or item_name.upper() == 'UNKNOWN':
                self.logger.warning(f"LLM无法提取有效的商品名,安全回退到标题名：{file_title}")
                return file_title
            self.logger.info(f"提取到的商品名:{item_name}")
            return item_name

        except Exception as e:
            self.logger.error(f"LLM调用失败,商品名安全回退到标题名：{file_title}")
            return file_title

    def _embedding_item_name(self, item_name: str) -> Optional[Tuple[list, dict]]:
        self.log_step("step4", "embedding模型嵌入商品名")

        try:
            embedding_model = get_bgem3_client()

            embedding_result = embedding_model.encode_documents([item_name])
            self.logger.info(f"✅ 商品名 '{item_name}' 嵌入完成")

            # 1. 提取稠密向量
            dense = embedding_result['dense'][0].tolist()

            # 2. 提取稀疏向量（现在是字典格式）
            sparse_data = embedding_result['sparse']  # List[Dict[int, float]]
            if sparse_data and len(sparse_data) > 0:
                sparse = sparse_data[0]  # {token_id: weight}
            else:
                sparse = {}

            self.logger.info(f"✅ 稠密维度: {len(dense)}, 稀疏非零项: {len(sparse)}")
            return dense, sparse

        except Exception as e:
            error_msg = f"嵌入商品名:'{item_name}'失败,原因是：{str(e)}"
            self.logger.error(error_msg)
            raise EmbeddingError(error_msg, self.name)

    def _save_to_milvus(self, file_title, item_name, dense_vector, sparse_vector, config):

        self.log_step("step5", "保存到向量数据库中")
        # 1. 参数检验
        if not dense_vector or not sparse_vector:
            self.logger.warning(f"[{item_name}] 向量生成不完整，跳过入库！")
            return

        # 2. 操作MilVus
        try:
            # 2.1 获取Milvus的客户端
            milvus_client = get_milvus_client()

            # 判断
            if milvus_client is None:
                return

            # 2.2 获取集合的名字
            collection_name = config.item_name_collection

            # 2.3 幂等性校验（不存在则创建新的）
            if not milvus_client.has_collection(collection_name=collection_name):
                self._create_item_name_collection(milvus_client, collection_name)

            # 2.4 构建字典结构数据
            data = {
                "file_title": file_title,  # 文件名字
                "item_name": item_name,  # 商品名字
                "dense_vector": dense_vector,  # 稠密向量 （list）
                "sparse_vector": sparse_vector  # 稀疏向量  (dict:{tokenId:weight})
            }

            # 2.5 插入数据到Milvus:{"insert_count":10,"ids":[10001,10002,10003]}
            result = milvus_client.insert(collection_name=collection_name, data=[data])
            self.logger.info(f"已成功保存到 Milvus，ID: {result['ids'][0]}")

        except Exception as e:
            self.logger.error(f"Milvus 数据库保存操作彻底失败: {e}")

    def _create_item_name_collection(self, client, collection_name):
        self.logger.info(f"正在创建集合: {collection_name}")

        schema = client.create_schema()

        schema.add_field(field_name="pk", datatype=DataType.VARCHAR, is_primary=True, auto_id=True, max_length=100)
        schema.add_field(field_name="file_title", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="item_name", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=1024)
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="dense_vector",
            index_name="dense_vector_index",
            index_type="AUTOINDEX",
            metric_type="COSINE"
        )
        index_params.add_index(
            field_name="sparse_vector",
            index_name="sparse_inverted_index",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="IP"
        )

        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params
        )
        self.logger.info(f"集合 {collection_name} 创建成功并构建了索引")

    def _fill_item_name(self, item_name: str, state: ImportGraphState, chunks: List[Dict[str, Any]]):
        self.log_step("step6", "回填商品名信息")
        for chunk in chunks:
            chunk['item_name'] = item_name  # 方便下游模型能有参考

        state['item_name'] = item_name

import json

if __name__ == '__main__':
    # 1. 读取chunk.json
    chunk_json_path = r"D:\folder\course\SGG\掌柜智库项目\资料\2-文档\markdown文档\6W100-整本手册\auto\chunks.json"
    with open(chunk_json_path, "r", encoding="utf-8") as f:
        chunk_content = json.load(f)
    # 2. 构建state
    state = {
        "file_title": "万用表的使用",
        "chunks": chunk_content
    }

    # 3. 实例化节点
    item_name_recognition_node = ItemNameRecognitionNode()

    # 4. 调用process
    result = item_name_recognition_node.process(state)

    # 5. 输出
    print(json.dumps(result, ensure_ascii=False, indent=4))

    """
      state = {
        "file_title": "万用表的使用",
        "chunks": chunk_content
    }

      state = {
        "file_title": "万用表的使用",
        "chunks": [{"item_name"},{"item_name"}],
        "item_name"
    }
    """


