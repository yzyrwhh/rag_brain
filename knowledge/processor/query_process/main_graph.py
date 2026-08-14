from dotenv import load_dotenv
from langgraph.constants import END
from langgraph.graph import StateGraph

from knowledge.processor.query_process.nodes.answer_output__node import AnswerOutputNode
from knowledge.processor.query_process.nodes.item_name_confirm_node import ItemNameConfirmNode
from knowledge.processor.query_process.nodes.reranker_node import RerankNode
from knowledge.processor.query_process.nodes.rrf_node import RrfNode
from knowledge.processor.query_process.nodes.search_embedding_hyde_node import SearchEmbeddingHydeNode
from knowledge.processor.query_process.nodes.search_embedding_node import SearchEmbeddingNode
from knowledge.processor.query_process.nodes.search_web_node import WebSearchNode
from knowledge.processor.query_process.state import QueryGraphState

load_dotenv()

def router_item_name(state: QueryGraphState) ->bool :
    if state.get("answer"):
        return True
    return False

def  create_graph():
    graph = StateGraph(QueryGraphState)

    nodes = {
        "rerank": RerankNode(),
        "answer_output": AnswerOutputNode(),
        "item_name_confirm": ItemNameConfirmNode(),
        "multi_search": lambda x:x,
        "search_embedding_hyde": SearchEmbeddingHydeNode(),
        "search_embedding":SearchEmbeddingNode(),
        "websearch":WebSearchNode(),
        "join":lambda x:{},
        "rrf":RrfNode(),
    }

    for name, node in nodes.items():
        graph.add_node(name,node)

    graph.set_entry_point("item_name_confirm")

    graph.add_conditional_edges(
        "item_name_confirm",
        router_item_name,
        {
            False: "multi_search",
            True: "answer_output",
        }
    )

    graph.add_edge("multi_search", "search_embedding_hyde")
    graph.add_edge("multi_search", "search_embedding")
    graph.add_edge("multi_search", "websearch")

    graph.add_edge("websearch","join")
    graph.add_edge("search_embedding", "join")
    graph.add_edge("search_embedding_hyde", "join")

    graph.add_edge("join", "rrf")
    graph.add_edge("rrf", "rerank")
    graph.add_edge("rerank", "answer_output")
    graph.add_edge("answer_output", END)

    return graph.compile()
query_app = create_graph()






