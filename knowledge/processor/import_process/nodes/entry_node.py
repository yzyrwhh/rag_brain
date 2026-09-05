from pathlib import Path

from knowledge.processor.import_process.base import BaseNode, T, setup_logging
from knowledge.processor.import_process.exceptions import ValidationError
from knowledge.processor.import_process.state import ImportGraphState


class EntryNode(BaseNode):
    name = "entry_node"

    def process(self, state: ImportGraphState) -> ImportGraphState:

        self.logger.info("_________________________节点一：文件类型检测_______________________")
        import_file_path = state.get("import_file_path")

        path_obj = Path(import_file_path)

        suffixe = path_obj.suffix

        if suffixe == '.pdf':
            state['is_pdf_read_enabled'] = True
            state['pdf_path'] = import_file_path
            self.logger.info("当前文件类型是PDF")
        elif suffixe == '.md':
            state['is_markdown_read_enabled'] = True
            state['md_path'] = import_file_path
            self.logger.info("当前文件类型是Markdown")
        else:
            self.logger.warning("当前文件类型是其他类型")
            raise ValidationError("文件类型不匹配")

        file_title = path_obj.stem
        state['file_title'] = file_title
        return state

if __name__ == '__main__':
    setup_logging()

    state = {
        "import_file_path": r"examples/6W100-整本手册.pdf"
    }

    node = EntryNode()

    res = node.process(state)
    print(res)

