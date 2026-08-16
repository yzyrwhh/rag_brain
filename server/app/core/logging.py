"""结构化日志（structlog，JSON 输出；对齐 07 §6.2 三级日志字段约定）。"""
import logging
import sys

import structlog


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(format="%(message)s", level=level, stream=sys.stdout, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
    )


def bind_context(**kw: object) -> None:
    """绑定请求级上下文（request_id/user_id/task_id），全程透传。"""
    structlog.contextvars.bind_contextvars(**kw)


def unbind_context(*keys: str) -> None:
    structlog.contextvars.unbind_contextvars(*keys)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
