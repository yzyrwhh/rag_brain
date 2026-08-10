from typing import Optional, List

from knowledge.processor.query_process.base import BaseNode, setup_logging
from knowledge.processor.query_process.config import get_config
from knowledge.processor.query_process.state import QueryGraphState
from knowledge.prompt.querry.hyde_prompt import HYDE_PROMPT_TEMPLATE
from knowledge.tools.embedding_tool import generate_hybrid_embeddings
from knowledge.tools.llm_tool import get_llm_client
from knowledge.tools.milvus_tool import build_hybrid_search_requests, execute_hybrid_search
from knowledge.utils.milvus_utils import get_milvus_client


class SearchEmbeddingHydeNode(BaseNode):
    name = "search_embedding_hyde"

    SEARCH_TOP_K = 10
    RERANK_TOP_K = 5
    RANKER_WEIGHTS = (0.5, 0.5)
    OUTPUT_FIELDS = ["chunk_id", "content", "item_name"]

    def process(self, state: QueryGraphState) -> QueryGraphState:

        query = state.get("rewritten_query") or state.get("original_query", "")
        if not query:
            self.logger.error("未找到用户查询")
            return {}

        item_names = state.get("item_names")

        try:
            # Step 1: 生成假设文档
            self.log_step("step_1", "生成假设性文档")
            hyde_doc = self._generate_hyde_doc(query)

            # Step 2-4: 拼接后向量化检索
            self.log_step("step_2", "执行混合搜索")
            chunks = self._search(query, hyde_doc, item_names)

            # Step 5: 返回结果
            self.log_step("step_3", f"搜索完成，返回 {len(chunks)} 条结果")
            return {"hyde_embedding_chunks": chunks, "hyde_doc": hyde_doc}
        except Exception as e:
            self.logger.error(f"HyDE 搜索失败: {e}")
            return {}





        pass

    def _generate_hyde_doc(self, query: str) -> str:
        """使用 LLM 根据用户查询生成假设性文档。"""

        llm = get_llm_client()
        prompt = HYDE_PROMPT_TEMPLATE.format(query=query)
        return llm.invoke(prompt).content

    def _search(
            self, query: str, hyde_doc: str,
            item_names: Optional[List[str]] = None,
    ) -> List:
        config = config = get_config()
        collection_name = config.chunks_collection

        # 拼接文本
        combined_text = f"{query} {hyde_doc}"

        # 向量化
        embeddings = generate_hybrid_embeddings([combined_text])

        # 构建搜索请求
        reqs = build_hybrid_search_requests(
            dense_vector=embeddings["dense"][0],
            sparse_vector=embeddings["sparse"][0],
            filter_expr=self._build_filter_expr(item_names),
            top_k=self.SEARCH_TOP_K,
        )

        res = execute_hybrid_search(
            client=get_milvus_client(),
            collection_name=collection_name,
            search_requests=reqs,
            ranker_weights=self.RANKER_WEIGHTS,
            top_k=self.RERANK_TOP_K,
            output_fields=self.OUTPUT_FIELDS,
        )

        return res[0] if res else []

    @staticmethod
    def _build_filter_expr(item_names: Optional[List[str]]) -> Optional[str]:
        """将商品名称列表转为 Milvus 过滤表达式。"""
        if not item_names:
            return None
        quoted = ", ".join(f'"{v}"' for v in item_names)
        return f"item_name in [{quoted}]"

_node_instance = SearchEmbeddingHydeNode()

def node_search_embedding_hyde(state: QueryGraphState) -> QueryGraphState:
        """兼容原有调用方式的入口函数。"""
        return _node_instance(state)

if __name__ == "__main__":
    import json
    from dotenv import load_dotenv

    # 1. 加载环境变量
    load_dotenv()
    setup_logging()

    print("=" * 60)
    print("HyDE 向量搜索节点测试")
    print("=" * 60)

    # 2. 构造测试状态
    test_state = {
        "session_id": "test_001",
        "rewritten_query": "如何使用万用表测量电压？",
        "original_query": "如何使用万用表测量电压？",
        "item_names": ["RS PRO RS-12 数字万用表"],
    }

    print("\n【输入状态】:")
    print(f"  rewritten_query: {test_state['rewritten_query']}")
    print(f"  item_names: {test_state['item_names']}")
    print("-" * 60)

    # 3. 执行节点
    result = node_search_embedding_hyde(test_state)

    # 4. 打印假设文档
    hyde_doc = result.get("hyde_doc", "")
    print("\n【LLM 生成的假设性文档】:")
    print(f"  {hyde_doc[:200]}...")
    print("-" * 60)

    # 5. 打印检索结果
    chunks = result.get("hyde_embedding_chunks", [])
    print(f"\n【检索结果】: 共 {len(chunks)} 条")
    print("-" * 60)

    for i, chunk in enumerate(chunks, 1):
        entity = chunk.get("entity", {})
        print(f"[{i}] 商品: {entity.get('item_name', '?')}")
        print(f"    ID: {entity.get('chunk_id', 'N/A')}")
        print(f"    分数: {chunk.get('distance', 0):.4f}")
        print(f"    内容: {entity.get('content', '')[:80]}...")
        print()




