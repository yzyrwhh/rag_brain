import json
from typing import List, Dict

from knowledge.front.utils.task_utils import set_task_result
from knowledge.processor.query_process.base import BaseNode
from knowledge.processor.query_process.config import get_config
from knowledge.processor.query_process.state import QueryGraphState
from knowledge.prompt.querry.answer_prompt import ANSWER_PROMPT
from knowledge.tools.llm_tool import get_llm_client
from knowledge.tools.mongo_history_tool import save_chat_message
from knowledge.front.utils.sse_tool import push_to_session, SSEEvent



class AnswerOutputNode(BaseNode):
    name = "answer_output"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        task_id = state.get("task_id")
        is_stream = state.get("is_stream")

        # Step 1: 已有答案（如商品确认提示）→ 直接推送
        if state.get("answer"):
            self._push_existing_answer(state)
        else:
            # Step 2-7: 构建提示词 → 生成答案
            prompt = self._build_prompt(state)
            state["prompt"] = prompt
            self._generate(state, prompt)

        # Step 8: 写入历史
        if state.get("answer"):
            self._write_history(state)
            # 收集引用来源（供前端展示）
            sources = self._collect_sources(state)
            # Step 9: 流式模式发送结束事件
            if is_stream:
                push_to_session(
                    task_id,
                    SSEEvent.FINAL,
                    {
                        "answer": state.get("answer", ""),
                        "status": "completed",
                        "sources": sources,
                    }
                )
            else:
                set_task_result(task_id, "sources", json.dumps(sources, ensure_ascii=False))

        return state

    def _collect_sources(self, state: QueryGraphState) -> List[Dict]:
        """从重排文档 / 网页检索结果中收集引用来源。"""
        sources: List[Dict] = []
        seen: set = set()

        docs = list(state.get("reranked_docs") or []) + list(state.get("web_search_docs") or [])
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            url = str(doc.get("url") or "").strip()
            chunk_id = str(doc.get("chunk_id") or "").strip()
            key = url or chunk_id or (doc.get("title") or "")[:40]
            if not key or key in seen:
                continue
            seen.add(key)
            item = {
                "title": (doc.get("title") or doc.get("source") or "").strip(),
                "source": (doc.get("source") or "").strip(),
                "url": url,
                "chunk_id": chunk_id,
                "score": doc.get("score"),
            }
            sources.append(item)
            if len(sources) >= 10:
                break

        return sources

    def _push_existing_answer(self, state: QueryGraphState):
        """将已有答案推送到流或任务结果。"""
        answer = state["answer"]
        if state.get("is_stream"):
            push_to_session(state["task_id"],SSEEvent.DELTA, {"delta": answer})
        else:
            set_task_result(state["task_id"], "answer", answer)


    def _build_prompt(self, state: QueryGraphState) -> str:
        """根据检索结果、历史对话、图谱关系组装 LLM 提示词。"""
        config = get_config()
        budget = config.max_context_chars
        question = state.get("rewritten_query") or state.get("original_query", "")
        item_names = state.get("item_names") or []

        # Step 3: 格式化检索文档
        context_str, budget = self._format_docs(
            state.get("reranked_docs") or [], budget
        )

        # Step 4: 格式化历史对话
        history_str, budget = self._format_history(
            state.get("history") or [], budget
        )

        # Step 6: 组装完整提示词
        return ANSWER_PROMPT.format(
            context=context_str or "无参考内容",
            history=history_str or "无历史对话",
            item_names=", ".join(item_names) if item_names else "无指定商品",
            question=question,
        )



    def _format_docs(self, docs: List[Dict], budget: int) -> tuple:  ########################################
        """格式化重排序文档，带字符预算控制。"""
        lines = []
        used = 0

        for i, doc in enumerate(docs, 1):
            text = (doc.get("text") or "").strip()
            if not text:
                continue

            meta = [f"[{i}]"]

            for key, fmt in [
                ("source", "[{}]"), ("chunk_id", "[chunk_id={}]"),
                ("url", "[url={}]"), ("title", "[title={}]"),
            ]:
                val = str(doc.get(key) or "").strip()
                if val:
                    meta.append(fmt.format(val))

            score = doc.get("score")
            if score is not None:
                meta.append(f"[score={float(score):.4f}]")

            doc_str = " ".join(meta) + "\n" + text
            if used + len(doc_str) > budget:
                break

            lines.append(doc_str)
            used += len(doc_str) + 2

        return "\n\n".join(lines), budget - used



    @staticmethod
    def _format_history(history: List[Dict], budget: int) -> tuple:
        """格式化历史对话。"""
        lines = []
        used = 0

        for msg in history:
            for role, key in [("用户", "user"), ("助手", "assistant")]:
                text = msg.get(key)
                if not text:
                    continue

                line = f"{role}: {text}"
                used += len(line) + 1
                if used > budget:
                    return "\n".join(lines), budget - used
                lines.append(line)

        return "\n".join(lines), budget - used

    def _generate(self, state: QueryGraphState, prompt: str):
        """调用 LLM 生成答案（流式/非流式）。"""
        self.log_step("generate", "生成答案")
        llm = get_llm_client()
        task_id = state.get("task_id")

        if state.get("is_stream"):
            state["answer"] = self._stream_generate(llm, prompt, task_id)
        else:
            state["answer"] = self._invoke_generate(llm, prompt, task_id)

    def _stream_generate(self, llm, prompt: str, task_id: str) -> str:
        """流式生成，逐 chunk 推送。"""
        result = ""
        try:
            for chunk in llm.stream(prompt):
                delta = getattr(chunk, "content", "") or ""
                if delta:
                    result += delta
                    push_to_session(task_id, "delta", {"delta": delta})
        except Exception as e:
            self.logger.error(f"流式生成出错: {e}")
        return result


    def _invoke_generate(self, llm, prompt: str, task_id: str) -> str:
        """非流式生成。"""
        try:
            response = llm.invoke(prompt)
            answer = response.content
            set_task_result(task_id, "answer", answer)
            return answer
        except Exception as e:
            self.logger.error(f"生成回答出错: {e}")
            return "抱歉，生成回答时出现错误。"

    def _write_history(self, state: QueryGraphState):
        """将助手回答写入 Mongo 历史记录。"""
        answer = (state.get("answer") or "").strip()
        if not answer:
            return
        try:
            save_chat_message(
                session_id=state.get("session_id", "default"),
                role="assistant",
                text=answer,
                rewritten_query="",
                item_names=state.get("item_names") or [],
            )
        except Exception as e:
            self.logger.warning(f"写入历史记录失败: {e}")

