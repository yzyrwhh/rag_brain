"""健康检查形状测试（不依赖基础设施：probe 失败返回 degraded 但 200）。"""


def test_health_returns_shape(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert set(body["services"]) == {"mongo", "milvus", "redis", "minio", "neo4j"}
