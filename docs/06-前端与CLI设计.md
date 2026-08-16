# 06 前端与 CLI 设计

> 项目：掌柜智库（多用户、多域 LangGraph 多智能体平台）
> 本文档基于《05-API与实时协议设计.md》中约定的 API 与 SSE 事件协议，描述 Web 前端（Vue 3 + TypeScript + Vite + Pinia + Vue Router + Element Plus）与 Python Typer CLI（`skb`）双入口的实现设计。
> 约定：本文不新增任何接口名或事件名，一律使用 05 文档的契约。

---

## 1. 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│  Web 前端 (Vue3+TS)          CLI (Python Typer `skb`)        │
│  ┌───────────┐               ┌──────────────┐               │
│  │ Pinia     │               │ 命令解析      │               │
│  │ stores    │               │ (login/chat/  │               │
│  ├───────────┤               │  upload/...)  │               │
│  │ SSE 客户端 │               ├──────────────┤               │
│  │ (ws/sse)  │               │ SSE 客户端    │               │
│  └─────┬─────┘               │ (httpx-sse)   │               │
│        │                     └──────┬───────┘               │
│        └────────── HTTP(S) / SSE  ─┴───────────────────────►│
│                        /api/v1                              │
│                    FastAPI 后端（JWT 鉴权）                   │
└─────────────────────────────────────────────────────────────┘
```

- Web 端：SPA，Token 存内存 + refresh token 存 localStorage，通过 axios 拦截器自动续期。
- CLI 端：Token 持久化在 `~/.shopkeer/config.toml`，共享同一套 HTTP API 与 SSE 事件协议，保证两端行为一致。
- 双向交互（HITL clarify、任务取消）在两端均通过同一批 REST 端点实现。

---

## 2. 前端技术选型与目录结构

### 2.1 选型

| 关注点 | 选择 | 说明 |
|---|---|---|
| 框架 | Vue 3 (`<script setup>` + TS) | Composition API 配合事件驱动的任务面板更易维护 |
| 构建 | Vite | 原生 ESM、开发热更新 |
| 状态 | Pinia | store 划分见第 7 章 |
| 路由 | Vue Router 4 | 路由守卫 + 懒加载 |
| UI | Element Plus | 表格/表单/上传/消息提示开箱即用 |
| HTTP | axios | 拦截器统一注入 Token、处理 401 |
| SSE | 原生 EventSource 封装 + 自研重连 | 自定义事件类型映射，见第 5 章 |

### 2.2 目录结构

```
web/src/
├── api/                # 按资源划分的 API 封装（axios 实例 + 类型）
│   ├── http.ts         # axios 实例、拦截器、错误码映射
│   ├── auth.ts
│   ├── chat.ts         # 会话 CRUD + POST /chat/stream
│   ├── task.ts         # 任务 CRUD/取消/respond/retry
│   ├── knowledge.ts
│   ├── agent.ts
│   ├── tool.ts
│   ├── memory.ts
│   ├── integration.ts
│   ├── graph.ts        # 图谱检索/脑图（FR-26）
│   └── admin.ts        # 管理员 API（FR-25）
├── stores/             # Pinia stores
│   ├── authStore.ts
│   ├── sessionStore.ts
│   ├── taskStore.ts    # 含 SSE 事件 reducer
│   ├── knowledgeStore.ts
│   ├── agentStore.ts
│   └── memoryStore.ts
├── ws/                 # 实时层（注意：项目无 WebSocket，统一走 SSE）
│   ├── sseClient.ts    # EventSource 封装：重连、游标、事件分发
│   ├── taskStream.ts   # 任务事件流（task.* 事件）
│   ├── chatStream.ts   # 聊天流（message.delta / message.final）
│   └── eventTypes.ts   # SSE 事件类型常量与 TS 类型定义
├── views/              # 页面级组件
│   ├── LoginView.vue
│   ├── RegisterView.vue
│   ├── WorkspaceView.vue
│   ├── KnowledgeView.vue
│   ├── AgentsView.vue
│   ├── MemoryView.vue
│   ├── SettingsView.vue
│   └── AdminView.vue    # 管理员页（FR-25，仅 admin 可见）
├── components/         # 通用组件
│   ├── TaskPanel.vue       # 右侧任务执行面板
│   ├── StepTree.vue        # 步骤树（AutoGPT 风格）
│   ├── ClarifyDialog.vue   # HITL 澄清对话框
│   ├── DocumentUpload.vue  # 知识库上传
│   ├── DocumentViewer.vue  # 全文查看/原件下载（FR-27，PDF.js + markdown 渲染）
│   ├── GraphPanel.vue      # 图谱可视化（关系图 + 脑图双模式，antv G6，FR-26）
│   ├── ProgressChip.vue    # "上次进展"记忆提示条（FR-30）
│   ├── SpaceSelector.vue   # 空间选择器（多用户）
│   └── AgentCard.vue
├── utils/              # 工具：格式化、错误文案、常量（状态机/事件名）
│   ├── errors.ts
│   ├── taskState.ts
│   └── format.ts
├── router/index.ts     # 路由 + 守卫
└── App.vue
```

---

## 3. API 客户端与请求封装

### 3.1 axios 实例与拦截器

```ts
// api/http.ts
const http = axios.create({ baseURL: '/api/v1', timeout: 30_000 })

