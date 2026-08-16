"""认证服务（对齐 docs/05 §2 与 §13.2；refresh 旋转 + Redis 吊销）。"""
import datetime
import uuid

import jwt

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.infra.mongo import get_async_db
from app.infra.redis import get_async_redis
from app.schemas.auth import TokenPair, UserOut

_UTC = datetime.timezone.utc


def _now() -> str:
    return datetime.datetime.now(_UTC).isoformat()


def _refresh_key(user_id: str, jti: str) -> str:
    return f"auth:refresh:{user_id}:{jti}"


async def _issue_pair(user: dict) -> TokenPair:
    """签发 access+refresh；refresh jti 存入 Redis（TTL=7d），吊销列表即"键不存在"。"""
    settings = get_settings()
    user_id = user["_id"]
    access_token, _ = create_access_token(user_id)
    refresh_token, refresh_jti = create_refresh_token(user_id)
    r = get_async_redis()
    await r.set(_refresh_key(user_id, refresh_jti), "1", ex=settings.jwt_refresh_ttl)
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut(
            user_id=user_id,
            username=user["username"],
            email=user.get("email"),
            role=user.get("role", "user"),
            nickname=user.get("nickname"),
            created_at=user.get("created_at"),
        ),
    )


async def register(username: str, password: str, email: str | None) -> TokenPair:
    db = get_async_db()
    if await db["users"].find_one({"username": username}):
        raise AppError(ErrorCode.CONFLICT, "用户名已存在", status_code=409)
    if email and await db["users"].find_one({"email": email}):
        raise AppError(ErrorCode.CONFLICT, "邮箱已被使用", status_code=409)
    user = {
        "_id": str(uuid.uuid4()),
        "username": username,
        "email": email,
        "password_hash": hash_password(password),
        "role": "user",
        "nickname": username,
        "status": "active",
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db["users"].insert_one(user)
    return await _issue_pair(user)


async def login(username: str, password: str) -> TokenPair:
    db = get_async_db()
    user = await db["users"].find_one({"username": username})
    if user is None or not verify_password(password, user["password_hash"]):
        raise AppError(ErrorCode.AUTH_INVALID, "用户名或密码错误", status_code=401)
    if user.get("status") != "active":
        raise AppError(ErrorCode.AUTH_FORBIDDEN, "账号已被禁用", status_code=403)
    return await _issue_pair(user)


async def refresh(refresh_token: str) -> TokenPair:
    settings = get_settings()
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError:
        raise AppError(ErrorCode.AUTH_INVALID, "refresh 令牌无效或已过期", status_code=401)
    if payload.get("type") != "refresh":
        raise AppError(ErrorCode.AUTH_INVALID, "令牌类型错误", status_code=401)

    user_id = payload["sub"]
    jti = payload["jti"]
    r = get_async_redis()
    key = _refresh_key(user_id, jti)
    if not await r.exists(key):
        raise AppError(ErrorCode.AUTH_INVALID, "refresh 令牌已失效（可能已被使用）", status_code=401)
    # 旋转：删除旧 jti，签发新对
    await r.delete(key)

    db = get_async_db()
    user = await db["users"].find_one({"_id": user_id})
    if user is None or user.get("status") != "active":
        raise AppError(ErrorCode.AUTH_INVALID, "用户不存在或已被禁用", status_code=401)
    return await _issue_pair(user)


async def logout(access_token: str) -> None:
    """吊销 access jti 直至其自然过期（Phase 0 简化：仅黑名单 access）。"""
    settings = get_settings()
    try:
        payload = decode_token(access_token)
    except jwt.PyJWTError:
        return  # 已过期令牌无需吊销
    exp = int(payload.get("exp", 0))
    now = int(datetime.datetime.now(_UTC).timestamp())
    ttl = max(exp - now, 1)
    r = get_async_redis()
    await r.set(f"auth:blacklist:{payload['jti']}", "1", ex=ttl)


async def me(user: dict) -> UserOut:
    return UserOut(
        user_id=user["_id"],
        username=user["username"],
        email=user.get("email"),
        role=user.get("role", "user"),
        nickname=user.get("nickname"),
        created_at=user.get("created_at"),
    )