# 兼容入口
anwser_output = AnswerOutputNode()


def answer_output(state: QueryGraphState) -> QueryGraphState:
    """兼容原有调用方式的入口函数。"""
    return answer_output(state)

if __name__ == "__main__":
    from dotenv import load_dotenv

    # 加载环境变量
    load_dotenv()

    # 初始化日志
    from knowledge.processor.query_process.base import setup_logging
    setup_logging()

    print("=" * 60)
    print("开始测试: 答案生成节点 (AnswerOutputNode)")
    print("=" * 60)

    # 构造模拟状态
    mock_state = {
        "session_id": "test_session_001",
        "is_stream": False,  # 非流式测试
        "original_query": "万用表怎么测电压？",
        "rewritten_query": "RS-12数字万用表如何测量电压？",
        "item_names": ["RS-12数字万用表"],
        "reranked_docs": [
            {
                "text": "数字万用表测量电压步骤：1. 将旋钮转到V档位；2. 黑表笔插COM孔，红表笔插V孔；3. 将表笔并联到被测点两端。",
                "source": "local",
                "chunk_id": "chunk_001",
                "title": "万用表使用手册",
                "score": 0.9234
            },
            {
                "text": "测量直流电压时需注意正负极性，红表笔接正极，黑表笔接负极。",
                "source": "web",
                "url": "https://example.com/guide",
                "title": "电压测量指南",
                "score": 0.8756
            }
        ],
        "history": [
            {"user": "万用表是什么？", "assistant": "万用表是一种多功能电子测量仪器..."}
        ]
    }

    print("【输入状态】:")
    print(f"  query: {mock_state['rewritten_query']}")
    print(f"  item_names: {mock_state['item_names']}")
    print(f"  reranked_docs: {len(mock_state['reranked_docs'])} 篇")
    print("-" * 60)

    # 执行答案生成
    result = answer_output(mock_state)

    # 打印结果
    print("\n【生成结果】:")
    print("-" * 60)
    print(result.get("answer", "无答案"))
    print("-" * 60)

    # 打印提示词（调试用）
    if result.get("prompt"):
        print("\n【构建的提示词】:")
        print(result["prompt"][:500] + "...")

    print("\n测试完成")





