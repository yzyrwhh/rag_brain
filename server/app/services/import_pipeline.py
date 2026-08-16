"""文档导入管线（纯同步函数，Celery worker 用）。

逻辑移植自旧项目 knowledge/processor/import_process/nodes/*（旧代码仅作参考，不 import）：

- pdf_to_md            -> 旧 pdf_md_node.py：MinerU CLI subprocess 调用 + HF_HOME/MODELSCOPE_CACHE 环境变量
- process_md_images    -> 旧 md_img.py：VLM 图片摘要(alt) + 上传 MinIO + 改写引用（内容保真，图片文字不丢）
- extract_document_meta -> 旧 item_name_recognition 的升级：LLM 抽取主题标签与关键实体（多域泛化）
- split_document       -> 旧 document_split_node.py：标题分段 + RecursiveCharacterTextSplitter + 短段合并
- embed_chunks         -> 旧 bge_embedding_node.py + bge_client_util.py：BGE-M3 批量嵌入（仅 dense）
- insert_chunks        -> 旧 import_milvus_node.py：字段对齐 kb_chunks_v3，改用 pymilvus 3.x MilvusClient API
"""
import logging
import os
import re
import subprocess
import time
from collections import deque
from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings
from app.infra.minio import get_minio
from app.services.llm_client import chat_json, vlm_image_summary

logger = logging.getLogger(__name__)

# 旧 md_img 配置的图片扩展名白名单（knowledge/processor/import_process/config.py）
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
# 标题行正则（旧 document_split_node）
_TITLE_RULE = re.compile(r"^\s*(#{1,6})\s+(.+)")

# ---------------------------------------------------------------------------
# pdf -> md（旧 pdf_md_node.py）
# ---------------------------------------------------------------------------


def pdf_to_md(pdf_path: str, out_dir: str) -> str:
    """调用 mineru CLI 将 PDF 转为 Markdown，返回生成的 .md 路径。

    环境变量与旧 pdf_md_node._execute_mineru 一致：HF_HOME / MODELSCOPE_CACHE 指向
    模型缓存目录（默认 D:\\software\\mineru，可经 Settings 环境变量覆盖），HF_ENDPOINT 走 hf-mirror。
    输出布局沿用旧逻辑：{out_dir}/{stem}/auto/{stem}.md。
    """
    s = get_settings()
    os.environ["HF_ENDPOINT"] = s.hf_endpoint
    os.environ["HF_HOME"] = s.mineru_hf_home
    os.environ["MODELSCOPE_CACHE"] = s.mineru_modelscope_cache

    cmd = [
        "mineru",
        "-p", pdf_path,
        "-o", out_dir,
        "--source", "local",
        "--device", "cpu",
        "--backend", "pipeline",
        "--batch-size", "1",
        "--no-auto-download",
    ]
    logger.info("开始 MinerU 转换: pdf=%s out=%s", pdf_path, out_dir)
    start_ts = time.time()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        logger.debug("[mineru] %s", line.rstrip())

    code = proc.wait()
    elapsed = time.time() - start_ts
    if code != 0:
        raise RuntimeError(f"mineru 转换失败: exit_code={code}, elapsed={elapsed:.1f}s")
    logger.info("MinerU 转换成功，耗时 %.1fs", elapsed)

    file_stem = os.path.splitext(os.path.basename(pdf_path))[0]
    md_path = os.path.join(out_dir, file_stem, "auto", f"{file_stem}.md")
    if not os.path.isfile(md_path):
        raise RuntimeError(f"mineru 未生成预期 md 文件: {md_path}")
    return md_path


# ---------------------------------------------------------------------------
# md 图片处理（旧 md_img.py，降级版）
# ---------------------------------------------------------------------------


