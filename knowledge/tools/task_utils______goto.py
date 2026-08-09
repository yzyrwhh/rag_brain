# knowledge/tools/task_utils______goto.py

"""任务追踪工具模块
提供查询流程中节点的运行状态追踪功能，支持：
- 运行中节点列表管理
- 已完成节点列表管理
- 任务状态管理（处理中/已完成/失败）
- 节点名称中英文映射
"""

from collections import defaultdict
from typing import Dict, List, Optional

# ==================== 全局状态存储 ====================

_tasks_running_list: Dict[str, List[str]] = defaultdict(list)
"""存储每个任务当前正在运行的节点列表。"""

_tasks_done_list: Dict[str, List[str]] = defaultdict(list)
"""存储每个任务已完成的节点列表。"""

_tasks_status: Dict[str, str] = {}
"""存储每个任务的整体状态。"""

# ==================== 任务状态常量 ====================

TASK_STATUS_PROCESSING = "processing"
"""任务处理中。"""

TASK_STATUS_COMPLETED = "completed"
"""任务已完成。"""

TASK_STATUS_FAILED = "failed"
"""任务失败。"""

# ==================== 节点名称映射 ====================

_NODE_NAME_TO_CN: Dict[str, str] = {
    # ===== 导入流程节点（kb/import_process/main_graph.py）=====
    "upload_file": "上传文件",
    "entry_node": "文件类型检测",
    "pdf_to_md": "PDF转Markdown",
    "md_img_node": "Markdown图片处理",
    "document_split_node": "文档切分",
    "item_name_rec_node": "商品名识别",
    "bge_embedding_node": "切片内容向量化",
    "import_milvus_node": "导入向量数据库",
    "__end__": "处理完成",

    # ===== 查询流程节点（kb/query_process/main_graph.py）=====
    "item_name_confirm_node": "确认问题产品",
    "item_name_confirm": "确认问题产品",
    "answer_output_node": "生成答案",
    "answer_output": "生成答案",
    "rerank_node": "重排序",
    "rerank": "重排序",
    "rrf_node": "倒排融合",
    "rrf": "倒排融合",
    "mcp_search_node": "网络搜索",
    "web_search_mcp": "网络搜索",
    "vector_search_node": "切片搜索",
    "search_embedding": "切片搜索",
    "hyde_search_node": "切片搜索(假设性文档)",
    "search_embedding_hyde": "切片搜索(假设性文档)",
    "kg_search_node": "查询知识图谱",
    "query_kg": "查询知识图谱",
    "multi_search": "多路搜索分发",
    "join": "结果汇合",

    # ===== 通用/兼容 =====
    "base_node": "基础节点",
}


def _to_cn(node_name: str) -> str:
    """将节点英文名转换为中文展示名。

    Args:
        node_name: 节点的英文名称。

    Returns:
        节点的中文名称，如果未配置映射则返回原名称。
    """
    return _NODE_NAME_TO_CN.get(node_name, node_name)


# ==================== 核心 API ====================

def add_running_task(task_id: str, node_name: str, is_stream: bool = False) -> None:
    """将节点添加到任务的运行列表中。

    用于在节点开始执行时标记该节点正在运行。

    Args:
        task_id: 任务 ID（通常为 session_id）。
        node_name: 节点名称。
        is_stream: 是否启用流式输出（当前版本暂未使用，预留扩展）。
    """

    # 获取当前任务的运行节点列表
    running = _tasks_running_list[task_id]

    # 将当前节点加入运行列表（去重）
    if node_name not in running:
        running.append(node_name)


def add_done_task(task_id: str, node_name: str, is_stream: bool = False) -> None:
    """将节点添加到任务的已完成列表中。

    用于在节点执行完成时标记该节点已完成。

    Args:
        task_id: 任务 ID（通常为 session_id）。
        node_name: 节点名称。
        is_stream: 是否启用流式输出（当前版本暂未使用，预留扩展）。
    """
    # 如果该节点还在运行列表中，则将其移出
    if node_name in _tasks_running_list[task_id]:
        _tasks_running_list[task_id].remove(node_name)

    # 获取当前任务的已完成节点列表
    done = _tasks_done_list[task_id]

    # 将当前节点加入已完成列表（去重）
    if node_name not in done:
        done.append(node_name)


def get_running_task_list(task_id: str) -> List[str]:
    """获取任务当前运行中的节点列表（中文名称）。

    Args:
        task_id: 任务 ID（通常为 session_id）。

    Returns:
        运行中的节点中文名称列表。


    """
    return [_to_cn(n) for n in _tasks_running_list.get(task_id, [])]


