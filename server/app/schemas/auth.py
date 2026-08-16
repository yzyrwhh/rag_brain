"""认证相关 DTO（对齐 docs/05 §13.2 契约）。"""
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    user_id: str
    username: str
    email: str | None = None
    role: str
    nickname: str | None = None
    created_at: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    user: UserOut
