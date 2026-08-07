from functools import lru_cache
from fastapi import FastAPI

from knowledge.front.service.import_file_service import ImportFileService
from knowledge.front.service.task_service import TaskService


@lru_cache
def get_task_service() -> TaskService:
    """获取 TaskService 单例"""
    return TaskService()


@lru_cache
def get_import_file_service() -> ImportFileService:
    """获取 FileImportService 单例"""
    return ImportFileService(get_task_service())