"""知识库文档导入编排（Phase 1，对齐 03 §3.8 文档元数据契约）。

- create_document（异步，API 侧）：sha256 去重 -> 上传 MinIO -> 写 knowledge_documents -> 建任务
- run_import_pipeline_sync（同步，Celery worker 侧）：下载 -> 解析 -> 图片 -> 切分 -> 嵌入 ->
  插入 Milvus，逐阶段更新文档状态（parsing/splitting/embedding/importing/completed）并发出
  node.start/node.end 与 tool.call/tool.result 事件；任务状态经 validate_transition 迁移
  （PENDING -> EXECUTING -> COMPLETED，失败由 workers/tasks.py 置 FAILED）。

事件 sink 说明：_append_event_sync / _set_status_sync 原在 workers/tasks.py，为避免重复
移入本模块顶部，workers/tasks.py 改为从本模块引用。
"""
import asyncio
import datetime
import hashlib
import io
import os
import shutil
import tempfile
import uuid

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.task_states import validate_transition
from app.infra.milvus import get_client
from app.infra.minio import get_minio
from app.infra.mongo import get_async_db, get_sync_db
from app.infra.redis import get_sync_redis
from app.schemas.events import SSEEvent, sse_pack
from app.services import task_service
from app.services.import_pipeline import (
    embed_chunks,
    extract_document_meta,
    insert_chunks,
    pdf_to_md,
    process_md_images,
    split_document,
)

_UTC = datetime.timezone.utc

# 导入管线阶段（knowledge_documents.status 与事件 node 名一致）
_PHASES = ["parsing", "splitting", "embedding", "importing"]

# 直接上传即拒绝的图片扩展名（阶段一）
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def _now() -> str:
    return datetime.datetime.now(_UTC).isoformat()


def _event_channel(task_id: str) -> str:
    return f"task:{task_id}"


# ---------------- worker 侧同步助手（原 workers/tasks.py，移入此处避免重复） ----------------


def _append_event_sync(task_id: str, event_type: str, payload: dict) -> int:
    """同步版 append_event（worker 用）；seq 来自 Mongo，事件发布到 Redis 通道。"""
    db = get_sync_db()
    last = db["task_events"].find_one({"task_id": task_id}, sort=[("seq", -1)])
    seq = (last["seq"] + 1) if last else 1
    db["task_events"].insert_one(
        {
            "task_id": task_id,
            "seq": seq,
            "type": event_type,
            "payload": payload,
            "ts": _now(),
        }
    )
    get_sync_redis().publish(_event_channel(task_id), sse_pack(event_type, payload))
    return seq


def _set_status_sync(task_id: str, status: str, **extra) -> None:
    db = get_sync_db()
    update = {"status": status, "updated_at": _now(), **extra}
    if status == "EXECUTING":
        update.setdefault("started_at", _now())
    if status in {"COMPLETED", "FAILED", "CANCELLED"}:
        update["finished_at"] = _now()
    db["tasks"].update_one({"task_id": task_id}, {"$set": update})


def _update_doc_sync(doc_id: str, **fields) -> None:
    get_sync_db()["knowledge_documents"].update_one(
        {"doc_id": doc_id}, {"$set": {"updated_at": _now(), **fields}}
    )


# ---------------- API 侧：创建文档 + 排队任务 ----------------


async def create_document(
    user_id: str, space_id: str, domain: str, filename: str, file_bytes: bytes
) -> tuple[str, str, str]:
    """创建文档元数据并排队导入任务，返回 (doc_id, task_id, file_key)。"""
    db = get_async_db()

    # 1) checksum 去重（同 space 内）
    checksum = hashlib.sha256(file_bytes).hexdigest()
    existing = await db["knowledge_documents"].find_one(
        {"space_id": space_id, "checksum": checksum}
    )
    if existing is not None:
        raise AppError(ErrorCode.CONFLICT, "文档已存在", status_code=409)

    # 2) 生成 doc_id 并上传 MinIO
    doc_id = str(uuid.uuid4())
    file_key = f"users/{user_id}/uploads/{doc_id}/{filename}"
    s = get_settings()

    def _upload() -> None:
        get_minio().put_object(
            s.minio_bucket,
            file_key,
            io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=_guess_content_type(filename),
        )

    await asyncio.to_thread(_upload)

    # 3) 写 knowledge_documents（字段对齐 03 §3.8 契约）
    now = _now()
    doc = {
        "doc_id": doc_id,
        "space_id": space_id,
        "user_id": user_id,
        "title": os.path.splitext(os.path.basename(filename))[0],
        "file_name": filename,
        "file_type": _guess_file_type(filename),
        "file_key": file_key,
        "source": "upload",
        "domain": domain,
        "tags": [],
        "status": "pending",
        "chunk_count": 0,
        "quality_score": None,
        "checksum": checksum,
        "created_at": now,
        "updated_at": now,
    }
    await db["knowledge_documents"].insert_one(doc)

    # 4) 建任务（agent=kb_import）并返回
    task_id = await task_service.create_task(user_id, "kb_import", {"doc_id": doc_id}, None)
    return doc_id, task_id, file_key


