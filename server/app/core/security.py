"""认证原语：JWT（PyJWT，HS256）+ bcrypt 密码哈希（对齐 02 §7 / 05 §2）。"""
import datetime
import uuid

import bcrypt
import jwt

from app.core.config import get_settings

_UTC = datetime.timezone.utc


def _now_ts() -> int:
    return int(datetime.datetime.now(_UTC).timestamp())


# ---------- 密码 ----------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ---------- JWT ----------
def _encode(sub: str, token_type: str, ttl: int, extra: dict | None = None) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    now = _now_ts()
    payload: dict = {
        "sub": sub,
        "type": token_type,
        "jti": jti,
        "iat": now,
        "exp": now + ttl,
    }
    if extra:
        payload.update(extra)
    settings = get_settings()
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


def create_access_token(user_id: str, extra: dict | None = None) -> tuple[str, str]:
    return _encode(user_id, "access", get_settings().jwt_access_ttl, extra)


def create_refresh_token(user_id: str) -> tuple[str, str]:
    return _encode(user_id, "refresh", get_settings().jwt_refresh_ttl)


def decode_token(token: str) -> dict:
    """解码并校验签名/过期；失败抛 jwt.PyJWTError。"""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def access_ttl_seconds() -> int:
    return get_settings().jwt_access_ttl