def process_md_images(
    md_path: str, minio_bucket: str, img_dir_prefix: str, doc_title: str = ""
) -> str:
    """提取 md 中引用的本地图片 -> VLM 生成中文摘要(alt) -> 上传 MinIO -> 改写引用为
    `![摘要](minio_url)`，返回改写后的 md 内容。

    摘要写入 alt = 图片内容进入切片与检索（修复"图片文字全部丢失"问题）。
    对齐旧 md_img.py 流程：扫描引用图片 -> 提取上下文 -> VLM 摘要(限速) -> 上传 -> 替换。
    """
    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    md_dir = os.path.dirname(os.path.abspath(md_path))
    images_dir = os.path.join(md_dir, "images")
    # 兜底：MinerU 不同版本可能把图片放在 auto/ 上一级的 images/
    if not os.path.isdir(images_dir):
        parent_images_dir = os.path.join(os.path.dirname(md_dir), "images")
        if os.path.isdir(parent_images_dir):
            images_dir = parent_images_dir
    if not os.path.isdir(images_dir):
        logger.info("未找到 images 目录（%s），跳过图片处理", md_dir)
        return md_content

    s = get_settings()
    minio_client = get_minio()
    base_url = _minio_base_url(minio_bucket)
    limiter = _RateLimiter(s.vl_requests_per_minute)

    for image_filename in sorted(os.listdir(images_dir)):
        ext = os.path.splitext(image_filename)[1].lower()
        if ext not in _IMAGE_EXTENSIONS:
            continue
        if not re.search(r"!\[.*?\]\(.*?" + re.escape(image_filename) + r".*?\)", md_content):
            logger.debug("图片 %s 未被 md 引用，跳过", image_filename)
            continue

        image_full_path = os.path.join(images_dir, image_filename)
        object_name = f"{img_dir_prefix}/{image_filename}"
        content_type = f"image/{ext[1:]}" if ext.startswith(".") else "application/octet-stream"
        try:
            minio_client.fput_object(
                minio_bucket, object_name, image_full_path, content_type=content_type
            )
        except Exception as e:  # noqa: BLE001 - 单张图片失败不阻断整条管线
            logger.warning("图片上传失败 %s: %s", image_filename, e)
            continue

        remote_url = f"{base_url}/{object_name}"
        alt = _image_alt_text(image_full_path, image_filename, md_content, doc_title, limiter)
        replace_pattern = re.compile(
            r"!\[.*?\]\((.*?" + re.escape(image_filename) + r".*?)\)",
            re.IGNORECASE,
        )
        md_content = replace_pattern.sub(f"![{alt}]({remote_url})", md_content)
        logger.info("图片已处理: %s -> %s (alt=%s)", image_filename, remote_url, alt)

    return md_content


class _RateLimiter:
    """简单节流（对齐旧 requests_per_minute=12 限速）。"""

    def __init__(self, rpm: int):
        self._interval = 60.0 / max(rpm, 1)
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = self._interval - (now - self._last)
        if delta > 0:
            time.sleep(delta)
        self._last = time.monotonic()


def _image_alt_text(
    image_full_path: str,
    image_filename: str,
    md_content: str,
    doc_title: str,
    limiter: "_RateLimiter",
) -> str:
    """VLM 摘要生成；VLM 关闭/失败时降级为文件名（不阻断管线）。"""
    s = get_settings()
    lines = md_content.split("\n")
    context_parts: List[str] = []
    for idx, line in enumerate(lines):
        if image_filename not in line:
            continue
        for i in range(max(0, idx - 2), min(len(lines), idx + 3)):
            cand = lines[i].strip()
            if cand and "![" not in cand and cand not in context_parts:
                context_parts.append(cand)
        break
    context = "\n".join(context_parts[:6]) if context_parts else ""

    if s.vlm_enabled:
        limiter.wait()
        summary = vlm_image_summary(image_full_path, doc_title or "", context)
        if summary and summary != "图片":
            return summary
    return os.path.splitext(image_filename)[0]


_ENTITY_SYSTEM_PROMPT = (
    "你是文档元数据抽取器。从给定文档内容中抽取 tags 与 entities：\n"
    "tags：3-8 个主题标签，覆盖文档核心主题；\n"
    "entities：文档涉及的关键实体（产品/型号/框架/技术/专有名词），按领域引导。\n"
    "只输出 JSON：{\"tags\": [\"...\"], \"entities\": [\"...\"]}；"
    "实体用最规范名称，绝不编造。"
)


def extract_document_meta(content: str, domain: str = "") -> dict:
    """LLM 抽取主题标签与关键实体（替代旧 item_name 的文档侧能力，多域泛化）。
    失败降级为空 dict（不阻断导入管线）。"""
    if not content:
        return {"tags": [], "entities": []}
    try:
        result = chat_json(
            _ENTITY_SYSTEM_PROMPT,
            f"领域(domain)：{domain or 'general'}\n\n文档内容片段：\n{content[:4000]}",
            max_tokens=300,
        )
        tags = [str(t)[:50] for t in (result.get("tags") or [])][:8]
        entities = [str(e)[:80] for e in (result.get("entities") or [])][:20]
        return {"tags": tags, "entities": entities}
    except Exception:  # noqa: BLE001 - LLM 失败不阻断导入
        logger.warning("实体/主题抽取失败，降级为空", exc_info=True)
        return {"tags": [], "entities": []}


