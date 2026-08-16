"""健康检查：报告各基础设施连通状态（对齐 08 §2.0 验收标准）。"""
import asyncio

from fastapi import APIRouter

from app.infra import milvus, minio, mongo, neo4j, redis

router = APIRouter(tags=["health"])


async def _probe(name: str, fn):
    try:
        await fn()
        return name, {"ok": True}
    except Exception as exc:  # noqa: BLE001 - 健康检查需要吞异常
        return name, {"ok": False, "error": type(exc).__name__}


@router.get("/health")
async def health() -> dict:
    probes = await asyncio.gather(
        _probe("mongo", mongo.ping),
        _probe("milvus", milvus.ping),
        _probe("redis", redis.ping),
        _probe("minio", minio.ping),
        _probe("neo4j", neo4j.ping),
    )
    services = dict(probes)
    all_ok = all(v["ok"] for v in services.values())
    return {"status": "ok" if all_ok else "degraded", "services": services}
