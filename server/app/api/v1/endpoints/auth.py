"""认证端点（对齐 docs/05 §13.2 契约）。"""
from fastapi import APIRouter, Depends

from app.core.deps import get_bearer_token, get_current_user
from app.core.errors import AppError, ErrorCode
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenPair, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenPair, status_code=201)
async def register(body: RegisterRequest) -> TokenPair:
    return await auth_service.register(body.username, body.password, body.email)


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest) -> TokenPair:
    return await auth_service.login(body.username, body.password)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest) -> TokenPair:
    return await auth_service.refresh(body.refresh_token)


@router.post("/logout")
async def logout(
    _user: dict = Depends(get_current_user),
    token: str | None = Depends(get_bearer_token),
) -> dict:
    if token is None:
        raise AppError(ErrorCode.AUTH_INVALID, "未提供认证凭证", status_code=401)
    await auth_service.logout(token)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)) -> UserOut:
    return await auth_service.me(user)
