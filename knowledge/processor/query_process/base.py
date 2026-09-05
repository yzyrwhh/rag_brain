import logging
from abc import ABC, abstractmethod
from typing import TypeVar, Optional

from knowledge.front.utils.task_utils import (
    add_running_task,
    add_done_task,
    get_done_task_list,
    get_running_task_list,
    get_task_status,
)
from knowledge.front.utils.sse_tool import push_to_session, SSEEvent
from knowledge.processor.query_process.config import QueryConfig, get_config
from knowledge.processor.query_process.exceptions import QueryProcessError


T = TypeVar("T")

class BaseNode(ABC):
    name: str = "base_node"

    def __init__(self, config: Optional[QueryConfig] = None):

        self.config = config or get_config()
        self.logger = logging.getLogger(f"query.{self.name}")

    def _push_progress(self, task_id: str) -> None:
        """向 SSE 队列推送当前任务进度（若已创建队列）。"""
        try:
            push_to_session(
                task_id,
                SSEEvent.PROGRESS,
                {
                    "status": get_task_status(task_id),
                    "done_list": get_done_task_list(task_id),
                    "running_list": get_running_task_list(task_id),
                },
            )
        except Exception:  # noqa: BLE001 - 进度推送失败不应影响节点执行
            pass

    def __call__(self, state: T) -> T:
        """节点执行入口。

                LangGraph 调用节点时会调用此方法。
                提供统一的日志输出、任务追踪和异常处理。

                Args:
                    state: 图状态字典。

                Returns:
                    更新后的状态字典。

                Raises:
                    QueryProcessError: 节点执行失败时抛出。
                """
        self.logger.info(f"--- {self.name} 开始 ---")

        # 注册任务追踪
        task_id = state.get("task_id", "") if isinstance(state, dict) else ""

        if task_id:
            try:
                add_running_task(task_id, self.name)
                self._push_progress(task_id)
            except Exception as e:
                self.logger.warning(f"任务追踪注册失败: {e}")

        try:
            result = self.process(state)
            self.logger.info(f"--- {self.name} 完成 ---")

            # 标记任务完成
            if task_id:
                try:
                    add_done_task(task_id, self.name)
                    self._push_progress(task_id)
                except Exception as e:
                    self.logger.warning(f"任务完成标记失败: {e}")

            return result
        except QueryProcessError:
            # 已经是自定义异常，直接抛出
            raise
        except Exception as e:
            self.logger.error(f"{self.name} 执行失败: {e}")
            raise QueryProcessError(
                message=str(e),
                node_name=self.name,
                cause=e
            )

    @abstractmethod
    def process(self, state: T) -> T:

        pass

    def log_step(self, step_name: str, message: str = ""):

        log_msg = f"[{step_name}]"
        if message:
            log_msg += f" {message}"
        self.logger.info(log_msg)


def setup_logging(level: int = logging.INFO):
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )




