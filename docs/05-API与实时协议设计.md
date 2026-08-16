# 05 · API 与实时协议设计

> 前后端与 CLI 的唯一契约。所有接口以 `/api/v1` 为前缀；鉴权默认 Bearer JWT（`Authorization: Bearer <access_token>`）；错误码统一（见 §9）。

## 1. API 总览

| 模块 | 前缀 | 说明 |
| :--- | :--- | :--- |
| 认证 | `/api/v1/auth` | 注册/登录/刷新/登出/我的信息 |
| 会话聊天 | `/api/v1/chat` | 会话 CRUD、消息、SSE 聊天 |
| 任务 | `/api/v1/tasks` | 提交/状态/事件/取消/澄清答复 |
| 知识库 | `/api/v1/knowledge` | 空间、文档、上传、检索、全文/原件、图谱检索（FR-26/27） |
| 智能体 | `/api/v1/agents` | Agent 列表与个人配置 |
| 工具 | `/api/v1/tools` | 工具注册表（工具库）、MCP 管理、使用统计 |
| 记忆 | `/api/v1/memory` | 语义记忆 CRUD/检索、点子捕获、进展恢复、定期整理 |
| 集成 | `/api/v1/integrations` | 第三方配置（加密存储，含外部 Agent 桥接 FR-28） |
| 管理 | `/api/v1/admin` | 用户管理、配额、审计日志、用量总览（FR-25） |

## 2. 认证（JWT 流程）

```
POST /api/v1/auth/register    {username, password, email?}
POST /api/v1/auth/login       {username, password}      → {access_token, refresh_token, user}
POST /api/v1/auth/refresh     {refresh_token}           → 新令牌对（旋转，旧 refresh 吊销）
POST /api/v1/auth/logout      Bearer                    吊销当前 refresh
GET  /api/v1/auth/me           Bearer                    → 用户信息
```

- access 15min / refresh 7d；刷新后返回新对。
- 错误：`401 UNAUTHORIZED`（令牌无效/过期）、`403 FORBIDDEN`（无权限/被禁用）。

## 3. 会话与聊天

### 3.1 会话
```
GET    /api/v1/chat/sessions           会话列表（分页）
POST   /api/v1/chat/sessions           {title?, agent?} → session
GET    /api/v1/chat/sessions/{sid}     会话详情（含消息）
PATCH  /api/v1/chat/sessions/{sid}     改名/改 agent
DELETE /api/v1/chat/sessions/{sid}     软删除（级联消息）
GET    /api/v1/chat/sessions/{sid}/messages?cursor=&limit=
```

### 3.2 同步聊天（SSE 流）
```
POST /api/v1/chat/stream
Content-Type: application/json
{
  "session_id": "…",            // 可空：服务端创建新会话
  "query": "用 LangGraph 做多智能体，状态怎么设计？",
  "attachments": [],            // 可选图片/文件
  "context": {"use_memory": true, "spaces": ["space_id"]}
}
响应: text/event-stream（SSE），事件见 §8
```

- 该接口内部创建/复用任务，返回首事件 `task.ready`（含 task_id）。
- 适用于快任务；若中途判定为长任务，服务端发 `task.async_upgraded` 事件，前端切换为轮询/订阅任务事件。

## 4. 任务 API

```
POST   /api/v1/tasks                   提交异步任务
       {agent, input:{query, entities, session_id}, budget?:{max_tokens, max_steps}}
       → {task_id, status}
GET    /api/v1/tasks/{task_id}          任务状态 + plan + result + cost
GET    /api/v1/tasks/{task_id}/events?after_seq=0    事件流（SSE，游标续传）
POST   /api/v1/tasks/{task_id}/cancel   取消（幂等）
POST   /api/v1/tasks/{task_id}/respond  HITL 答复 {clarify_id, option_id | text}
GET    /api/v1/tasks?status=&agent=&page=   任务列表（本人）
POST   /api/v1/tasks/retry/{task_id}    失败任务重试（retry_count ≤ 3）
```

- 幂等：请求头 `Idempotency-Key`（client_request_id），重复提交返回原任务。
- 所有任务接口强制 `user_id` 隔离，越权返回 404（不暴露存在性）。

## 5. 知识库 API

