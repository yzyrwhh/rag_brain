"""FastAPI 应用工厂（Phase 0）。"""
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import bind_context, setup_logging
from app.infra.minio import ensure_bucket


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Phase 0：MinIO bucket 尽力确保；其余基础设施首次访问时惰性连接
    try:
        ensure_bucket()
    except Exception:  # noqa: BLE001 - 启动不因基础设施缺失而失败
        pass
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.app_debug)

    app = FastAPI(
        title="掌柜智库",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Phase 0 开发期；生产按 02 §7 收紧
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    async def root():
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/docs")

    @app.middleware("http")
    async def _request_context(request, call_next):
        request_id = str(uuid.uuid4())
        bind_context(request_id=request_id)
        try:
            return await call_next(request)
        finally:
            from app.core.logging import unbind_context

            unbind_context("request_id")

    return app


app = create_app()
