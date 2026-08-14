import uuid
from typing import List, Dict, Any

from knowledge.front.utils.task_utils import update_task_status, TASK_STATUS_PROCESSING, get_task_result
from knowledge.processor.query_process.main_graph import query_app
from knowledge.tools.mongo_history_tool import get_recent_message, clear_chat_message
from knowledge.front.utils.sse_tool import create_sse_queue


class QueryService:

    def generate_session_id(self):
        return str(uuid.uuid4())
    def generate_task_id(self) -> str:
        return str(uuid.uuid4())

    def submit_query(self, task_id:str,is_stream:bool):
        update_task_status(task_id,TASK_STATUS_PROCESSING)
        if is_stream:
            create_sse_queue(task_id)

    def run_query_graph(self,task_id:str,session_id:str,user_query:str,is_stream:bool):
        default_state = {
            "original_query": user_query,
            "session_id": session_id,
            "task_id": task_id,
            "is_stream": is_stream,
        }

        query_app.invoke(default_state)

    def get_answer(self, task_id: str) -> str:
        return get_task_result(task_id, "answer", "")

    def get_history(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:

            records = get_recent_message(session_id, limit=limit)
            return [
                {
                    "_id": str(r.get("_id", "")),
                    "session_id": r.get("session_id", ""),
                    "role": r.get("role", ""),
                    "text": r.get("text", ""),
                    "rewritten_query": r.get("rewritten_query", ""),
                    "item_names": r.get("item_names", []),
                    "ts": r.get("ts"),
                }
                for r in records
            ]

    def clear_history(self, session_id: str) -> int:
        return clear_chat_message(session_id)