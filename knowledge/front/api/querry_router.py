import asyncio
import os
import uuid

import uvicorn
from readline import clear_history


from fastapi import FastAPI, BackgroundTasks,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse, FileResponse

from knowledge.front.schema.QueryRequest import QueryRequest
from knowledge.front.utils.paths import get_front_page_dir
from knowledge.front.utils.task_utils import update_task_status, TASK_STATUS_COMPLETED, TASK_STATUS_PROCESSING, \
    get_task_result
from knowledge.processor.query_process.main_graph import query_app
from knowledge.tools.mongo_history_tool import get_recent_message
from knowledge.front.utils.sse_tool import sse_generator, create_sse_queue


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="Query Service",
        description="知识库查询服务"
    )

    # 允许跨域（开发环境）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],      # 允许所有来源
        allow_credentials=True,   # 允许携带凭证
        allow_methods=["*"],      # 允许所有方法
        allow_headers=["*"],      # 允许所有头部
    )

    # 静态文件挂载（前端页面）
    page_dir = get_front_page_dir()
    if os.path.exists(page_dir):
        app.mount("/front", StaticFiles(directory=page_dir), name="front")

    # 注册路由
    _register_routes(app)

    return app



def _register_routes(app: FastAPI):
    """注册路由"""

    @app.get("/chat.html")
    async def chat_page():
        return FileResponse(os.path.join(get_front_page_dir(), "chat.html"))

    @app.post("/query")
    async def query(request: QueryRequest, background_tasks: BackgroundTasks):
        user_query = request.query
        session_id = request.session_id or str(uuid.uuid4())
        is_stream = request.is_stream

        update_task_status(session_id, TASK_STATUS_PROCESSING, is_stream)

        if is_stream:
            background_tasks.add_task(_run_query_graph, session_id, user_query, is_stream)
            await asyncio.sleep(0.1)
            return {"message": "Query submitted", "session_id": session_id}
        else:
            _run_query_graph(session_id, user_query, is_stream)
            answer = get_task_result(session_id, "answer", "")
            return {"session_id": session_id, "answer": answer}


    @app.get("/stream/{task_id}",response_model=None)
    async def stream(task_id: str, request: Request):
        return StreamingResponse(
            sse_generator(task_id, request), media_type="text/event-stream",
        )

    @app.get("/history/{session_id}")
    async def history(session_id: str, limit: int = 50):
        records = get_recent_message(session_id, limit=limit)
        items = [
            {
                "role": r.get("role", ""),
                "text": r.get("text", ""),
                "ts": r.get("ts")
            }
            for r in records
        ]
        return {"session_id": session_id, "items": items}

    @app.delete("/history/{session_id}")
    async def clear_chat_history(session_id: str):
        count = clear_history(session_id)
        return {"deleted_count": count}


def _run_query_graph(session_id: str, user_query: str, is_stream: bool):
    """后台任务：执行查询流程图"""
    if is_stream:
        create_sse_queue(session_id)

    default_state = {
        "original_query": user_query,
        "session_id": session_id,
        "is_stream": is_stream
    }

    query_app.invoke(default_state)
    update_task_status(session_id, TASK_STATUS_COMPLETED, is_stream)

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app=create_app(), host="0.0.0.0", port=8001)