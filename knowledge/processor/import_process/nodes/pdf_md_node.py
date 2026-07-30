import os
import subprocess
import time
from pathlib import Path
from typing import Tuple

from knowledge.processor.import_process.base import BaseNode
from knowledge.processor.import_process.exceptions import PdfConversionError, FileProcessingError
from knowledge.processor.import_process.state import ImportGraphState


class PdfToMdNode(BaseNode):
    name = "pdf_to_md"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        self.logger.info("_________________________节点二：PDF转md_______________________")
        pdf_path_obj,output_dir_obj = self._validate_param(state)

        process_code = self._execute_mineru(pdf_path_obj, output_dir_obj)

        if process_code != 0:
            raise PdfConversionError("pdf转换失败",node_name=self.name)

        md_path = self._get_md_path(pdf_path_obj, output_dir_obj)
        state["md_path"] = md_path
        return state
        pass

    def _get_md_path(self, pdf_path_obj: Path, output_dir_obj: Path) -> str:
        file_stem = pdf_path_obj.stem
        #md_path = output_dir_obj.joinpath(file_stem + ".md")
        md_path = output_dir_obj / file_stem / "auto" / f"{file_stem}.md"
        return str(md_path)

    def _validate_param(self,
                        state: ImportGraphState) -> Tuple[Path, Path]:

        pdf_path = state.get("pdf_path")
        if not pdf_path:
            raise FileProcessingError("pdf_path为空",node_name=self.name)
        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            raise FileProcessingError(f"{pdf_path_obj} 不存在")

        md_path = state.get("md_path")
        if not md_path:
            md_path = pdf_path_obj.parent
        md_path_obj = Path(md_path)

        return pdf_path_obj,md_path_obj

    def _execute_mineru(self, pdf_path_obj: Path, output_dir_obj: Path) -> int:

        self.logger.info("===========================开始转换==================================")

        self.logger.info("开始执行 MinerU 转换")
        self.logger.info(f"PDF 路径: {pdf_path_obj}")
        self.logger.info(f"输出目录: {output_dir_obj}")


        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        os.environ["HF_HOME"] = r"D:\software\mineru"
        os.environ["MODELSCOPE_CACHE"] = r"D:\software\mineru"

        cmd = [
            "mineru",
            "-p",str(pdf_path_obj),
            "-o",str(output_dir_obj),
            "--source","local",
            "--device","cpu",
            "--backend","pipeline",
            "--batch-size","1",
            "--no-auto-download"
        ]

        self.logger.info(f"执行命令：{cmd}")
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
        for line in proc.stdout:
            self.logger.debug(f"[mineru] {line.rstrip()}")


        proc_code = proc.wait()
        elapsed = time.time() - start_ts
        if proc_code == 0:
            self.logger.info(f"PDF conversion took {elapsed} elapses to complete successfully ")
        else:
            self.logger.error("pdf failed")

        return proc_code

if __name__ == "__main__":

    state = {
        "pdf_path": r"D:\folder\course\SGG\掌柜智库项目\资料\2-文档\pdf文档\doc\6W100-整本手册.pdf",
    }
    node = PdfToMdNode()
    res = node.process(state)
    print(res)

    from knowledge.processor.import_process.base import setup_logging

    setup_logging()

    state = {
        "pdf_path": r"D:\folder\course\SGG\掌柜智库项目\资料\2-文档\pdf文档\doc\6W100-整本手册.pdf",
        "md_path": r"D:\folder\course\SGG\掌柜智库项目\资料\2-文档\markdown文档"
    }
    node = PdfToMdNode()
    res = node.process(state)
    print(f"转换完成，MD 文件: {res.get('md_path')}")