# ---------------- worker 侧：同步导入管线 ----------------


def run_import_pipeline_sync(
    task_id: str, doc_id: str, user_id: str, space_id: str, domain: str, file_key: str
) -> dict:
    """同步执行导入管线（Celery worker 调用）。

    声明式阶段执行器：阶段列表可插拔/可跳过/可单测（复用旧 BaseNode 抽象的职责，
    但不引入重框架）；每阶段统一发 node.start/end + tool.call/result 事件并更新 doc.status。
    任务状态迁移：PENDING -> EXECUTING -> COMPLETED；异常向上抛出由 workers/tasks.py 兜底置 FAILED。
    """
    db = get_sync_db()
    doc = db["knowledge_documents"].find_one({"doc_id": doc_id})
    if doc is None:
        raise AppError(ErrorCode.NOT_FOUND, "文档不存在", status_code=404)
    task_doc = db["tasks"].find_one({"task_id": task_id})
    if task_doc is None:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在", status_code=404)
    # 幂等启动：PENDING=首次执行，EXECUTING=重入/续跑（Celery 重投递等情况）；
    # 终态（COMPLETED/FAILED/CANCELLED）才拒绝。
    if task_doc["status"] not in {"PENDING", "EXECUTING"}:
        raise AppError(
            ErrorCode.TASK_BUSY,
            f"任务已处于终态，禁止重复执行: {task_doc['status']}",
            status_code=409,
        )
    _set_status_sync(task_id, "EXECUTING")

    s = get_settings()
    tmp_dir = tempfile.mkdtemp(prefix="kb_import_")
    try:
        ctx: dict = {
            "task_id": task_id,
            "doc_id": doc_id,
            "user_id": user_id,
            "space_id": space_id,
            "domain": domain,
            "file_key": file_key,
            "title": doc.get("title") or "",
            "tmp_dir": tmp_dir,
            "md_content": "",
            "chunks": [],
            "vectors": [],
            "sparse_vectors": [],
            "meta": {"tags": [], "entities": []},
        }
        stages = [
            _Stage("parsing", _stage_parse, "PDF/MD 解析 + 图片处理(VLM) + 实体抽取"),
            _Stage("splitting", _stage_split, "文档切分"),
            _Stage("embedding", _stage_embed, "BGE-M3 嵌入"),
            _Stage("importing", _stage_insert, "Milvus 插入"),
        ]
        for st in stages:
            _stage(task_id, doc_id, st.name, "start")
            try:
                st.func(ctx)
            except Exception:
                raise
            _stage(task_id, doc_id, st.name, "end")

        # 完成：文档 completed + 任务 COMPLETED
        _update_doc_sync(doc_id, status="completed", chunk_count=len(ctx["chunks"]))
        result = {
            "doc_id": doc_id,
            "chunk_count": len(ctx["chunks"]),
            "inserted": ctx.get("inserted", 0),
        }
        validate_transition("EXECUTING", "COMPLETED")
        _set_status_sync(
            task_id, "COMPLETED", result=result, cost={"tokens": 0, "estimated_cost": 0.0}
        )
        _append_event_sync(task_id, SSEEvent.COMPLETED, {
            "task_id": task_id,
            "cost": {"tokens": 0, "estimated_cost": 0.0},
        })
        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


class _Stage:
    """声明式阶段：名称 + 执行函数 + 描述（阶段执行器的构成单元）。"""

    def __init__(self, name: str, func, description: str = ""):
        self.name = name
        self.func = func
        self.description = description


# ---------------- 阶段实现（可独立单测） ----------------


