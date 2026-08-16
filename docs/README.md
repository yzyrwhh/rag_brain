# 掌柜智库 · 多智能体系统设计文档

> 目标：将现有"文档上传 + 商品查询"的 RAG 工作流系统，重构为一个**多用户、多域、可扩展的多智能体平台**，并按软件工程规范（需求 → 架构 → 领域模型 → 数据 → 前后端 → LLM 工程 → 测试 → 路线图）全过程落地。
>
> 本文档为设计总览，是整套设计文档的入口。

## 1. 项目定位

**掌柜智库（Shopkeeper Brain）** 是一个个人/家庭级多智能体助理平台，围绕四个能力域：

| 能力域 | 智能体 | 核心能力 | 状态 |
| :--- | :--- | :--- | :--- |
| 知识域 | KnowledgeAgent | 多格式文档导入、统一混合检索 RAG、知识库管理 | 现有资产，需重构 |
| 开发域 | DevAgent | 技术方案咨询、代码生成/审查、开发案例与技术栈经验沉淀 | 新增 |
| 研究域 | ResearchAgent | 指定领域论文检索、筛选评估、入库、综述生成 | 新增 |
| 生活域 | LifeAgent | 外卖/买菜/网购的需求理解、比价推荐、购物清单、外链跳转 | 新增（不代下单） |

## 2. 文档地图（建议阅读顺序）

| 文档 | 内容 | 依赖 |
| :--- | :--- | :--- |
| [01-需求分析与范围](./01-需求分析与范围.md) | 干系人、用户故事、功能/非功能需求、边界 | 无 |
| [02-系统架构与部署](./02-系统架构与部署.md) | 分层架构、任务执行模型、技术选型、部署、安全 | 01 |
| [03-领域模型与数据设计](./03-领域模型与数据设计.md) | 限界上下文、实体、Mongo/Milvus/Redis/MinIO 设计 | 01, 02 |
| [04-多智能体编排设计](./04-多智能体编排设计.md) | Supervisor/Worker/Planner/Critic、工具注册(MCP)、记忆系统 | 02, 03 |
| [05-API与实时协议设计](./05-API与实时协议设计.md) | REST API、任务/事件协议、SSE/WebSocket、错误码 | 03, 04 |
| [06-前端与CLI设计](./06-前端与CLI设计.md) | Web SPA 页面、任务可视化、SSE 客户端、CLI | 05 |
| [07-LLM工程与可观测性](./07-LLM工程与可观测性.md) | 模型选型矩阵、提示词规范、结构化输出、评测、成本、LangSmith | 02, 04 |
| [08-实施路线图与测试策略](./08-实施路线图与测试策略.md) | 里程碑、迁移策略、测试金字塔、风险登记册 | 01–07 |

## 3. 关键架构决策（ADR 摘要）

| # | 决策 | 结论 | 理由 |
| :--- | :--- | :--- | :--- |
| ADR-001 | 多智能体框架 | **LangGraph + LangSmith** | 与现有 import/query 图无缝融合；SubGraph 天然支持 Supervisor 嵌套 Worker；LangSmith 提供全链路 trace（复杂 agent 调试刚需） |
| ADR-002 | 用户模型 | **直接做多用户** | 所有数据带 `user_id`/`space_id`，从第一天避免单用户重构成本；登录用 JWT |
| ADR-003 | 生活域执行边界 | **推荐 + 清单 + 外链跳转**，不代下单 | 规避支付合规与开放平台资质门槛；下单动作由用户在美团/京东等完成 |
| ADR-004 | 前端形态 | **Web SPA + CLI 双入口** | Web 承载完整可视化（任务树、人机回环）；CLI 用于快速调试 agent 编排与自动化脚本 |
| ADR-005 | 任务执行模型 | **同步 SSE（快任务）+ Celery 异步队列（慢任务）** | 多用户 + 长任务（论文综述等）必须有可靠队列、重试、中断恢复；现有内存 task_utils 不可用 |
| ADR-006 | 知识存储 | **统一知识切片集合 + 域标签 + 空间隔离** | 合并现有 `kb_chunks_v2`/`item_names`/`entity_names` 碎片，用 `domain` 字段分域检索，`space_id` 隔离 |
| ADR-007 | 工具集成 | **MCP 标准的工具注册中心** | 工具动态注册/按需装载；DashScope MCP、自研知识工具、第三方 API 统一接入 |
| ADR-008 | 记忆系统 | **四类记忆：工作/情景/语义/程序** | 工作记忆在图状态；情景=任务消息历史；语义=可编辑长期事实（向量+结构化）；程序=Agent 技能与提示词 |
| ADR-009 | 代码执行 | **Docker 沙箱（阶段二）** | DevAgent 的代码运行/审查需要隔离执行环境，先不开放任意本机执行 |
| ADR-010 | LLM 提供商 | **阿里云百炼（DashScope 兼容模式）为主，本地 BGE 嵌入/重排为辅** | 现有资产；兼容 OpenAI 协议便于切换 |
| ADR-011 | 知识图谱 | **引入 Neo4j 存储实体/关系，与向量检索互补（FR-26）** | 技术栈脑图、多跳检索、引用网络超出纯向量召回的表达力 |
| ADR-012 | 全文与原件 | **片段召回 + 全文/原件双通道（FR-27）** | 综述/精读需整篇加载；原件经 MinIO 预签名提供查看与下载 |
| ADR-013 | 外部 Agent | **MCP/子进程桥接第三方 Agent（Claude Code 等，FR-28）** | 复用更专业的外部智能体，产出回流为经验库 |
| ADR-014 | 数据访问 | **数据服务层（数据中台）统一收口** | Agent 不直连存储；隔离/审计/缓存单点强制，杜绝越权遗漏 |
| ADR-015 | 记忆维护 | **定时整理任务（夜间）驱动记忆生命周期（FR-29）** | 情景→语义沉淀、去重、衰减、新旧更替，避免记忆库腐化 |
| ADR-016 | 记忆架构 | **采用 L0-L3 分层记忆 + 渐进召回 + 经验资产化（借鉴 TencentDB-Agent-Memory）** | 分层沉淀避免记忆膨胀；稳定/动态分离 + 召回预算省 token；经验/Skill 版本化可治理 |
| ADR-017 | 设计知识 | **设计流程/ADR/复盘作为一等知识资产自存储（FR-33）** | 让"如何设计系统"的经验可被未来设计任务召回，形成设计复利 |
| ADR-018 | 路线选择 | **求稳优先（路线 A）：MVP 只做"多域 Agent + 检索 + L0/L1 显式记忆 + 经验 Skill"；图谱/自动整理/外部 Agent 均以评测或需求验证为门禁后置** | 单人可交付优先；"做不完/做不精"是最大失败模式，用门禁让系统自己决定要不要上重活 |