### 5.1 空间
```
POST   /api/v1/knowledge/spaces          {name, type, domain_hint[]}
GET    /api/v1/knowledge/spaces          我的空间列表（含共享）
GET    /api/v1/knowledge/spaces/{sid}    详情 + 成员
PATCH  /api/v1/knowledge/spaces/{sid}
DELETE /api/v1/knowledge/spaces/{sid}    仅 owner；级联删除文档/切片
POST   /api/v1/knowledge/spaces/{sid}/members    {user_id, role}（owner）
DELETE /api/v1/knowledge/spaces/{sid}/members/{uid}
```

### 5.2 文档
```
POST   /api/v1/knowledge/spaces/{sid}/documents        multipart 上传 → {doc_id, task_id}
GET    /api/v1/knowledge/spaces/{sid}/documents?status=&domain=&tag=&page=
GET    /api/v1/knowledge/documents/{doc_id}             详情（含导入进度）
DELETE /api/v1/knowledge/documents/{doc_id}             级联删除
POST   /api/v1/knowledge/documents/{doc_id}/tags        {tags[]}
POST   /api/v1/knowledge/documents/{doc_id}/reimport    重新导入（修复解析）
GET    /api/v1/knowledge/documents/{doc_id}/fulltext    全文查看（组装全文/章节，FR-27）
GET    /api/v1/knowledge/documents/{doc_id}/download    原件下载（302 → MinIO 预签名 URL，TTL 10min）
```

### 5.3 检索
```
POST /api/v1/knowledge/search
{ "query": "…", "space_ids": [], "domain": null, "top_k": 10,
  "filters": {"tags": [], "sources": []}, "hybrid": true }
→ { "results": [{chunk_id, doc_id, text, score, source, page}], "elapsed_ms": 123 }
```
- 权限：space_ids 必须 ⊆ 用户可访问空间，否则 403。
- `mode`：`chunk`（默认，片段召回）或 `full`（整篇全文，配合 `kb_read_document`，服务端按预算截断）。
- 该接口供前端"知识库检索"页面与 CLI 使用；Agent 内部走同一实现（`kb_retrieve`）。

### 5.4 图谱检索（FR-26）

```
POST /api/v1/knowledge/graph/query      {query, space_ids, depth?} → {entities[], relations[], docs[]}
GET  /api/v1/knowledge/graph/mindmap    ?topic=&space_id=           → {nodes[], edges[]}（脑图树）
GET  /api/v1/knowledge/graph/neighbors  ?entity=&depth=1&space_id=  → 子图 JSON
GET  /api/v1/knowledge/graph/entities   ?q=&kind=&space_id=         → 实体搜索
```
- 全部带空间过滤；前端 `GraphPanel.vue` 消费 mindmap/neighbors 渲染关系图与脑图；Agent 走 `graph_query`/`graph_mindmap` 工具。

## 6. 智能体与工具 API

```
GET    /api/v1/agents                      系统 + 个人 Agent 列表（含已启用工具）
GET    /api/v1/agents/{agent_id}           详情（persona、模型、工具）
POST   /api/v1/agents                      创建个人 Agent（复制系统模板）
PATCH  /api/v1/agents/{agent_id}           改配置（模型/工具/参数/版本+1）
DELETE /api/v1/agents/{agent_id}           删除个人 Agent

GET    /api/v1/tools                       工具注册表
POST   /api/v1/tools/{tool_id}/enable|disable
POST   /api/v1/tools/mcp                   {name, endpoint, transport} 接入 MCP server
DELETE /api/v1/tools/mcp/{id}
GET    /api/v1/tools/{tool_id}/test        连通性测试
GET    /api/v1/tools/stats                  工具使用统计（调用/成功率/成本，工具库治理）
GET    /api/v1/tools/recommend?agent=       指定 Agent 的推荐工具集
```

## 7. 记忆与集成 API

```
GET    /api/v1/memory?kind=&tag=&page=     记忆列表（本人）
GET    /api/v1/memory/search?q=&kind=      语义检索
POST   /api/v1/memory                      {kind, content, tags, importance}
PATCH  /api/v1/memory/{mid}
DELETE /api/v1/memory/{mid}
POST   /api/v1/memory/save-from-task       {task_id, kind, tags}  ← DevAgent 经验沉淀
POST   /api/v1/memory/capture              {text, kind(idea|insight|progress), linked_ids[]}  ← 点子/进展捕获（FR-31）
GET    /api/v1/memory/progress             ?topic=  ← 按主题查学习/研究进展（FR-30）
POST   /api/v1/memory/consolidate          ← 手动触发定期整理（FR-29，本人或 admin）

GET    /api/v1/integrations                已配置 provider 列表（脱敏）
PUT    /api/v1/integrations/{provider}     {config}（加密存储）
DELETE /api/v1/integrations/{provider}
GET    /api/v1/integrations/{provider}/status  外部 Agent 桥接可用性/健康检查（FR-28）
```
- provider 含 dashscope/arxiv/semantic_scholar/mcp_websearch/shopping 及外部 Agent（claude_code 等，配置 {command, model, budget, sandbox}，详见 04 §11）。

