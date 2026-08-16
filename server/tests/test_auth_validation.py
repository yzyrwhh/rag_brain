"""认证参数校验测试（422 在进入业务层前拦截，无需基础设施）。"""


def test_register_short_password_422(client):
    r = client.post("/api/v1/auth/register", json={"username": "alice", "password": "short"})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_register_bad_username_422(client):
    r = client.post("/api/v1/auth/register", json={"username": "a b!", "password": "password123"})
    assert r.status_code == 422
