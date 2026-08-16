"""Neo4j 驱动（同步，健康检查经线程池）。Route A 下默认禁用（NEO4J_ENABLED=false）。"""
import asyncio

from neo4j import GraphDatabase

from app.core.config import get_settings

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        s = get_settings()
        _driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    return _driver


def ping_sync() -> bool:
    if not get_settings().neo4j_enabled:
        return False  # 未启用：健康检查如实报告 disabled
    with get_driver().session() as session:
        session.run("RETURN 1").consume()
    return True


async def ping() -> bool:
    return await asyncio.to_thread(ping_sync)