def _minio_base_url(bucket: str) -> str:
    """对齐旧 minio_utils.get_minio_base_url：{protocol}://{endpoint}/{bucket}"""
    s = get_settings()
    protocol = "https" if s.minio_secure else "http"
    endpoint = s.minio_endpoint.replace("http://", "").replace("https://", "")
    return f"{protocol}://{endpoint}/{bucket}"


# ---------------------------------------------------------------------------
# 切分（旧 document_split_node.py）
# ---------------------------------------------------------------------------


def split_document(md_content: str, file_title: str = "") -> List[str]:
    """按旧 document_split_node 流程切分：标题分段 -> 长段递归切分 -> 短段贪婪合并。

    返回每个切片的最终文本（title + body，即旧 collect_data 的 content 字段）。
    file_title 作为兜底父标题（旧逻辑取自 state['file_title']，新管线传文档标题）。
    """
    if md_content:
        md_content = md_content.replace("\r\n", "\n").replace("\r", "\n")

    s = get_settings()
    parts = _split_doc_title(md_content, file_title)

    current_parts: List[dict] = []
    for part in parts:
        current_parts.extend(_split_long_part(part, s.max_content_length))
    final_parts = _merge_short_part(current_parts, s.min_content_length)

    return [f"{p.get('title', '')}\n\n{p.get('body', '')}" for p in final_parts]


def _split_doc_title(md_content: str, file_title: str) -> List[dict]:
    """按标题行把 md 切成「标题 + 正文」段落（旧 split_doc_title）。"""
    lines = md_content.split("\n")
    temp: List[str] = []
    res: List[dict] = []
    new_title = ""
    in_code = False
    level_title_list = [""] * 7
    current_level = 0

    for line in lines:
        if line.strip() in ("```", "~~~"):
            in_code = not in_code
        if not in_code and _TITLE_RULE.match(line):
            content = "\n".join(temp)
            if new_title or content:
                if current_level > 1:
                    parent_title = level_title_list[current_level - 1] or file_title
                else:
                    parent_title = file_title
                if not parent_title:
                    parent_title = file_title
                res.append({
                    "title": new_title,
                    "body": content,
                    "file_title": file_title,
                    "parent_title": parent_title,
                })

            match_obj = _TITLE_RULE.match(line)
            if match_obj:
                level = len(match_obj.group(1))
                current_level = level
                level_title_list[level] = line
                for lv in range(current_level + 1, 7):
                    level_title_list[lv] = ""

            new_title = line
            temp = []
        else:
            temp.append(line)

    last_content = "\n".join(temp)
    if new_title or last_content:
        if current_level > 1:
            parent_title = level_title_list[current_level - 1] or file_title
        else:
            parent_title = file_title
        if not parent_title:
            parent_title = file_title
        res.append({
            "title": new_title,
            "body": last_content,
            "file_title": file_title,
            "parent_title": parent_title,
        })
    return res


def _split_long_part(part: dict, max_content_length: int) -> List[dict]:
    """超长段落用 RecursiveCharacterTextSplitter 再切（参数对齐旧 split_long_part）。"""
    title = part.get("title") or ""
    body = part.get("body") or ""
    file_title = part.get("file_title")
    parent_title = part.get("parent_title")

    if len(title) > 50:
        title = title[:50]

    title_prefix = f"{title}\n\n"
    total_length = len(title_prefix) + len(body)
    if total_length <= max_content_length:
        return [part]

    body_size = max_content_length - len(title_prefix)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=body_size,
        chunk_overlap=0,
        separators=["\n\n", "\n", "。", "！", "？", " ", ""],
        keep_separator=False,
    )
    texts = text_splitter.split_text(body)
    return [
        {
            "title": f"{title}-{index + 1}",
            "body": text,
            "file_title": file_title,
            "parent_title": parent_title,
            "part": str(index + 1),
        }
        for index, text in enumerate(texts)
    ]


def _merge_short_part(current_parts: List[dict], min_content_length: int) -> List[dict]:
    """短段贪婪合并（旧 merge_short_part）：同父标题且长度不足时与下一段合并。"""
    if not current_parts:
        return []
    current_part = dict(current_parts[0])
    final_parts: List[dict] = []

    for next_part in current_parts[1:]:
        next_part = dict(next_part)
        same_parent = current_part.get("parent_title") == next_part.get("parent_title")
        body_len = len(current_part.get("body") or "")
        if same_parent and body_len < min_content_length:
            current_part["body"] = (
                (current_part.get("body") or "").rstrip()
                + "\n\n"
                + (next_part.get("body") or "").lstrip()
            )
            current_part["title"] = current_part.get("parent_title")
            current_part["part"] = 0
        else:
            final_parts.append(current_part)
            current_part = next_part
    final_parts.append(current_part)

    # 重编号 part（旧逻辑保留：业务上用于章节序号）
    part_counter: dict = {}
    result: List[dict] = []
    for parts in final_parts:
        if "part" in parts:
            parent_title = parts.get("parent_title")
            part_counter[parent_title] = part_counter.get(parent_title, 0) + 1
            parts["part"] = part_counter[parent_title]
        result.append(parts)
    return result