## 4. 与 plan.md 的关系

根目录 `plan.md` 是初版草案。本系列文档是其**深化与可执行化**：保留"五层架构、Supervisor-Worker、黑板模式、MCP、人机回环、避免过度工程"的判断，补充了需求工程、领域模型、数据库 schema、任务执行基础设施、API 协议、评测与路线图等落地细节。plan.md 中的结论在本系列中均有对应章节，可直接对照。

## 5. 术语表

| 术语 | 含义 |
| :--- | :--- |
| 智能体（Agent） | 一个具备角色提示词 + 工具集 + 编排逻辑的 LangGraph 子图/节点组 |
| Supervisor | 主管智能体：意图识别、任务分发、结果汇总 |
| Worker | 域智能体：Knowledge/Dev/Research/Life |
| Planner / Critic | 规划器（任务分解）/ 反思器（质量评审与重试） |
| 空间（Space） | 知识库隔离单位（个人空间/共享空间） |
| 任务（Task） | 一次智能体执行单元，有状态机与事件流 |
| 人机回环（HITL） | Agent 执行中需要用户确认/澄清的交互点 |
| 工具注册中心 | 基于 MCP 的插件化工具管理 |
| 记忆（Memory） | 工作/情景/语义/程序四类长期状态 |
| 数据服务层（数据中台） | 统一数据访问层：Agent/服务不直连存储，隔离/审计/缓存单点强制 |
| 图谱检索 | Neo4j 实体/关系检索 + 向量检索互补（多跳、脑图、引用网络） |
| 全文访问 | 整篇文档读取（Agent 加载）与原件查看/下载（预签名 URL） |
| 经验闭环 | 经验去重、新旧更替（supersedes）、使用反馈驱动自迭代 |
| 点子捕获 | 多轮对话中想法/困惑的结构化存储，关联 Paper/文档 |
| 进展恢复 | 跨会话找回"上次学到哪/上次的想法"（FR-30） |
| 记忆资产 | Chat Memory / Skill / Wiki / CodeGraph 的统一登记单元（Owner/版本/状态/可见性） |
| Loadout | 给某个 Agent 装配的记忆资产集合（Fixed Binding + ACL） |
| 渐进召回 | L0-L3 分层：稳定部分常驻、动态部分按查询召回、预算硬约束 |
| Skill 资产 | 版本化可执行经验：版本+资源+触发边界+步骤+验证规则（非纯文本） |
| 任务拓扑 | 用 Mermaid 状态机记录任务目标/进度/阻塞点（认知墓碑） |

## 6. 参考文献与借鉴项目

> 设计过程中参考的成熟方案与论文；每条"借鉴点"已落位到对应章节。研读建议顺序：**CoALA（记忆分类法）→ MemGPT（上下文管理）→ TencentDB-Agent-Memory（工程实现）→ Agent Workflow Memory（程序记忆自动化）**，每读一个回查"落位"对照我们的取舍。

### 论文

