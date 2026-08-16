"""任务状态机单元测试（纯函数，无基础设施）。"""
import pytest

from app.core.errors import AppError
from app.core.task_states import validate_transition


def test_valid_transition():
    validate_transition("PENDING", "EXECUTING")
    validate_transition("EXECUTING", "AWAITING_INPUT")
    validate_transition("AWAITING_INPUT", "EXECUTING")
    validate_transition("FAILED", "EXECUTING")  # 重试


def test_terminal_rejects_all():
    for terminal in ("COMPLETED", "CANCELLED"):
        with pytest.raises(AppError):
            validate_transition(terminal, "EXECUTING")


def test_illegal_transition():
    with pytest.raises(AppError):
        validate_transition("PENDING", "COMPLETED")
