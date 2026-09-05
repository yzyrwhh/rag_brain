"""
智能产品知识库统一 API 入口
============================

合并原 query(8001) 与 import(8000) 两套独立服务为单一 FastAPI 应用，
统一托管前端页面与全部接口，修复"双端口割裂"的问题。

接口一览
--------
- 页面托管:   GET /            → chat.html
              GET /chat.html   → 聊天页面
              GET /import.html → 知识导入页面
- 查询:       POST /query                 提交查询（支持流式/非流式）
              GET  /stream/{task_id}      SSE 流式通道
              GET  /history/{session_id}  会话历史
              DELETE /history/{session_id} 清空会话
              GET  /sessions              会话列表
- 导入:       POST /upload                上传文件（触发导入图）
              GET  /status/{task_id}      导入任务状态

启动方式（在 rag_brain 根目录下执行）:
    python -m uvicorn knowledge.front.api.main:app --host 0.0.0.0 --port 8001 --reload
"""
import asyncio
import os
import threading
import uuid

import uvicorn
from fastapi import FastAPI, UploadFile, File, Depends, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from knowledge.front.schema.QueryRequest import QueryRequest, TaskStatusResponse
from knowledge.front.schema.upload_schema import UploadResponse
from knowledge.front.service.import_file_service import ImportFileService
from knowledge.front.service.task_service import TaskService
from knowledge.front.utils.deps import get_import_file_service, get_task_service
from knowledge.front.utils.paths import get_front_page_dir
from knowledge.front.utils.sse_tool import sse_generator, create_sse_queue
from knowledge.front.utils.task_utils import (
    update_task_status,
    get_task_result,
    clear_task,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
)
from knowledge.processor.query_process.main_graph import query_app
from knowledge.tools.mongo_history_tool import (
    get_recent_message,
    clear_chat_message,
    list_sessions,
)


def create_app() -> FastAPI:
    """创建统一 FastAPI 应用。"""
    app = FastAPI(
        title="智能产品知识库",
        description="RAG 知识库：查询问答（流式/非流式）+ 文档导入 + 会话管理",
        version="1.0.0",
    )

    # 允许跨域（开发环境）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态文件挂载（前端页面目录）
    page_dir = get_front_page_dir()
    if os.path.isdir(page_dir):
        app.mount("/front", StaticFiles(directory=page_dir), name="front")

    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    """注册全部路由。"""

    # ==================== 页面托管 ====================
    @app.get("/", include_in_schema=False)
    async def index_page():
        return FileResponse(os.path.join(get_front_page_dir(), "chat.html"))

    @app.get("/chat.html", include_in_schema=False)
    async def chat_page():
        return FileResponse(os.path.join(get_front_page_dir(), "chat.html"))

    @app.get("/import.html", include_in_schema=False)
    async def import_page():
        return FileResponse(os.path.join(get_front_page_dir(), "import.html"))

    # ==================== 查询 ====================
    @app.post("/query")
    async def query(request: QueryRequest, background_tasks: BackgroundTasks):
        user_query = (request.query or "").strip()
        session_id = request.session_id or str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        is_stream = request.is_stream

        update_task_status(task_id, TASK_STATUS_PROCESSING)

        if is_stream:
            # 先建立 SSE 队列，客户端随即连接 /stream/{task_id}
            create_sse_queue(task_id)
            # 注意：不能用 FastAPI BackgroundTasks——它要等响应完全结束后才执行，
            # 而 SSE 是无限流（永不结束），查询图将永远不启动。
            # 因此流式任务用独立线程执行，事件经队列推送。
            threading.Thread(
                target=_run_query_graph,
                args=(session_id, task_id, user_query, is_stream),
                daemon=True,
            ).start()
            await asyncio.sleep(0.1)
            return {
                "message": "Query submitted",
                "session_id": session_id,
                "task_id": task_id,
            }

        # 非流式：同步执行并直接返回答案
        _run_query_graph(session_id, task_id, user_query, is_stream)
        answer = get_task_result(task_id, "answer", "")
        clear_task(task_id)
        return {"session_id": session_id, "task_id": task_id, "answer": answer}

    @app.get("/stream/{task_id}")
    async def stream(task_id: str, request: Request):
        return StreamingResponse(
            sse_generator(task_id, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/history/{session_id}")
    async def history(session_id: str, limit: int = 50):
        records = get_recent_message(session_id, limit=limit)
        # get_recent_message 按 ts 倒序返回（最新在前），历史展示需正序（旧→新），这里反转
        records = list(reversed(records))
        items = [
            {
                "role": r.get("role", ""),
                "text": r.get("text", ""),
                "rewritten_query": r.get("rewritten_query", ""),
                "item_names": r.get("item_names", []),
                "ts": r.get("ts"),
            }
            for r in records
        ]
        return {"session_id": session_id, "items": items}

    @app.delete("/history/{session_id}")
    async def clear_chat_history(session_id: str):
        count = clear_chat_message(session_id)
        return {"deleted_count": int(count or 0)}

    @app.get("/sessions")
    async def sessions(limit: int = 50):
        try:
            data = list_sessions(limit=limit)
            return {"sessions": data}
        except Exception as e:  # noqa: BLE001
            return {"sessions": [], "error": str(e)}

    # ==================== 导入 ====================
    @app.post("/upload", response_model=UploadResponse)
    async def upload_file(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        service: ImportFileService = Depends(get_import_file_service),
    ):
        # 保存文件 + MD5 去重检查
        task_id, file_dir, import_file_path, file_md5, is_duplicate, dup_title = service.process_upload_file(file)

        if is_duplicate:
            return UploadResponse(
                message=f"文件已导入过，已跳过",
                task_id="",
                duplicate=True,
                file_md5=file_md5,
            )

        # 后台执行导入图
        background_tasks.add_task(service.run_import_graph, task_id, file_dir, import_file_path, file_md5)
        return UploadResponse(message="上传文件成功", task_id=task_id, duplicate=False, file_md5=file_md5)

    @app.get("/status/{task_id}", response_model=TaskStatusResponse)
    async def get_status_endpoint(
        task_id: str, task_service: TaskService = Depends(get_task_service)
    ):
        task_info = task_service.get_task_info(task_id)
        return TaskStatusResponse(**task_info)


def _run_query_graph(session_id: str, task_id: str, user_query: str, is_stream: bool):
    """后台任务：执行查询图，完成后标记任务状态。"""
    try:
        default_state = {
            "original_query": user_query,
            "session_id": session_id,
            "task_id": task_id,
            "is_stream": is_stream,
        }
        query_app.invoke(default_state)
        update_task_status(task_id, TASK_STATUS_COMPLETED)
    except Exception as e:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        update_task_status(task_id, TASK_STATUS_FAILED)


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app=create_app(), host="0.0.0.0", port=8001)