| 参考 | 类型 | 借鉴点 | 落位 |
| :--- | :--- | :--- | :--- |
| [CoALA: Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427) | 记忆分类框架 | 工作/情景/语义/程序四类记忆的标准化定义 | 04 §7.1 |
| [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) | 上下文管理 | 虚拟上下文分页、层级记忆 → 上下文压缩/归档策略 | 03 §10.3 |
| [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442) | 反思机制 | 记忆流 + 反思 + 检索评分（recency/importance/relevance） | 03 §10.1 |
| [Agent Workflow Memory (ICML 2025)](https://openreview.net/forum?id=NTAhi2JEEE) | 程序记忆自动化 | 从轨迹自动提炼可复用工作流 → Skill 资产化的进阶方向 | 04 §7.2 |
| [Rethinking Memory Mechanisms of Foundation Agents](https://arxiv.org/abs/2602.06052) / [Memory for Autonomous LLM Agents](https://arxiv.org/abs/2603.07670) / [Memory in the Age of AI Agents](https://arxiv.org/abs/2512.13564) | 记忆综述 | 记忆机制全景与评估维度 | 07 §4 |
| [A Survey of Self-Evolving Agents](https://arxiv.org/abs/2507.21046) | 自演化 | 经验积累/质量闭环 → 自迭代的理论支撑 | 03 §10.6 |
| [Graph Retrieval-Augmented Generation: A Survey (ACM TOIS)](https://dl.acm.org/doi/10.1145/3777378) / GraphRAG / HippoRAG / LightRAG / KAG | 图谱 RAG | 图+向量混合检索、社区摘要（GraphRAG 阶段二） | 03 §8.4 |
| Self-RAG / CRAG | 检索增强 | 按需检索、检索质量校验 → Critic 与 GuardAgent 参考 | 04 §4.3 |

### 开源项目

| 项目 | 说明 | 借鉴点 | 落位 |
| :--- | :--- | :--- | :--- |
| TencentDB-Agent-Memory（已本地研读） | 腾讯开源，L0-L3 分层记忆 + Skill + 资产治理 | 分层沉淀、渐进召回、任务延续 L1.5、生成溯源 | 03 §10、04 §7 |
| LangMem（LangChain 官方记忆 SDK） | 记忆提取/优化，与 LangGraph 同生态 | 记忆提取 pipeline 实现参考（同为 Python 生态） | 04 §7 实施参考 |
| Mem0 | 双层记忆（短期/长期）+ 提取-存储-检索 API | API 形态与记忆提取触发策略对比 | 04 §7 实施参考 |
| Zep / Graphiti | 时序知识图谱记忆 | 实体+关系+时间戳的记忆图谱 → Neo4j 图记忆通道参考 | 03 §8 |
| Letta（MemGPT 开源版） | 记忆层级 + 上下文分页 | 长期会话的上下文管理对比 | 03 §10.3 |
| Cognee | 记忆 + 知识图谱 + RAG 一体化 | 一体化数据层设计对比（防过度设计对照） | 02 §9 |

### 本地源码可复用资产（根目录 `mem0/` 与 `TencentDB-Agent-Memory/`）

| 资产 | 复用方式 | 说明 |
| :--- | :--- | :--- |
| **mem0 `Memory` 类**（`mem0/mem0/memory/main.py`） | **直接跑**：包一层 `memory_service` 实现 L1 记忆（add/search/get_all/update/delete，sync+async） | vector_store 支持 **Milvus**（我们现有存储）；llm/embedder 走 OpenAI 兼容（qwen / text-embedding-v4 直接用）；规避自研 L1 抽取 pipeline |
| mem0 提取 prompt 与 schema | 抄 | "消息→事实条目"提取设计（注意配置成显式写入为主，防 R13 噪音） |
| **TencentDB MemoryCore Gateway + Python SDK**（`sdk/memory-core/python`） | 可选 sidecar：跑 Gateway（:8420）+ SDK 接入 v3 数据面 | 白嫖完整 L0-L3 + 任务拓扑 + Skill；代价：Node 服务 + SQLite 数据目录 + team/agent/user 四元组映射；**Route A 下等记忆增强门禁通过再启用** |
| TencentDB L1/L1.5/L2 提示词（`src/offload/.../prompts/*.ts`） | 直接抄 | 中文 JSON 提示词（工具摘要/任务延续判定/Mermaid 拓扑），进我们 07 prompt 注册表 |
| TencentDB `auto-recall.ts` 召回预算/截断/格式化 | 抄成 Python | 03 §11.3 `apply_recall_budget` 的完整参考 |
| TencentDB `hermes-plugin/.../supervisor.py` + `client.py` | 抄接线模式 | "回合结束写 L0 / 构造 prompt 前召回"的宿主接线范式，映射到我们 LangGraph 节点 |
| TencentDB `mongodb-init.js` / `skill/types.ts` | 对照 | 我们 `scripts/init_db.py` 索引模式与 03 §3.17 Skill 字段的出处 |