### 7.1 记忆扩展（L2 场景 / Skill / 溯源，FR-29~33）

```
GET    /api/v1/memory/scenes?kind=&page=         L2 场景/任务拓扑列表
GET    /api/v1/memory/scenes/{scene_id}          读场景（含 mmd_content 任务拓扑）
POST   /api/v1/memory/scenes/{scene_id}/refresh  手动重建任务拓扑（L1.5/L2，幂等）
GET    /api/v1/skills?status=&owner=&page=       Skill 资产列表（head 版本）
POST   /api/v1/skills/propose                    {content, metadata} → {propose_id, similar_skills[]}（两阶段去重）
POST   /api/v1/skills/confirm                    {propose_id} → 创建/更新 Skill（版本+1，supersedes 旧版）
PATCH  /api/v1/skills/{skill_id}                 metadata/visibility/acl（正文不可变 → 走 propose/confirm）
DELETE /api/v1/skills/{skill_id}                 归档（保留历史版本）
GET    /api/v1/memory/generation-log?memory_id=  记忆生成溯源（prompt id/version/hash + 输入引用）
POST   /api/v1/memory/prompts                    {layer, prompt_ref, scope, scope_id}（admin，FR-33 相关）
```

## 8. 事件协议（SSE 事件名与 payload）

统一事件封装：`event: <type>\ndata: <json>\n\n`。事件类型注册在 `schemas/events.py`。

| type | payload 关键字段 | 说明 |
| :--- | :--- | :--- |
| `task.ready` | task_id, session_id | 任务建立 |
| `task.plan` | plan[] | 步骤树（前端渲染） |
| `node.start` / `node.end` | node, step_id | 图节点进度 |
| `agent.thinking` | text | Agent 中间思考（可选展示） |
| `tool.call` | tool_id, input(摘要) | 工具调用开始 |
| `tool.result` | tool_id, ok, summary | 工具返回摘要 |
| `clarify` | clarify_id, question, options[] | HITL 等待用户 |
| `clarify.answered` | clarify_id, option_id | 恢复执行 |
| `task.async_upgraded` | task_id | 同步转异步 |
| `message.delta` | text | 答案流式增量 |
| `message.final` | text, sources[], memory_saved[] | 完整答案（含引用与记忆写入回执） |
| `task.completed` | task_id, cost | 正常结束 |
| `task.failed` | task_id, error{code, message, retryable} | 失败 |
| `task.cancelled` | task_id | 取消 |

**示例（clarify）：**
```
event: clarify
data: {"clarify_id":"c_01","question":"推荐哪个方向？","options":[{"id":"o1","label":"LangGraph 原生"},{"id":"o2","label":"轻量自研"}]}
```

**游标续传**：`GET /tasks/{id}/events?after_seq=N` 返回 `seq > N` 的事件（SSE），用于断线重连/异步任务轮询。

## 9. 错误码约定

| code | HTTP | 含义 |
| :--- | :--- | :--- |
| `AUTH_INVALID` | 401 | 凭证无效/过期 |
| `AUTH_FORBIDDEN` | 403 | 无权限（含越权资源，资源不存在返回 404） |
| `VALIDATION_ERROR` | 422 | 参数校验失败（含字段明细） |
| `NOT_FOUND` | 404 | 资源不存在 |
| `CONFLICT` | 409 | 唯一冲突（用户名已存在、重复导入） |
| `TASK_BUSY` | 409 | 任务状态不允许该操作（如取消已完成任务） |
| `TASK_LIMIT` | 429 | 用户并发任务超限 |
| `RATE_LIMITED` | 429 | 限流 |
| `UPSTREAM_ERROR` | 502 | 第三方（LLM/搜索/存储）故障 |
| `INTERNAL` | 500 | 未预期错误 |

