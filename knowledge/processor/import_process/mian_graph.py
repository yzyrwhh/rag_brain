from langgraph.constants import END
from langgraph.graph import StateGraph

from knowledge.service.task_service import TaskService
from knowledge.processor.import_process.base import setup_logging
from knowledge.processor.import_process.nodes.bge_embedding_node import BgeEmbeddingNode
from knowledge.processor.import_process.nodes.md_img import MdImgNode
from knowledge.processor.import_process.nodes.document_split_node import DocumentSplitNode
from knowledge.processor.import_process.nodes.entry_node import EntryNode
from knowledge.processor.import_process.nodes.import_milvus_node import ImportMilvusNode
from knowledge.processor.import_process.nodes.item_name_recognition import ItemNameRecognitionNode
from knowledge.processor.import_process.nodes.pdf_md_node import PdfToMdNode
from knowledge.processor.import_process.state import ImportGraphState


#创建graph对象
#添加节点、添加边，graph对象编译
#返回编译后的graph对象
def  create_graph():
    graph = StateGraph(ImportGraphState)

    nodes = {
        "entry_node": EntryNode(),
        "document_split": DocumentSplitNode(),
        "md_img": MdImgNode(),
        "pdf_to_md": PdfToMdNode(),
        "item_name_recognition": ItemNameRecognitionNode(),
        "import_milvus": ImportMilvusNode(),
        "bge_embedding": BgeEmbeddingNode()
    }
    for name, node in nodes.items():
        graph.add_node(name,node)

    graph.set_entry_point('entry_node')

    graph.add_conditional_edges(
        "entry_node",
        import_router,
        {
        "pdf":"pdf_to_md",
        "md":"md_img",
        END:END
        }
    )

    graph.add_edge("entry_node", "pdf_to_md") #条件边优先级更高
    graph.add_edge("pdf_to_md", "md_img")
    graph.add_edge("md_img", "document_split")
    graph.add_edge("document_split", "item_name_recognition")
    graph.add_edge("item_name_recognition", "bge_embedding")
    graph.add_edge("bge_embedding", "import_milvus")
    graph.add_edge("import_milvus", END)

    graph_compile = graph.compile()

    return graph_compile

#条件边路由方法
def import_router(state: ImportGraphState) -> ImportGraphState:
    if state.get("is_pdf_read_enabled"):
        return "pdf"
    if state.get("is_md_read_enabled"):
        return "md"
    return END

#获取上一个方法编译graph对象，执行
#invoke 或者 stream
def run_graph_import(task_id,impotd_file_path,file_dir):
    state = {
        "task_id":task_id,
        "import_file_path":impotd_file_path,
        "file_dir":file_dir
    }

    final_state = None
    graph = create_graph()
    ts = TaskService()

    for event in graph.stream(state):
        for node_name,state_data in event.items():
            print(f"运行节点：{node_name} ， 传输数据：{state_data}")
            ts.mark_node_done(task_id,node_name)

            final_state = state_data
    return final_state


if __name__ == '__main__':
    setup_logging()
    import_file_path = r"D:\folder\course\SGG\掌柜智库项目\资料\2-文档\pdf文档\doc\6W100-整本手册.pdf"
    file_dir = r"D:\folder\course\SGG\掌柜智库项目\资料\2-文档\test"

    final_res = run_graph_import(
        task_id=1,
        impotd_file_path=import_file_path,
        file_dir=file_dir
    )

    print(final_res)


