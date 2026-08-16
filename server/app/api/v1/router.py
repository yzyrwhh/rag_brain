"""v1 路由汇总。"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, knowledge, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(tasks.router)
api_router.include_router(knowledge.router)