def get_done_task_list(task_id: str) -> List[str]:
    """获取任务已完成的节点列表（中文名称）。

    Args:
        task_id: 任务 ID（通常为 session_id）。

    Returns:
        已完成的节点中文名称列表。
        ['确认问题产品', '切片搜索', '查询知识图谱']
    """
    return [_to_cn(n) for n in _tasks_done_list.get(task_id, [])]


def get_all_task_nodes(task_id: str) -> Dict[str, List[str]]:
    """获取任务的所有节点状态（运行中 + 已完成）。

    Args:
        task_id: 任务 ID（通常为 session_id）。

    Returns:
        包含 'running' 和 'done' 两个键的字典。


    """
    return {
        "running": get_running_task_list(task_id),
        "done": get_done_task_list(task_id),
    }


def clear_task(task_id: str) -> None:
    """清除指定任务的所有追踪数据。

    在任务完成或取消时调用，清理内存。

    Args:
        task_id: 任务 ID（通常为 session_id）。

    Examples:
        >>> clear_task("session_001")
    """
    if task_id in _tasks_running_list:
        del _tasks_running_list[task_id]
    if task_id in _tasks_done_list:
        del _tasks_done_list[task_id]
    if task_id in _tasks_status:
        del _tasks_status[task_id]


# ==================== 任务状态管理 ====================

def update_task_status(task_id: str, status: str) -> None:
    """更新任务的整体状态。

    Args:
        task_id: 任务 ID（通常为 session_id）。
        status: 任务状态，必须是 TASK_STATUS_* 常量之一。

    Raises:
        ValueError: 当状态值不合法时抛出。

    Examples:
        >>> update_task_status("session_001", TASK_STATUS_PROCESSING)
        >>> get_task_status("session_001")
        'processing'
    """
    valid_statuses = [TASK_STATUS_PROCESSING, TASK_STATUS_COMPLETED, TASK_STATUS_FAILED]
    if status not in valid_statuses:
        raise ValueError(f"无效的任务状态: {status}，有效状态为: {valid_statuses}")

    _tasks_status[task_id] = status


def get_task_status(task_id: str) -> Optional[str]:
    """获取任务的整体状态。

    Args:
        task_id: 任务 ID（通常为 session_id）。

    Returns:
        任务状态字符串，如果任务不存在则返回 None。

    Examples:
        >>> get_task_status("session_001")
        'processing'
    """
    return _tasks_status.get(task_id)


def is_task_completed(task_id: str) -> bool:
    """检查任务是否已完成。

    Args:
        task_id: 任务 ID（通常为 session_id）。

    Returns:
        如果任务状态为 TASK_STATUS_COMPLETED 则返回 True，否则返回 False。
    """
    return get_task_status(task_id) == TASK_STATUS_COMPLETED


def is_task_processing(task_id: str) -> bool:
    """检查任务是否正在处理中。

    Args:
        task_id: 任务 ID（通常为 session_id）。

    Returns:
        如果任务状态为 TASK_STATUS_PROCESSING 则返回 True，否则返回 False。
    """
    return get_task_status(task_id) == TASK_STATUS_PROCESSING


def is_task_failed(task_id: str) -> bool:
    """检查任务是否已失败。

    Args:
        task_id: 任务 ID（通常为 session_id）。

    Returns:
        如果任务状态为 TASK_STATUS_FAILED 则返回 True，否则返回 False。
    """
    return get_task_status(task_id) == TASK_STATUS_FAILED


# ==================== 便捷工具 ====================

def reset_all_tasks() -> None:
    """重置所有任务追踪数据（主要用于测试）。

    Warning:
        此方法会清除所有任务数据，请谨慎使用。
    """
    _tasks_running_list.clear()
    _tasks_done_list.clear()
    _tasks_status.clear()


def get_task_summary(task_id: str) -> Dict[str, any]:
    """获取任务的完整摘要信息。

    Args:
        task_id: 任务 ID（通常为 session_id）。

    Returns:
        包含任务所有信息的字典。

    Examples:
        >>> get_task_summary("session_001")
        {
            'task_id': 'session_001',
            'status': 'processing',
            'running': ['多路搜索分发'],
            'done': ['确认问题产品', '切片搜索'],
            'running_count': 1,
            'done_count': 2,
            'total_count': 3,
        }
    """
    running = get_running_task_list(task_id)
    done = get_done_task_list(task_id)

    return {
        "task_id": task_id,
        "status": get_task_status(task_id),
        "running": running,
        "done": done,
        "running_count": len(running),
        "done_count": len(done),
        "total_count": len(running) + len(done),
    }


# ==================== 兼容旧版 API ====================

# 为兼容旧代码保留的别名
add_running_task._is_stream_supported = True
add_done_task._is_stream_supported = True