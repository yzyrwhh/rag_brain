"""测试夹具：无需基础设施的用例（Phase 0 冒烟）。"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="session")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c