## 10. WebSocket 设计（阶段二）

- `WS /ws/v1/tasks/{task_id}`：订阅任务事件（替代 SSE 轮询，低延迟 + 双向：可内嵌 respond/cancel 指令）。
- `WS /ws/v1/chat`：全双工聊天（音频/长连接场景，预留）。
- 阶段一以 SSE 为主（浏览器原生支持、CLI 易实现、负载可控），WS 作为演进项。

## 11. 通用约定

- **分页**：`?page=1&page_size=20`，响应 `{items, total, page, page_size}`；消息/事件用游标 `cursor/after_seq`。
- **时间**：ISO 8601 UTC（`2025-01-01T00:00:00Z`）。
- **ID**：对外一律 UUID4 字符串（`task_id`、`doc_id`、`space_id`、`memory_id`）。
- **限流**：聊天/任务 10 req/min/user；登录 5 req/min/IP；检索 60 req/min/user。
- **版本**：破坏性变更升 `/api/v2`；非破坏性向后兼容。
- **审计**：删除、导入、记忆写入、工具确认操作写 `audit_logs`。

## 12. 管理 API（FR-25，admin 角色）

```
GET    /api/v1/admin/users?role=&status=&page=         用户列表
PATCH  /api/v1/admin/users/{uid}                       启停/改角色/改配额
GET    /api/v1/admin/users/{uid}/usage                 单用户用量（token/费用/任务数）
GET    /api/v1/admin/stats/overview                    平台用量总览（按日/按模型/按域）
GET    /api/v1/admin/audit-logs?action=&user=&page=    审计日志查询
PATCH  /api/v1/admin/agents/{agent_id}                 系统级 Agent 模板配置
POST   /api/v1/admin/announcements                     系统公告（前端广播）
POST   /api/v1/admin/memory/consolidate/all            全量记忆定期整理触发（FR-29）
```
- 统一 `require_role("admin")` 依赖校验；admin 的敏感操作同样写审计日志。
- 权限模型见 03 §3.1 角色矩阵；越权返回 403。

## 13. 核心接口契约（实现级示例）

> 本节给出关键接口的**请求/响应 JSON 示例与错误行为**，前端/CLI/Agent 工具实现以此为准，字段名不得自行改动。

### 13.1 统一约定
- 成功：直接返回类型化 JSON（无包裹层）。
- 错误：HTTP 状态码 + 统一错误体 `{"code": "<错误码>", "message": "<中文文案>", "detail": {...}}`（错误码见 §9）。
- 时间 ISO8601 UTC；ID 一律 UUID4；分页 `{items, total, page, page_size}`。

### 13.2 认证
```
POST /api/v1/auth/register
req:  {"username":"alice","password":"...","email":"a@b.c"}
resp 201: {"user":{"user_id":"u_1","username":"alice","role":"user"},"access_token":"...","refresh_token":"..."}
错误: VALIDATION_ERROR(422) / CONFLICT(409, username 已存在)

POST /api/v1/auth/login
req:  {"username":"alice","password":"..."}
resp 200: 同上
错误: AUTH_INVALID(401, 凭证错误)

POST /api/v1/auth/refresh
req:  {"refresh_token":"..."}
resp 200: {"access_token":"...","refresh_token":"..."}（旋转，旧 refresh 即刻吊销）
错误: AUTH_INVALID(401, refresh 已失效/被吊销)
```

### 13.3 聊天（SSE 流）
```
POST /api/v1/chat/stream
req: {"session_id":"s_001","query":"用 LangGraph 做多智能体，状态怎么设计？",
      "attachments":[],"context":{"use_memory":true,"spaces":["sp_1"]}}
```
事件序列（实现必须按此顺序发出）：
```
event: task.ready     data: {"task_id":"t_1","session_id":"s_001"}
event: task.plan      data: {"plan":[{"step_id":"s1","title":"检索经验库","agent":"dev","deps":[]},
                                     {"step_id":"s2","title":"生成方案","agent":"dev","deps":["s1"]}]}
event: node.start     data: {"node":"dev","step_id":"s1"}
event: tool.call      data: {"tool_id":"kb_retrieve","input":{"query":"LangGraph 状态设计","domain":"dev","top_k":5}}
event: tool.result    data: {"tool_id":"kb_retrieve","ok":true,"summary":"命中 5 条经验"}
event: agent.thinking data: {"text":"基于经验库 3 条方案对比，推荐子图嵌套"}
event: message.delta  data: {"text":"推荐用 SubGraph 嵌套…"}
event: message.final  data: {"text":"…完整答案…","sources":[{"doc_id":"d_1","title":"04-多智能体编排设计","url":"/api/v1/knowledge/documents/d_1/fulltext"}],"memory_saved":["m_3"]}
event: task.completed data: {"task_id":"t_1","cost":{"tokens":1234,"estimated_cost":0.0012}}
```

