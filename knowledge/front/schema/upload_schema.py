from pydantic import BaseModel, Field


class UploadResponse(BaseModel):

    message: str = Field(..., description="消息响应")
    task_id: str = Field(...,description="任务ID")
    