# ---------------------------------------------------------------------------
# 嵌入（旧 bge_embedding_node.py + bge_client_util.py）
# ---------------------------------------------------------------------------

_bge_model = None


def _get_bge_model():
    """BGE-M3 模型懒加载单例。惰性 import FlagEmbedding（依赖 torch，较重），
    避免 API/worker 进程在依赖未安装时于导入链上直接崩溃。

    本地模型护栏：bge_m3_path 为本地目录时设置 HF_HUB_OFFLINE=1，
    防止路径解析错误时静默从 HuggingFace 下载数 GB 模型（fail-fast 优于误下载）。
    """
    global _bge_model
    if _bge_model is None:
        from FlagEmbedding import BGEM3FlagModel  # noqa: PLC0415 - 惰性加载重型依赖

        s = get_settings()
        model_path = s.bge_m3_path
        if not os.path.isdir(model_path):
            # 硬防线：本地模型缺失直接报错，绝不回退 HF 下载（曾误下载 4.5GB）
            raise RuntimeError(
                f"BGE_M3_PATH 指向的本地模型目录不存在: {model_path}；"
                f"请检查 server/.env 的 BGE_M3_PATH（当前 server 目录: {Path(__file__).resolve().parent.parent.parent}）"
            )
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        logger.info(
            "加载本地 BGE-M3 模型: path=%s device=%s（已禁用 HF 网络访问）",
            model_path, s.bge_device,
        )
        _bge_model = BGEM3FlagModel(model_path, device=s.bge_device, use_fp16=False)
    return _bge_model


def _normalize_sparse(sparse: dict) -> dict:
    """L2 归一化稀疏向量（对齐旧 utils/normalize_sparse_vector.py）。"""
    if not sparse:
        return {}
    values = [float(v) for v in sparse.values()]
    norm = sum(v * v for v in values) ** 0.5
    if norm < 1e-9:
        return sparse
    return {int(k): v / norm for k, v in sparse.items()}


def embed_chunks(chunks: List[str]) -> tuple[List[List[float]], List[dict]]:
    """BGE-M3 批量嵌入（dense + sparse），返回 (dense_vectors, sparse_vectors)。

    sparse 键为 token_id(int)，值经 L2 归一化（对齐旧 bge_embedding_node + normalize_sparse_vector）。
    """
    if not chunks:
        return [], []
    model = _get_bge_model()
    s = get_settings()

    dense_vectors: List[List[float]] = []
    sparse_vectors: List[dict] = []
    for i in range(0, len(chunks), s.embedding_batch_size):
        batch = chunks[i:i + s.embedding_batch_size]
        result = model.encode(
            batch, return_dense=True, return_sparse=True, return_colbert_vecs=False
        )
        for dense in result["dense_vecs"]:
            dense_vectors.append(dense.tolist() if hasattr(dense, "tolist") else list(dense))
        for sp in result["lexical_weights"]:
            sparse_vectors.append(_normalize_sparse(sp or {}))
    return dense_vectors, sparse_vectors


def embed_query(query: str) -> tuple[List[float], dict]:
    """单条查询向量化（dense + sparse，kb_retrieve 用，与上传共用同一模型单例）。"""
    if not query:
        return [], {}
    model = _get_bge_model()
    result = model.encode(
        [query], return_dense=True, return_sparse=True, return_colbert_vecs=False
    )
    dense = result["dense_vecs"][0]
    dense_list = dense.tolist() if hasattr(dense, "tolist") else list(dense)
    sparse = _normalize_sparse(result["lexical_weights"][0] or {})
    return dense_list, sparse


# ---------------------------------------------------------------------------
# Milvus 插入（旧 import_milvus_node.py，改用 pymilvus 3.x MilvusClient）
# ---------------------------------------------------------------------------


def insert_chunks(client, collection: str, rows: List[dict]) -> int:
    """MilvusClient 插入 kb_chunks_v3（pk 自增不填，字段对齐 03 §4.1 / init_db.py），返回插入条数。"""
    if not rows:
        return 0
    result = client.insert(collection_name=collection, data=rows)
    return int(result.get("insert_count", 0) or 0)
