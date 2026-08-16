"""LLM/VLM 客户端（OpenAI 兼容，DashScope；对齐 07 §7.1 统一封装与旧 md_img/item_name 调用方式）。

- chat_json: JSON 模式文本抽取（实体/主题/标签等结构化输出）
- vlm_image_summary: 图片 base64 + 上下文 → 中文摘要（旧 MdImgNode._call_vlm_for_summary 的移植）
"""
import base64
import json
import re

from openai import OpenAI

from app.core.config import get_settings


def get_openai_client() -> OpenAI:
    s = get_settings()
    # 统一超时（30s），防止 LLM 调用挂死拖垮请求（曾出现 ask 请求无限等待）
    return OpenAI(api_key=s.openai_api_key, base_url=s.openai_api_base, timeout=30.0)


def _extract_json(text: str) -> str:
    """从响应文本中提取 JSON（兼容代码块包裹/前导噪音）。"""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def chat_json(system: str, user: str, model: str | None = None, max_tokens: int = 500) -> dict:
    """JSON 模式文本调用（qwen-flash 等），失败抛异常由调用方降级。"""
    s = get_settings()
    client = get_openai_client()
    resp = client.chat.completions.create(
        model=model or s.entity_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=max_tokens,
        extra_body={"response_format": {"type": "json_object"}},
    )
    text = resp.choices[0].message.content or "{}"
    return json.loads(_extract_json(text))


def chat_text(system: str, user: str, model: str | None = None, max_tokens: int = 1024) -> str:
    """普通文本调用（知识问答等），失败抛异常由调用方降级。"""
    s = get_settings()
    client = get_openai_client()
    resp = client.chat.completions.create(
        model=model or s.qa_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def vlm_image_summary(image_path: str, doc_title: str, context: str) -> str:
    """图片 + 上下文 → 中文标题（对齐旧 MdImgNode；失败返回兜底文案不抛错）。"""
    s = get_settings()
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
    except OSError:
        return "图片"

    try:
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=s.vl_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "任务：为 Markdown 文档中的图片生成一个简短的中文标题。\n"
                                f"背景信息：\n1. 所属文档标题：\"{doc_title}\"\n"
                                f"2. 图片上下文：\n{context or '无可用上下文'}\n"
                                "请结合图片视觉内容和上述上下文信息，用中文简要总结这张图片的内容，"
                                "生成一个精准的中文标题（不要包含\"图片\"二字）。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=100,
            temperature=0.3,
        )
        summary = (resp.choices[0].message.content or "").strip().replace("\n", " ")
        return summary or "图片"
    except Exception:
        return "图片"