// 请求拦截：注入 access token
http.interceptors.request.use((cfg) => {
  const token = useAuthStore().accessToken
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// 响应拦截：401 时尝试 refresh（单飞模式），成功后重放原请求
http.interceptors.response.use(
  (res) => res,
  async (err) => {
    const { code } = err.response?.data?.detail ?? {}
    if (err.response?.status === 401 && code === 'AUTH_INVALID' && !err.config._retried) {
      err.config._retried = true
      const ok = await useAuthStore().refresh()   // POST /auth/refresh
      if (ok) return http(err.config)             // 重放
      useAuthStore().logout(); router.push('/login')
    }
    throw normalizeError(err)                     // 统一错误对象
  })
```

### 3.2 错误码 → 中文文案

| 错误码 | HTTP | 中文提示 | 前端动作 |
|---|---|---|---|
| AUTH_INVALID | 401 | 登录已过期，请重新登录 | 触发 refresh / 跳转登录 |
| AUTH_FORBIDDEN | 403 | 没有权限执行该操作 | 提示并禁用入口 |
| VALIDATION_ERROR | 422 | 参数校验失败，请检查输入 | 表单级错误回显 |
| NOT_FOUND | 404 | 资源不存在或已被删除 | 提示 + 列表刷新 |
| CONFLICT | 409 | 资源冲突（如重名） | 提示并建议改名 |
| TASK_BUSY | 409 | 任务正在执行，请稍后再试 | 禁用重复操作 |
| TASK_LIMIT | 429 | 任务并发数已达上限 | 提示稍后重试 |
| RATE_LIMITED | 429 | 请求过于频繁，请稍后再试 | 指数退避重试 |
| UPSTREAM_ERROR | 502 | 上游服务（模型/工具）异常 | 提示 + 任务可重试 |
| INTERNAL | 500 | 服务器内部错误 | 通用错误提示 + 上报 |

---

## 4. 认证与路由守卫

- `/login`、`/register` 为公开页；其余页面要求已登录，`/workspace` 为登录后默认落地页。
- 守卫流程：`router.beforeEach` → 无 token 且有 refresh token → 先 `POST /auth/refresh` → 成功放行、失败清空并跳 `/login`；无任何凭据直接跳 `/login?redirect=...`。
- 双令牌：access（15min，内存）与 refresh（7d，localStorage）；刷新失败即视为登出，调用 `POST /auth/logout` 使 refresh 失效。
- `GET /auth/me` 在应用启动时调用，用于恢复会话与用户信息（头像、昵称、默认空间）。

---

## 5. SSE 客户端设计

### 5.1 事件协议总览（前端必须完整支持）

| 事件 | 字段 | 归属流 | 前端用途 |
|---|---|---|---|
| task.ready | task_id, session_id | 任务流 | 建立任务-会话关联，初始化面板 |
| task.plan | plan[] | 任务流 | 渲染步骤树骨架（AutoGPT 风格） |
| node.start / node.end | node, step_id | 任务流 | 步骤状态：运行中→完成/失败 |
| agent.thinking | text | 任务流 | 展示 Agent 推理过程（可折叠） |
| tool.call | tool_id, input | 任务流 | 步骤下展开工具调用输入 |
| tool.result | tool_id, ok, summary | 任务流 | 工具结果摘要（成功/失败徽标） |
| clarify | clarify_id, question, options[] | 任务流 | 弹出 HITL 对话框 |
| clarify.answered | — | 任务流 | 关闭对话框，恢复执行态 |
| task.async_upgraded | — | 任务流 | 同步聊天流切换为任务事件订阅 |
| message.delta | text | 聊天流 | 流式输出追加到当前消息气泡 |
| message.final | text, sources[], memory_saved[] | 聊天流 | 完成消息，渲染引用与记忆回写标记 |
| task.completed | cost | 任务流 | 面板置为完成态，展示 Token 成本 |
| task.failed | error{code,message,retryable} | 任务流 | 面板失败态，retryable 时显示重试按钮 |
| task.cancelled | — | 任务流 | 面板取消态 |

### 5.2 两类流的处理

- **任务事件流**（`POST /tasks` 返回的 task_id 后订阅，事件名以 `task.`/`node.`/`tool.`/`agent.`/`clarify.` 开头）：驱动右侧任务执行面板，事件携 `seq` 自增序号，用于游标续传。
- **聊天流**（`POST /chat/stream`，事件名 `message.delta`/`message.final`）：驱动左侧对话气泡，不涉及断点续传——`message.final` 落库后由 `GET /chat/sessions/{sid}/messages` 兜底恢复。

### 5.3 EventSource 封装与断线重连

```ts
// ws/sseClient.ts —— 通用 SSE 客户端
export class SseClient {
  private es?: EventSource
  private seq = 0                       // 已消费的最大 seq
  private retry = 0

  constructor(private url: string, private handlers: EventHandlers) {}

  connect(afterSeq?: number) {
    const u = afterSeq ? `${this.url}?after_seq=${afterSeq}` : this.url
    this.es = new EventSource(u)
    this.es.onmessage = (e) => this.dispatch(e)
    this.es.onerror = () => this.scheduleReconnect()
  }

  private dispatch(e: MessageEvent) {
    const evt = JSON.parse(e.data)      // {seq, type, payload}
    this.seq = Math.max(this.seq, evt.seq)
    this.handlers[evt.type]?.(evt.payload, evt)
  }

  private scheduleReconnect() {
    // 指数退避：1s → 2s → 4s → … 上限 30s；EventSource 会自动重连，这里负责
    // 在事件流上叠加“带 after_seq 的显式重连”以补齐断档
    const delay = Math.min(1000 * 2 ** this.retry++, 30_000)
    setTimeout(() => this.reconnectWithCursor(), delay)
  }

  private async reconnectWithCursor() {
    // 若服务端 EventSource 已自动续上则无事发生；否则主动携带 after_seq 重建
    this.close()
    this.connect(this.seq)              // 游标续传，服务端从 seq 之后补发
  }

  close() { this.es?.close(); this.es = undefined }
}
```

要点：
- 所有事件统一 JSON 载荷且带 `seq`；任务事件与聊天事件各自维护独立游标。
- 断线重连以「已消费最大 seq」为游标调用 `GET /tasks/{task_id}/events?after_seq=N` 或等价 SSE 端点续传，杜绝丢事件。
- 页面卸载（`onBeforeUnmount`）时 `close()`，组件重新挂载时恢复订阅。

### 5.4 同步转异步（task.async_upgraded）

聊天入口有两条路径：
1. **同步路径**：`POST /chat/stream` 正常返回 `message.final`，聊天流结束，任务面板无任务。
2. **升级路径**：服务端发出 `task.async_upgraded` 后，聊天流停止输出消息事件，任务转为后台执行。

前端处理：

```ts
// ws/chatStream.ts
onEvent('task.async_upgraded', (p) => {
  chatStream.close()                    // 1. 关闭聊天流
  const { task_id } = taskStore.current  // 2. 后端已通过 task.ready 告知 task_id
  taskStore.subscribe(task_id)          // 3. 打开任务事件流（5.3 的 SseClient）
  ui.openTaskPanel()                    // 4. 唤出右侧任务面板，展示步骤树
})
```

切换后任务进度完全由任务事件流驱动；`task.completed` 时聊天区追加一条「任务已完成」摘要消息（含 cost）。

### 5.5 HITL 澄清（clarify）

- 收到 `clarify(clarify_id, question, options[])` → 打开 `ClarifyDialog.vue`，展示问题与选项按钮（选项为「直接选择」；若选项允许自由输入，附文本框）。
- 用户选择 → `POST /tasks/{task_id}/respond`，载荷 `{clarify_id, option_id}` 或 `{clarify_id, text}`。
- 收到 `clarify.answered` → 关闭对话框，面板回到执行态；对话框打开期间面板显示「等待用户输入（AWAITING_INPUT）」状态。

---

## 6. 任务执行面板（步骤树）

### 6.1 任务状态机（前端映射）

```
PENDING ──► PLANNING ──► EXECUTING ──► REVIEWING ──► COMPLETED
              │             │  ▲
              │             ▼  │  (HITL respond)
              │         AWAITING_INPUT
              ▼
           FAILED (retryable ≤3 次)          CANCELLED
```

| 状态 | 面板表现 | 可执行操作 |
|---|---|---|
| PENDING | 排队中动画 | 取消 |
| PLANNING | 规划中，步骤树骨架生成中 | 取消 |
| EXECUTING | 步骤逐个点亮 | 取消；遇 clarify 时答复 |
| AWAITING_INPUT | 高亮等待澄清 | 在 ClarifyDialog 中答复 |
| REVIEWING | 校验中 | 取消 |
| COMPLETED | 绿色完成态 + cost | 重跑（POST /tasks/retry/{task_id}） |
| FAILED | 红色失败态 + error.message | retryable 时重试（≤3 次） |
| CANCELLED | 灰色取消态 | 无 |

### 6.2 步骤树渲染（task.plan + node/tool 事件驱动）

`StepTree.vue` 维护 `steps: StepNode[]`：

```ts
type StepNode = {
  step_id: string
  title: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  tools: { tool_id: string; status: 'running'|'done'|'failed'; summary?: string }[]
}
```

- `task.plan(plan[])` → 初始化 steps 数组，全部 `pending`（含子步骤，展开/折叠）。
- `node.start(node, step_id)` → 对应 step 置 `running`；`node.end` → `done`。
- `tool.call(tool_id, input)` → 挂到当前 step 的 tools，置 `running` 并显示输入 JSON；`tool.result(tool_id, ok, summary)` → 更新徽标与摘要。
- `agent.thinking(text)` → 在当前 step 下追加推理气泡（可折叠）。
- `task.failed` → 当前 running 步骤置 `failed`；`task.cancelled` → 未完成步骤置 `skipped`。
- 面板顶部常驻：任务状态徽标、耗时、Token 成本（`task.completed`）、取消按钮、重试按钮（仅 FAILED 且 retryable）。

---

## 7. Pinia 状态管理

### 7.1 store 划分

| Store | 职责 | 关键 state |
|---|---|---|
| authStore | 登录态、双令牌、用户信息 | accessToken, refreshToken, user, activeSpaceId |
| sessionStore | 会话列表与当前会话消息 | sessions[], currentSid, messages: Record<sid, Msg[]> |
| taskStore | 当前任务与步骤树、任务列表 | currentTask, steps[], taskList[], seqCursor |
| knowledgeStore | 空间/文档/检索结果 | spaces[], docsBySpace, searchResults |
| agentStore | 个人 Agent 与工具/MCP | agents[], tools[], mcpSources[] |
| memoryStore | 语义记忆 | memories[], searchQuery |

空间是横切维度：`activeSpaceId` 存于 authStore，所有按空间过滤的 store 以 `getter` 依赖它，切换空间时触发对应列表刷新。

### 7.2 任务事件增量更新 store（reducer）

```ts
// stores/taskStore.ts —— 事件 reducer 骨架
export const useTaskStore = defineStore('task', {
  state: () => ({ currentTask: null as Task|null, steps: [] as StepNode[], seqCursor: 0 }),
  actions: {
    onSseEvent(evt: SseEvent) {
      this.seqCursor = Math.max(this.seqCursor, evt.seq)   // 游标推进
      switch (evt.type) {
        case 'task.ready':        this.currentTask = { id: evt.task_id, sessionId: evt.session_id, status: 'PLANNING' }; break
        case 'task.plan':         this.steps = buildSteps(evt.plan); break
        case 'node.start':        setStepStatus(this.steps, evt.step_id, 'running'); break
        case 'node.end':          setStepStatus(this.steps, evt.step_id, 'done'); break
        case 'tool.call':         pushTool(this.steps, evt.step_id ?? curStep(), evt.tool_id, evt.input); break
        case 'tool.result':       updateTool(this.steps, evt.tool_id, evt.ok, evt.summary); break
        case 'clarify':           this.currentTask.status = 'AWAITING_INPUT'; this.pendingClarify = evt; break
        case 'clarify.answered':  this.currentTask.status = 'EXECUTING'; this.pendingClarify = null; break
        case 'task.completed':    this.currentTask.status = 'COMPLETED'; this.currentTask.cost = evt.cost; break
        case 'task.failed':       this.currentTask.status = 'FAILED'; this.currentTask.error = evt.error; break
        case 'task.cancelled':    this.currentTask.status = 'CANCELLED'; break
      }
    },
    async respond(optionId?: string, text?: string) {
      await api.respond(this.currentTask!.id, { clarify_id: this.pendingClarify!.clarify_id, option_id: optionId, text })
    },
    async cancel()  { await api.cancelTask(this.currentTask!.id) },
    async retry()   { await api.retryTask(this.currentTask!.id) },
  },
})
```

- 聊天流事件不进 taskStore：`message.delta` 由 chatStream 直接 append 到 sessionStore 当前消息；`message.final` 同时写入 `sources` 与 `memory_saved` 标记。
- 所有 reducer 必须是纯函数式更新（不可变更新 steps 数组），保证 Vue 响应式与撤销/重放一致。

---

## 8. 页面设计（组件拆分与数据流）

### 8.1 /login 与 /register

- 组件：`LoginView.vue`（表单 + 错误提示 + redirect 参数）、`RegisterView.vue`（注册成功自动登录）。
- 数据流：表单 → `POST /auth/login|register` → authStore 写入双令牌 → 路由守卫放行 → 跳 `redirect` 或 `/workspace`。

### 8.2 /workspace（核心页）

- 组件：`WorkspaceView.vue`（双栏布局）＝ 左 `ChatPanel`（消息列表 + 输入框）+ 右 `TaskPanel.vue`（内含 `StepTree.vue`、`ClarifyDialog.vue`）+ 顶部 `SpaceSelector.vue` 与会话列表 `SessionSidebar.vue`。
- 数据流：
  - 发送消息 → `POST /chat/stream`（SSE）→ `chatStream` 分发 `message.delta/final` → sessionStore；
  - 服务端建任务 → `task.ready` → taskStore.subscribe → `GET /tasks/{task_id}/events` 事件流 → reducer 更新 `TaskPanel`；
  - 切换会话 → `GET /chat/sessions/{sid}/messages` 回填消息列表；
  - 会话开始 → `GET /memory/progress?topic=`（取最近主题）→ `ProgressChip.vue` 展示"你上次在 XX 的进展：…"，点击跳转对应记忆/文档（FR-30）。

### 8.3 /knowledge

- 组件：`SpaceSelector`、`SpaceList`、`DocumentTable`（分页 + 标签列）、`DocumentUpload.vue`、`SearchBar` + `SearchResultList`。
- 数据流：
  - 上传：`DocumentUpload.vue` 以 multipart `POST /knowledge/spaces/{sid}/documents` → 返回 `{doc_id, task_id}` → 弹出进度条订阅该 task_id 事件流（解析中 → 完成/失败）→ 刷新文档表；
  - 检索：`POST /knowledge/search` 携带 `{space_id, query, top_k}` → 结果列表展示命中片段与来源文档（可跳转）；
  - 全文/原件：`DocumentViewer.vue` 消费 `GET /knowledge/documents/{id}/fulltext`（全文查看）与 `GET /knowledge/documents/{id}/download`（302 预签名下载，FR-27）；
  - 图谱：`GraphPanel.vue` 消费 `GET /knowledge/graph/mindmap?topic=` 与 `GET /knowledge/graph/neighbors`，渲染技术栈脑图/关系图，节点点击跳转文档与经验（FR-26）；
  - 文档操作：PATCH 元信息、DELETE、`POST /knowledge/documents/{doc_id}/tags` 打标签；成员管理走 `/knowledge/spaces/{sid}/members`。

### 8.4 /agents

- 组件：`AgentCard.vue`（个人 Agent 列表，含来源系统模板标识）、`AgentEditor`（Prompt/模型/工具绑定配置）、`ToolList`（启用/禁用开关，`POST /tools/{tool_id}/enable|disable`）、`McpManager`（`POST /tools/mcp` 接入、`DELETE /tools/mcp/{id}` 移除、`GET /tools/{tool_id}/test` 联调测试）。
- 数据流：`GET /agents` → agentStore；复制模板 `POST /agents`；编辑保存 `PATCH /agents/{agent_id}`；删除 `DELETE /agents/{agent_id}`。Agent 配置严格按用户隔离（见第 10 章）。

### 8.5 /memory

- 组件：`MemoryList`、`MemorySearch`、`MemoryEditor`、`SaveFromTask` 快捷入口。
- 数据流：`GET /memory` 列表；`GET /memory/search?q=` 语义检索；`POST /memory` 新增；`PATCH/DELETE /memory/{mid}` 编辑删除；`POST /memory/save-from-task` 将某任务产出存入记忆；`POST /memory/capture` 记录点子/进展（FR-31）；`GET /memory/progress?topic=` 展示"学习/研究进展"时间线（FR-30）；"立即整理"按钮触发 `POST /memory/consolidate`（FR-29）。

### 8.6 /settings

- 组件：`IntegrationPanel`（`GET /integrations` 列表 + `PUT /integrations/{provider}` 配置 + 断开 `DELETE`）、`ModelSettings`（默认模型/温度等，走 PATCH 用户配置）、`UsageStats`（用量展示，含任务 cost 汇总）、`ProfileCard`（`GET /auth/me`）。

---

### 8.7 /admin（FR-25，仅 admin）

- 组件：`UserTable`（启停/角色/配额，`GET /admin/users` + `PATCH /admin/users/{uid}`）、`UsageOverview`（`GET /admin/stats/overview` 用量总览）、`AuditLogTable`（`GET /admin/audit-logs`）、`SystemAgentEditor`（`PATCH /admin/agents/{agent_id}`）。
- 路由守卫：`meta.roles=['admin']`，非 admin 跳转 /workspace；接口 403 兜底。

## 9. CLI 设计（Python Typer）

### 9.1 命令集

| 命令 | 说明 | 关键调用 |
|---|---|---|
| `skb login` | 交互式登录，存 token 到 `~/.shopkeer/config.toml` | `POST /auth/login`、`/auth/refresh` |
| `skb logout` | 登出并清除本地凭据 | `POST /auth/logout` |
| `skb chat` | 交互式聊天（REPL），支持 `/cancel`、`/clarify` | `POST /chat/stream` + SSE |
| `skb task <task_id>` | 查看单个任务详情与步骤 | `GET /tasks/{task_id}` + events |
| `skb tasks` | 任务列表 | `GET /tasks` |
| `skb upload <file> --space <sid>` | 上传文档到知识库 | `POST /knowledge/spaces/{sid}/documents` |
| `skb search <query> --space <sid>` | 混合检索 | `POST /knowledge/search` |
| `skb agents list` | 列出个人 Agent | `GET /agents` |
| `skb memory list / search <q> / add <text>` | 记忆管理 | `GET /memory`、`GET /memory/search`、`POST /memory` |
| `skb stream <task_id>` | 实时订阅任务事件流 | `GET /tasks/{task_id}/events` |
| `skb doc <doc_id> --fulltext\|--download` | 查看全文 / 下载原件 | `GET /knowledge/documents/{id}/fulltext\|download` |
| `skb graph mindmap <topic> --space <sid>` | 主题脑图（JSON 输出） | `GET /knowledge/graph/mindmap` |
| `skb memory progress <topic>` | 查学习/研究进展 | `GET /memory/progress` |
| `skb admin users` | 用户列表（admin） | `GET /admin/users` |

### 9.2 复用同一套 API 与 SSE 协议

- 统一 `SkbClient`（httpx 封装）：自动带 `Authorization: Bearer`、401 时用 refresh token 续期（与前端逻辑一致）。
- SSE 订阅用 `httpx-sse` 的 `connect_sse` 或自实现行解析（`data: {...}`），事件分发器与前端 reducer 同构：

```python
# skb/cli/sse.py —— 与前端 SseClient 对应的事件分发骨架
from httpx_sse import connect_sse

async def stream_task(task_id: str, client: SkbClient, after_seq: int = 0):
    url = f"/api/v1/tasks/{task_id}/events?after_seq={after_seq}"
    async with client.stream("GET", url) as resp:
        async with connect_sse(resp) as sse:
            async for ev in sse.iter_sse():
                payload = json.loads(ev.data)          # {seq, type, payload}
                handler = HANDLERS.get(payload["type"])  # task.plan → 渲染步骤树
                if handler:
                    handler(payload["payload"])
```

- 断线重连：捕获 `StopAsyncIteration`/连接异常后，以 `after_seq=<已消费最大 seq>` 重新请求，等价于前端的游标续传。
- `skb chat` 中 `task.async_upgraded` 后自动转入 `stream_task` 订阅，与 Web 端行为一致。

### 9.3 配置文件与认证

```toml
# ~/.shopkeer/config.toml
[server]
base_url = "https://api.shopkeer.example"   # 默认 http://127.0.0.1:8000

[auth]
access_token = "..."    # 15min，过期自动用 refresh 续期
refresh_token = "..."   # 7d
expires_at = "2025-..."

[defaults]
space_id = "..."        # 默认空间，upload/search 未指定 --space 时使用
```

- token 刷新成功后回写文件；`skb logout` 删除 `[auth]` 段（保留 server 配置）。

### 9.4 退出与取消

- `Ctrl+C`：首按发送 `POST /tasks/{task_id}/cancel` 并优雅退出；再按强制退出（`KeyboardInterrupt` 兜底）。
- `skb chat` 输入 `/cancel` 同样触发 cancel；REPL 中收到 `clarify` 时以选项编号菜单让用户选择，选择后调 `POST /tasks/{task_id}/respond`。

---

## 10. 多用户视角

| 场景 | 交互说明 |
|---|---|
| 空间选择 | 顶部 `SpaceSelector.vue`：展示「我的空间 + 我加入的共享空间」；切换即切换 `activeSpaceId`，会话/知识库/任务面板按空间过滤刷新 |
| 共享空间成员 | `/knowledge` 空间详情内展示成员列表（`GET /knowledge/spaces/{sid}/members`），按角色（owner/member）控制文档上传/删除按钮显隐；403 时提示 AUTH_FORBIDDEN |
| Agent 按用户隔离 | `GET /agents` 只返回当前用户（个人 Agent + 可见系统模板副本）；复制模板产生的 `POST /agents` 归属当前用户，其他人不可见；PATCH/DELETE 仅限 owner，越权返回 403 |
| 任务与会话隔离 | 任务/会话均带 owner 维度；他人任务 ID 不可访问（404/403），共享空间内文档为协作可见、任务仍私有 |
| 并发提示 | 同空间多人上传时，文档列表依赖服务端事件或刷新兜底；`TASK_BUSY` 时按钮置灰并提示 |
| 管理员 | `/admin` 页面与 `skb admin` 命令仅 admin 可用；角色不足时接口返回 403（AUTH_FORBIDDEN） |

---

## 11. 非功能要求

### 11.1 鉴权与安全
- 路由守卫 + axios 拦截器双层防护（见第 3、4 章）；`AUTH_INVALID` 一律走 refresh 单飞，避免并发 401 风暴。
- access token 仅存内存；refresh token 存 localStorage 并设置过期清理；登出时调用 `/auth/logout`。

### 11.2 错误与加载态规范
- 统一错误提示：Element Plus `ElMessage`/`ElNotification`，文案来自错误码映射表（3.2），技术细节进 console。
- 加载态：列表首次加载用骨架屏（`el-skeleton`）；提交/上传按钮 `loading`；任务面板状态徽标常驻。
- 空态规范：列表为空时展示插画 + 引导按钮（如「上传第一份文档」「新建 Agent」）；步骤树为空时展示「等待任务开始」占位。

### 11.3 性能与健壮性
- 路由级懒加载（`import()`）；SSE 连接数受控（每任务一条事件流，任务结束即 close）。
- 消息列表虚拟滚动（长会话）；`message.delta` 高频追加时以 `requestAnimationFrame` 节流渲染。
- 断线重连指数退避（1s→30s），恢复后游标续传补齐事件；页面 `visibilitychange` 时校验 SSE 存活。

### 11.4 可观测性
- 前端统一日志封装（debug 级别记录 SSE 事件流 seq/type），便于与后端事件日志对照排障。

---

## 12. 附：双端一致性要点

| 能力 | Web | CLI | 复用点 |
|---|---|---|---|
| 鉴权 | 内存 + refresh 自动续期 | config.toml + 自动续期 | 401 → refresh → 重放 |
| SSE | 原生 EventSource 封装 | httpx-sse | 同一事件协议、同一游标续传策略 |
| 事件分发 | Pinia reducer | 字典 HANDLERS | 事件类型/载荷结构完全一致 |
| 同步转异步 | 关闭聊天流 → 订阅任务流 | 同一逻辑 | `task.async_upgraded` |
| HITL | ClarifyDialog 选项按钮 | 选项编号菜单 | `POST /tasks/{id}/respond` |
| 取消 | 面板取消按钮 | Ctrl+C / `/cancel` | `POST /tasks/{id}/cancel` |

> 后续演进：事件协议升级时优先在 `ws/eventTypes.ts` 与 CLI `HANDLERS` 同步维护类型定义，保持两端契约单一来源（以 05 文档为最终权威）。
