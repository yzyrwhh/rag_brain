import os.path
import shutil
import uuid
from datetime import datetime

from fastapi import UploadFile

from knowledge.front.service.task_service import TaskService
from knowledge.front.utils.paths import get_local_base_dir
from knowledge.processor.import_process.main_graph import run_graph_import
from knowledge.tools.file_registry_tool import compute_file_md5, get_file_registry


class ImportFileService:
    def __init__(self,task_service: TaskService):
        self.task_service = task_service

    def get_file_dir(self) ->str:
        return os.path.join(get_local_base_dir(),datetime.now().strftime("%y%m%d"))

    def save_upload_file_to_local(self,file:UploadFile,file_dir:str):
        os.makedirs(file_dir,exist_ok=True)
        import_file_path = os.path.join(file_dir,file.filename)
        with open(import_file_path,"wb") as f:
            # f.write(file.file.read())    文件过大有溢出风险
            shutil.copyfileobj(file.file, f)    #批量操作
        return import_file_path

    def process_upload_file(self,file:UploadFile):

        data_dir = self.get_file_dir()
        task_id = str(uuid.uuid4())
        file_dir = os.path.join(data_dir,task_id)

        self.task_service.mark_node_running(task_id,"upload_file")
        import_file_path = self.save_upload_file_to_local(file,file_dir)

        # MD5 去重检查：内容完全相同（已导入过）则跳过
        file_md5 = compute_file_md5(import_file_path)
        registry = get_file_registry()
        existing = registry.find_by_md5(file_md5)
        if existing:
            # 清理临时文件，返回重复标记
            try:
                os.remove(import_file_path)
            except OSError:
                pass
            return task_id, file_dir, import_file_path, file_md5, True, existing.get("file_title", "")

        self.task_service.mark_node_done(task_id,"upload_file")

        #task_id: 任务id, file_dir: 本地保存上传文件目录，import_file_path: 本地上传文件目录+文件名称
        return task_id,file_dir,import_file_path,file_md5,False,""

    def run_import_graph(self,task_id: str,file_dir: str, import_file_path: str, file_md5: str = ""):
        try:
            self.task_service.update_task_status(task_id,"processing")

            run_graph_import(task_id,import_file_path,file_dir)

            # 导入成功后才登记 MD5（失败不登记，允许重试）
            if file_md5:
                get_file_registry().register(file_md5, os.path.basename(import_file_path), task_id)

            self.task_service.update_task_status(task_id,"completed")

        except Exception as e:
                self.task_service.update_task_status(task_id,"failed")
                print(f"{task_id} failed {e}")