### 13.4 任务
```
POST /api/v1/tasks
req:  {"agent":"research","input":{"query":"找 10 篇 RAG 优化论文","entities":{"topic":"RAG","limit":10}},
       "budget":{"max_tokens":50000}}
resp 202: {"task_id":"t_2","status":"PENDING"}

GET /api/v1/tasks/{task_id}
resp 200: {"task_id":"t_2","status":"EXECUTING","agent":"research","intent":"research_paper_search",
           "plan":[...],"current_step":"s2","cost":{"tokens":800,"estimated_cost":0.0008},
           "created_at":"2026-01-01T00:00:00Z","started_at":"..."}

POST /api/v1/tasks/{task_id}/respond
req:  {"clarify_id":"c_1","option_id":"o1"}     # 或 {"clarify_id":"c_1","text":"自定义输入"}
resp 200: {"task_id":"t_2","status":"EXECUTING"}
错误: TASK_BUSY(409, 任务不在 AWAITING_INPUT)

POST /api/v1/tasks/{task_id}/cancel
resp 200: {"task_id":"t_2","status":"CANCELLED"}（幂等，已终态返回当前状态）
```

### 13.5 知识库
```
POST /api/v1/knowledge/search
req:  {"query":"RAG 混合检索","space_ids":["sp_1"],"domain":"dev","top_k":10,"mode":"chunk","hybrid":true}
resp 200: {"results":[{"chunk_id":"c_1","doc_id":"d_1","text":"...","score":0.82,"source":"upload","page":3}],
           "elapsed_ms":120}
错误: AUTH_FORBIDDEN(403, space_ids 含不可访问空间)

POST /api/v1/knowledge/spaces/{sid}/documents      # multipart/form-data, 字段 file + 可选 tags/domain
resp 202: {"doc_id":"d_9","task_id":"t_3"}

GET  /api/v1/knowledge/documents/{doc_id}/download → 302 Location: <minio presigned url>
GET  /api/v1/knowledge/documents/{doc_id}/fulltext
resp 200: {"doc_id":"d_9","title":"...","full_text":"...","sections":[{"heading":"一","text":"..."}],"text_length":12345}
```

### 13.6 记忆 / Skill
```
POST /api/v1/memory/capture
req:  {"text":"用户提出 RAG 可结合图谱做多跳","kind":"idea","linked_ids":["d_9"]}
resp 201: {"memory_id":"m_10","layer":"l1","type":"idea"}

GET /api/v1/memory/progress?topic=RAG
resp 200: {"items":[{"memory_id":"m_5","topic":"RAG","progress_state":"读到第 3 章","updated_at":"..."}]}

POST /api/v1/skills/propose
req:  {"content":"部署 LangGraph 的 checklist…","metadata":{"tags":["langgraph","deploy"]}}
resp 200: {"propose_id":"p_1","similar_skills":[{"skill_id":"sk_2","similarity":0.91}]}

POST /api/v1/skills/confirm
req:  {"propose_id":"p_1"}
resp 201: {"skill_id":"sk_3","version":1,"is_head":true,"supersedes":["sk_2"]}
```

### 13.7 图谱
```
GET /api/v1/knowledge/graph/mindmap?topic=LangGraph&space_id=sp_1
resp 200: {"nodes":[{"id":"n1","label":"LangGraph","kind":"framework"},
                    {"id":"n2","label":"LangChain","kind":"framework"}],
           "edges":[{"source":"n1","target":"n2","type":"DEPENDS_ON"}]}

POST /api/v1/knowledge/graph/query
req:  {"query":"多智能体编排框架选型","space_ids":["sp_1"],"depth":2}
resp 200: {"entities":[{"name":"LangGraph","kind":"framework"}],
           "relations":[{"source":"LangGraph","target":"LangChain","type":"DEPENDS_ON"}],
           "docs":[{"doc_id":"d_1","title":"04-多智能体编排设计"}]}
```
