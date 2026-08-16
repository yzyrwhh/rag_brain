"""FastAPI 依赖：get_current_user / require_role（对齐 02 §7 授权）。"""
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError, ErrorCode
from app.infra.mongo import get_async_db

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if creds is None:
        raise AppError(ErrorCode.AUTH_INVALID, "未提供认证凭证", status_code=401)
    try:
        payload = jwt.decode(
            creds.credentials,
            request.app.state.settings.jwt_secret,
            algorithms=[request.app.state.settings.jwt_algorithm],
        )
    except jwt.PyJWTError:
        raise AppError(ErrorCode.AUTH_INVALID, "令牌无效或已过期", status_code=401)

    if payload.get("type") != "access":
        raise AppError(ErrorCode.AUTH_INVALID, "令牌类型错误", status_code=401)

    user_id = payload.get("sub")
    db = get_async_db()
    user = await db["users"].find_one({"_id": user_id, "status": "active"})
    if user is None:
        raise AppError(ErrorCode.AUTH_INVALID, "用户不存在或已被禁用", status_code=401)
    return user


def require_role(*roles: str):
    def _dep(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise AppError(ErrorCode.AUTH_FORBIDDEN, "没有权限执行该操作", status_code=403)
        return user

    return _dep


async def get_bearer_token(request: Request) -> str | None:
    """提取原始 Bearer token（用于登出等需要原文的场景）。"""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return None
