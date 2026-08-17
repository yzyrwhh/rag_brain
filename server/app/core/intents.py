"""意图枚举与路由表（对齐 04 §2.1 Supervisor 意图识别；Phase 1 先通 4 类，其余按域扩展）。"""
from enum import Enum


class Intent(str, Enum):
    KNOWLEDGE_QUERY = "knowledge_query"      # 知识问答（RAG）
    KNOWLEDGE_IMPORT = "knowledge_import"    # 知识库导入（提示走上传接口）
    GENERAL_CHAT = "general_chat"            # 闲聊/通用对话
    DEV_CONSULT = "dev_consult"              # 开发域（阶段二）
    RESEARCH_PAPER = "research_paper_search"  # 研究域（阶段二）
    LIFE_RECOMMEND = "life_recommend"        # 生活域（阶段二）
    UNKNOWN = "unclear"                      # 未识别 -> 澄清


class Domain(str, Enum):
    KNOWLEDGE = "knowledge"
    DEV = "dev"
    RESEARCH = "research"
    LIFE = "life"
    GENERAL = "general"


class RouteTarget(str, Enum):
    QA = "qa"                # 知识问答
    CHAT = "chat"            # 通用对话
    UPLOAD = "upload"        # 导入（提示前端）
    CLARIFY = "clarify"      # 澄清


# 意图 -> (domain, route target)
INTENT_ROUTES: dict[Intent, tuple[Domain, RouteTarget]] = {
    Intent.KNOWLEDGE_QUERY: (Domain.KNOWLEDGE, RouteTarget.QA),
    Intent.KNOWLEDGE_IMPORT: (Domain.KNOWLEDGE, RouteTarget.UPLOAD),
    Intent.GENERAL_CHAT: (Domain.GENERAL, RouteTarget.CHAT),
    Intent.DEV_CONSULT: (Domain.DEV, RouteTarget.CHAT),          # 阶段二落到 DevAgent
    Intent.RESEARCH_PAPER: (Domain.RESEARCH, RouteTarget.CHAT),  # 阶段二落到 ResearchAgent
    Intent.LIFE_RECOMMEND: (Domain.LIFE, RouteTarget.CHAT),      # 阶段二落到 LifeAgent
    Intent.UNKNOWN: (Domain.GENERAL, RouteTarget.CLARIFY),
}