def _stage_parse(ctx: dict) -> dict:
    """下载 -> PDF/MD 解析 -> 图片处理(VLM) -> 实体/主题抽取。"""
    s = get_settings()
    local_path = _download_from_minio(ctx["file_key"], ctx["tmp_dir"])
    file_type = _guess_file_type(local_path)
    image_prefix = _image_prefix(ctx["user_id"], ctx["doc_id"])

    if file_type == "pdf":
        md_path = pdf_to_md(local_path, ctx["tmp_dir"])
        ctx["md_content"] = process_md_images(
            md_path, s.minio_bucket, image_prefix, ctx["title"]
        )
    elif file_type == "md":
        with open(local_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        ctx["md_content"] = process_md_images(
            local_path, s.minio_bucket, image_prefix, ctx["title"]
        )
    elif file_type == "image":
        raise AppError(
            ErrorCode.VALIDATION_ERROR, "暂不支持直接导入图片文件（阶段一）", status_code=422
        )
    else:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, f"不支持的文件类型: {file_type}", status_code=422
        )

    # 实体/主题抽取（替代旧 item_name 的文档侧能力；LLM 失败降级空，不阻断）
    ctx["meta"] = extract_document_meta(ctx["md_content"], ctx["domain"])
    if ctx["meta"]["tags"] or ctx["meta"]["entities"]:
        _update_doc_sync(
            ctx["doc_id"],
            tags=ctx["meta"]["tags"],
            metadata={"entities": ctx["meta"]["entities"]},
        )
    return ctx


def _stage_split(ctx: dict) -> dict:
    ctx["chunks"] = split_document(ctx["md_content"], file_title=ctx["title"])
    if not ctx["chunks"]:
        raise AppError(ErrorCode.VALIDATION_ERROR, "文档切分为空", status_code=422)
    return ctx


def _stage_embed(ctx: dict) -> dict:
    ctx["vectors"], ctx["sparse_vectors"] = embed_chunks(ctx["chunks"])
    if len(ctx["vectors"]) != len(ctx["chunks"]) or len(ctx["sparse_vectors"]) != len(ctx["chunks"]):
        raise AppError(ErrorCode.INTERNAL, "嵌入数量与切片数量不一致", status_code=500)
    return ctx


def _stage_insert(ctx: dict) -> dict:
    s = get_settings()
    rows = [
        {
            "chunk_id": str(uuid.uuid4()),
            "doc_id": ctx["doc_id"],
            "space_id": ctx["space_id"],
            "user_id": ctx["user_id"],
            "domain": ctx["domain"],
            "visibility": 1,
            "chunk_index": idx,
            "text": ctx["chunks"][idx],
            "dense_vector": ctx["vectors"][idx],
            "sparse_vector": ctx["sparse_vectors"][idx],
        }
        for idx in range(len(ctx["chunks"]))
    ]
    ctx["inserted"] = insert_chunks(get_client(), s.milvus_chunks_collection, rows)
    return ctx


# ---------------- 内部工具 ----------------


def _stage(task_id: str, doc_id: str, phase: str, action: str, extra: dict | None = None) -> None:
    """更新文档状态并发出阶段事件：start -> node.start + tool.call；end -> node.end + tool.result。"""
    payload = {"node": phase, **(extra or {})}
    if action == "start":
        _update_doc_sync(doc_id, status=phase)
        _append_event_sync(task_id, SSEEvent.NODE_START, payload)
        _append_event_sync(task_id, SSEEvent.TOOL_CALL, {
            "tool_id": "kb_import", "name": phase, **(extra or {})
        })
    else:
        _append_event_sync(task_id, SSEEvent.NODE_END, payload)
        _append_event_sync(task_id, SSEEvent.TOOL_RESULT, {
            "tool_id": "kb_import", "name": phase, **(extra or {})
        })


def _image_prefix(user_id: str, doc_id: str) -> str:
    return f"users/{user_id}/uploads/{doc_id}"


def _download_from_minio(file_key: str, dest_dir: str) -> str:
    s = get_settings()
    dest = os.path.join(dest_dir, os.path.basename(file_key) or "upload.bin")
    get_minio().fget_object(s.minio_bucket, file_key, dest)
    return dest


def _guess_file_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".md", ".markdown"):
        return "md"
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    return "other"


def _guess_content_type(filename: str) -> str:
    file_type = _guess_file_type(filename)
    if file_type == "pdf":
        return "application/pdf"
    if file_type == "md":
        return "text/markdown"
    if file_type == "image":
        ext = os.path.splitext(filename)[1].lower()
        return f"image/{ext[1:]}" if ext.startswith(".") else "image/jpeg"
    return "application/octet-stream"
