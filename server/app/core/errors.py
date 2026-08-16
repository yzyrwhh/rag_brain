"""错误码框架（对齐 docs/05 §9 错误码约定 + §13.1 统一错误体）。"""
from enum import Enum

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(str, Enum):
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    TASK_BUSY = "TASK_BUSY"
    TASK_LIMIT = "TASK_LIMIT"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    INTERNAL = "INTERNAL"


class AppError(Exception):
    """业务异常：统一错误体 {"code","message","detail"}。"""

    def __init__(self, code: ErrorCode, message: str, status_code: int = 400, detail: dict | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


def error_body(code: str, message: str, detail: dict | None = None) -> dict:
    return {"code": code, "message": message, "detail": detail or {}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_req: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code.value, exc.message, exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_req: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body(
                ErrorCode.VALIDATION_ERROR.value,
                "参数校验失败，请检查输入",
                {"errors": exc.errors()[:5]},
            ),
        )

    @app.exception_handler(Exception)
    async def _generic_handler(_req: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(ErrorCode.INTERNAL.value, "服务器内部错误"),
        )
