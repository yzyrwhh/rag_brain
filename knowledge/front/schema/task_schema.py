from typing import List

from pydantic import BaseModel, Field


class TaskStatusResponse(BaseModel):
    status: str = Field(..., description="任务状态")
    done_list: List[str] = Field(...,description="已完成")
    running_list: List[str] = Field(...,description="正在运行")
