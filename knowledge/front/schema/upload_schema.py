from typing import Optional
from pydantic import BaseModel, Field


class UploadResponse(BaseModel):

    message: str = Field(..., description="消息响应")
    task_id: str = Field(..., description="任务ID")
    duplicate: Optional[bool] = Field(False, description="是否重复文件（已导入过）")
    file_md5: Optional[str] = Field("", description="文件内容 MD5")
