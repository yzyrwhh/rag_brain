# 智能产品知识库

**智能产品知识库**是一个面向产品资料场景的智能问答系统：上传产品说明书、产品描述、
产品介绍等文档（支持 **PDF、Markdown**），系统自动解析并结构化入库；用户随后用自然
语言提问（如"如何使用万用表测量电压？"），系统基于库内文档检索相关内容，生成**带引用
来源**的回答。

## 核心能力

- **文档导入**：上传 PDF / Markdown → MinerU 版面解析（PDF→Markdown）→ 图表理解
  （VLM 生成图片摘要、图片托管到 MinIO）→ 标题分段 + 递归切分 → BGE-M3 向量化
  （稠密 + 稀疏双路）→ 写入 Milvus；同时自动识别文档核心产品名并登记入产品名索引
- **智能问答**：产品名识别 → 多路检索（向量召回 / HyDE 假设文档 / 联网检索）→ RRF
  融合 → BGE-Reranker 精排 → LLM 生成（支持流式 SSE，回答附引用来源）
- **会话管理**：多会话切换、历史记录、清空（MongoDB 存储）
- **MD5 去重**：重复上传同一文档自动跳过，避免库内冗余
- **一键部署**：`docker compose` 起基础组件，单进程运行，开箱即用

## 技术栈

| 环节 | 选型 |
| :--- | :--- |
| 服务框架 | FastAPI + Uvicorn（单应用，端口 8001，页面与 API 一体） |
| 流程编排 | LangGraph（文档导入图 + 智能问答图） |
| 文档解析 | MinerU（PDF→Markdown）；Markdown 直接使用 |
| 图片理解 | VLM（生成图片摘要，检索展示不丢图） |
| 文本嵌入 / 精排 | BGE-M3（1024 维 dense+sparse）/ BGE-Reranker-large |
| 向量库 | Milvus（切片集合 + 产品名集合） |
| 元数据 / 会话 | MongoDB（文档注册表、会话历史） |
| 对象存储 | MinIO（解析产物图片等） |
| 大模型 | OpenAI 兼容接口（地址、模型、密钥在 `knowledge/.env` 配置） |
| 联网补充 | MCP over HTTP（DashScope，可选开关） |

## 快速开始

1. 启动基础组件：`docker compose up -d`（etcd / minio / milvus / attu / mongodb）
2. 按需配置 `knowledge/.env`（LLM 密钥与模型、BGE 模型路径、存储连接等）
3. 启动服务：`start_rag_brain.bat`，或
   `python -m uvicorn knowledge.front.api.main:app --host 0.0.0.0 --port 8001`
4. 打开 http://127.0.0.1:8001 → 上传产品文档 → 开始提问

## 目录结构

```
rag_brain/
├── docker-compose.yml          # 基础组件编排（Milvus / MongoDB / MinIO / etcd / attu）
├── start_rag_brain.bat         # 一键启动脚本
├── knowledge/
│   ├── front/                  # API 入口、页面、schema、service、任务与工具
│   ├── processor/              # LangGraph：import_process 导入图 / query_process 问答图
│   ├── prompt/                 # 提示词（回答 / HYDE / 商品名抽取 / 导入）
│   ├── tools/                  # 嵌入、重排、检索、会话历史、文档注册、联网检索等
│   └── utils/                  # 基础组件（BGE 客户端、MinIO、Milvus 等）
└── docs/                       # 设计文档
```

## 相关文档

- [智能产品知识库系统详细设计](智能产品知识库系统详细设计.md)