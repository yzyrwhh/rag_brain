from webbrowser import register

import  os
import uvicorn

from fastapi import FastAPI, UploadFile, Depends,BackgroundTasks,File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from knowledge.front.schema.task_schema import TaskStatusResponse
from knowledge.front.schema.upload_schema import UploadResponse
from knowledge.front.service.import_file_service import ImportFileService
from knowledge.front.service.task_service import TaskService
from knowledge.front.utils.deps import get_import_file_service, get_task_service
from knowledge.front.utils.paths import get_front_page_dir
from knowledge.processor.import_process.base import setup_logging


def creat_app() -> FastAPI:
    app = FastAPI(description="知识库导入")

    front_page_dir = get_front_page_dir()

    if front_page_dir and os.path.exists(front_page_dir):
        app.mount("/front", StaticFiles(directory=front_page_dir), name="static")

    register_router(app)

    return app
def register_router(app:FastAPI) -> FastAPI:
    @app.get("/import")
    async def import_page():
        return FileResponse(os.path.join(get_front_page_dir(),"import.html"))

    @app.post("/upload", response_model=UploadResponse)
    async def upload_file(
                background_tasks: BackgroundTasks,
                file: UploadFile = File(...),
                service: ImportFileService = Depends(get_import_file_service)):

        #保存文件
        task_id,file_dir,import_file_path = service.process_upload_file(file)

        #执行图
        background_tasks.add_task(service.run_import_graph,
                                  task_id,file_dir,import_file_path)

        #返回task_id
        return UploadResponse(message="上传文件成功",task_id=task_id)

    @app.get("/status/{task_id}",response_model=TaskStatusResponse)
    async def get_status_endpoint(task_id: str,
                                  task_service: TaskService = Depends(get_task_service)):

        task_info = task_service.get_task_info(task_id)
        return TaskStatusResponse(**task_info)

if __name__ == "__main__":
    setup_logging()
    uvicorn.run(app="knowledge.front.api.import_router:creat_app", port=8000, host="0.0.0.0",reload=True)








