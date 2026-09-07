import base64
import json
import os
import re
from pathlib import Path
from typing import Tuple, List, Dict, Deque
from collections import deque

from knowledge.processor.import_process.base import BaseNode, setup_logging
from knowledge.processor.import_process.config import get_config
from knowledge.processor.import_process.exceptions import ImageProcessingError
from knowledge.processor.import_process.state import ImportGraphState
from knowledge.utils.minio_utils import get_minio_client


class MdImgNode(BaseNode):
    """
        Markdown 图片处理节点。

        该节点负责处理 Markdown 文档中的本地图片，主要流程包括：
        1. 读取 Markdown 内容，定位图片存储目录。
        2. 扫描并筛选需要处理的本地图片文件。
        3. 调用多模态大模型（VLM）生成图片的文本摘要。
        4. 将图片上传至 MinIO 对象存储，并替换 Markdown 中的本地路径为远程 URL。
        5. 保存替换后的 Markdown 内容到新文件。

        Attributes:
            name (str): 节点名称，标识为 "md_img"。
    """

    name: str = "md_img"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        config = get_config()

        md_content, md_path_obj, images_dir_obj, = self._get_md_content_and_path(state)
        state["md_content"] = md_content

        if not images_dir_obj.exists():
            self.logger.info("未找到 images目录，跳过图片处理流程。")
            return state

        target_images_info = self._scan_and_filter_images(md_content, images_dir_obj, config.image_extensions)

        if not target_images_info:
            self.logger.info("未在Markdown 中找到需要处理的有效图片引用。")
            return state

        minio_client = get_minio_client()

        image_summeries = self._generate_image_summaries(
            md_path_obj.stem,
            target_images_info,
            config.requests_per_minute,
            config
        )

        new_md_content = self._upload_images_and_replace_links(
            minio_client,
            md_path_obj.stem,
            target_images_info,
            image_summeries,
            md_content,
            config
        )
        state["md_content"] = new_md_content

        new_md_file_path = self._backup_new_md_file(state["md_path"], new_md_content)
        state["md_path"] = new_md_file_path

        return state


    def _get_md_content_and_path(self, state: ImportGraphState) -> Tuple[str,Path, Path]:
        self.log_step("step_1","读取文件内容")

        md_file_path_str = state.get("md_path")
        if not md_file_path_str:
            raise ImageProcessingError("state中md_path为空",node_name=self.name)
        md_path_obj = Path(md_file_path_str)
        try:
            with open(md_path_obj, "r", encoding="utf-8") as f:
                md_content = f.read()
        except IOError as e:
            raise ImageProcessingError(
                f"无法读取文件 {md_path_obj}：{e}"
            )

        images_dir_obj = md_path_obj.parent / "images"
        return md_content, md_path_obj, images_dir_obj

    def _scan_and_filter_images(self,
                                md_content: str,
                                images_dir_obj: Path,
                                allowed_extensions: set
                                ) -> List[Tuple[str, str, Tuple[str, str, str]]]:

        self.log_step("step2",f"扫描图片目录:{images_dir_obj}")
        target_images = []

        for image_filename in os.listdir(images_dir_obj):
            file_ext = os.path.splitext(image_filename)[1].lower()
            if file_ext not in allowed_extensions:
                continue

            image_full_path = str(images_dir_obj / image_filename)
            contexts_list = self._find_image_context_in_md(md_content,image_filename)
            if not contexts_list:
                self.logger.debug(f"图片 {image_filename} 未在文档中被引用，跳过。")
                continue

            primary_context = contexts_list[0]
            target_images.append((image_filename, image_full_path, primary_context))
        self.logger.info(f"找到 {len(target_images)} 张需要处理的有效图片。")
        return target_images

    def _find_image_context_in_md(
            self,
            md_content: str,
            image_filename: str,
            max_chars: int = 100
        ) -> List[Tuple[str, str, str]]:
        self.log_step("step3", f"基于 Markdown 语义结构查找图片的上下文")

        lines = md_content.split("\n")

        image_pattern = re.compile(
            r"!\[.*?\]\(.*?" + re.escape(image_filename) + r".*?\)"
        )

        contexts_list = []

        for line_idx ,line in enumerate(lines):###########################文档内容搜索######################
            if not image_pattern.search(line):
                continue

            section_heading = ""
            heading_line_idx = -1

            for i in range(line_idx -1,-1,-1):
                if re.match(r"^#{1,6}\s+", lines[i]):
                    section_heading = lines[i].strip()
                    heading_line_idx = i
                    break
            pre_start = heading_line_idx + 1 if heading_line_idx >= 0 else 0
            pre_lines = lines[pre_start:line_idx]
            pre_paragraphs = self._extract_paragraphs_with_limit(
                pre_lines, max_chars, direction="backward"
            )

            next_heading_idx = len(lines)
            for i in range(line_idx + 1, len(lines)):
                if re.match(r"^#{1,6}\s+", lines[i]):
                    next_heading_idx = i
                    break
            post_lines = lines[line_idx + 1:next_heading_idx]
            post_paragraphs = self._extract_paragraphs_with_limit(
                post_lines, max_chars, direction="forward"
            )

            contexts_list.append((section_heading, pre_paragraphs, post_paragraphs))

        return contexts_list

    def _extract_paragraphs_with_limit(
            self,
            lines: List[str],
            max_chars: int,
            direction: str=  "forward"
        ) -> str:
        self.log_step("step4", f"从给定的行列表中提取完整段落，总字符数不超过 max_chars")

        paragraphs = []
        currnt_para = []

        for line in lines:
            stripped = line.strip()
            if stripped == "":
                if currnt_para:
                    paragraphs.append("\n".join(currnt_para))
                    currnt_para = []
            else:
                if re.match(r"^!\[.*?\]\(.*?\)$", stripped):
                    if currnt_para:
                        paragraphs.append("\n".join(currnt_para))
                        currnt_para = []
                    continue
                currnt_para.append(stripped)

        if currnt_para:
            paragraphs.append("\n".join(currnt_para))

        paragraphs = [p for p in paragraphs if p.strip() ]

        if not paragraphs:
            return ""

        if direction == "backward":
            paragraphs = list(reversed(paragraphs))

        selected = []
        total_chars = 0
        for para in paragraphs:
            para_len = len(para)
            if total_chars + para_len > max_chars and selected: #################非空校验（多处出现需梳理逻辑）#################
                break
            selected.append(para)
            total_chars += para_len
        if direction == "backward":
            selected = list(reversed(selected))

        return "\n\n".join(selected)



    def _generate_image_summaries(
            self,
            document_stem: str,
            target_images_info:List[Tuple[str, str, Tuple[str, str, str]]],
            requests_per_minute: int,
            config
        ) -> Dict[str, str]:
        self.log_step("step3", "为图片生成内容摘要")

        image_summaries = {}
        request_timestamps: Deque[float] = deque()

        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=config.openai_api_key,
                base_url=config.openai_api_base
            )
        except ImportError:
            self.logger.error("未安装 openai 库，无法初始化 VL 客户端。")
            return image_summaries
        except Exception as e:
            self.logger.error(f"初始化 VL 客户端失败: {e}")
            return image_summaries

        for image_filename, image_full_path, context_tuple in target_images_info:
            self.logger.debug(f"正在生成摘要: {image_filename}")

            summary_text = self._call_vlm_for_summary(
                client,
                config.vl_model,
                image_full_path,
                document_stem,
                context_tuple
            )
            image_summaries[image_filename] = summary_text

        return image_summaries

    def _call_vlm_for_summary(
            self,
            client,
            model_name: str,
            image_path: str,
            doc_title: str,
            context_tuple
        )-> str:
        self.log_step("step#", "调用多模态模型生成内容")

        try:
            with open(image_path, "rb") as f:
                base64_bytes = base64.b64encode(f.read()).decode("utf-8")
        except IOError as e:
            self.logger.error(f"无法读取图片文件{image_path}：{e}")
            return "图片读取失败"

        section_heading, pre_text, post_text = context_tuple
        context_parts = []
        if section_heading:
            context_parts.append(f"所属章节标题：{section_heading}")
        if pre_text:
            context_parts.append(f"图片上文：{pre_text}")
        if post_text:
            context_parts.append(f"图片下文：{post_text}")

        context_info = "\n".join(context_parts) if context_parts else "无可用上下文"
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"""任务：提取这张图片中的全部文字内容，按阅读顺序逐行输出。
        背景信息：
        1. 所属文档标题："{doc_title}"
        2. 图片上下文：
           {context_info}
        要求：忠实提取图中所有可见文字（标题、说明、标注、表格文字等），按阅读顺序输出，不遗漏；禁止添加图中没有的信息，禁止推断、解释或总结；如果图中没有任何文字，输出"图中无文字"。
        """,
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_bytes}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=800,
                temperature=0.3
            )
            summary = response.choices[0].message.content.strip().replace("\n", " ")
            return summary
        except Exception as e:
            self.logger.warning(f"图片摘要生成失败 {image_path}: {e}")
            return "图片"

    def _upload_images_and_replace_links(
            self,
            minio_client,
            document_stem: str,
            target_images_info: List[Tuple[str, str, Tuple[str, str, str]]],
            image_summaries: Dict[str, str],
            md_content: str,
            config
        ) -> str:
        self.log_step("step4", "将图片上传至 MinIO 并替换 Markdown 中的本地链接")

        uploaded_urls = {}
        for image_filename, image_full_path, _ in target_images_info:
            object_name = f"{document_stem}/{image_filename}"

            ext = os.path.splitext(image_full_path)[1].lower()
            content_type = f"image/{ext[1:]}" if ext.startswith(".") else "application/octet-stream"

            if minio_client:
                try:
                    minio_client.fput_object(      ###################################minIO 上传##################################
                        #
                        config.minio_bucket,
                        object_name,
                        image_full_path,
                        content_type=content_type
                    )
                    remote_url = f"{config.get_minio_base_url()}/{object_name}"
                    uploaded_urls[image_filename] = remote_url
                    self.logger.info(f"图片上传成功: {image_filename} -> {remote_url}")
                except Exception as e:
                    self.logger.warning(f"图片上传失败 {image_filename}: {e}")
            else:
                self.logger.warning("MinIO 客户端未初始化，跳过实际上传。")
                uploaded_urls[image_filename] = \
                    f"http://mock-minio/{document_stem}/{image_filename}"

        new_md_content = md_content
        for image_filename, summary_text in image_summaries.items():     ######################## 文中内容替换#######################
            remote_url = uploaded_urls.get(image_filename)
            if not remote_url:
                continue

            replace_pattern = re.compile(
                r"!\[(.*?)\]\((.*?" + re.escape(image_filename) + r".*?)\)",
                re.IGNORECASE
            )
            # alt 保留提取文字前 20 字（简短），正文插入完整提取文字段落
            summary_clean = summary_text.strip().replace("\n", " ")
            alt_text = summary_clean[:20] if summary_clean and summary_clean != "图中无文字" else "图片"
            image_block = f"![{alt_text}]({remote_url})"
            if summary_clean and summary_clean != "图中无文字":
                image_block += f"\n\n【图片内容】{summary_clean}\n"
            new_md_content = replace_pattern.sub(
                lambda m: image_block,
                new_md_content
            )

        self.logger.info(f"成功替换了 {len(uploaded_urls)} 张图片的链接。")
        return new_md_content

    def _backup_new_md_file(
            self,
            original_md_path_str: str,
            new_md_content: str
    ) -> str:

        self.log_step("step_5", "备份新文件")

        original_path = Path(original_md_path_str)
        new_file_path = original_path.with_name(
            f"{original_path.stem}_new{original_path.suffix}"
        )

        try:
            with open(new_file_path, "w", encoding="utf-8") as f:
                f.write(new_md_content)
            self.logger.info(f"处理后的文件已备份至: {new_file_path}")
        except IOError as e:
            self.logger.error(f"写入新文件失败 {new_file_path}: {e}")
            raise ImageProcessingError(f"文件写入失败: {e}", node_name=self.name)

        return str(new_file_path)

node_md_img = MdImgNode()

if __name__ == '__main__':
    # 1. 开启日志
    setup_logging()

    # 2. 构建处理图片节点的状态
    img_state = {
        "md_path": r"examples/6W100-整本手册.md"
    }
    # 3. 处理 md 图片节点
    processed_img_result = node_md_img.process(img_state)

    # 4. 打印结果
    processed_img_result_str = json.dumps(
        processed_img_result,
        indent=4,
        ensure_ascii=False
    )
    print(processed_img_result_str)