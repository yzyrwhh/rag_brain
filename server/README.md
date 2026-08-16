# server/ · Phase 0 工程骨架

> 设计契约：`docs/02`（架构/配置）、`docs/03`（集合 schema）、`docs/05`（API/错误码/事件）、`docs/08`（Phase 0 任务）。

## 环境要求（与设计一致）

- Python **>= 3.11**。本机 conda 已有 `python312`（3.12）环境，直接使用：
  ```bash
  conda activate python312
  ```
  也可新建独立环境：`conda create -n shopkeer python=3.12`
  （`knowledge` 环境是 3.10，留给旧 `knowledge/` 项目，勿混用；**不要原地升级 knowledge 到 3.12**——会重解析其依赖树（langchain/langgraph 等），存在破坏旧项目风险，而旧项目是对等测试基准（08 §1.2））
- Docker Desktop 已启动（Milvus/Mongo/Redis/MinIO/Neo4j）

## 启动步骤

```bash
# 1. 依赖（venv 或 uv）
python -m venv .venv && .venv/Scripts/activate
pip install -e ".[dev]"

# 2. 配置
cp .env.example .env   # 按需修改（JWT_SECRET、NEO4J_PASSWORD 必改）

# 3. 基础设施（根目录）
docker compose -f docker-compose.yml -f docker-compose.app.yml up -d

# 4. 初始化数据库（Mongo 索引 / Milvus 集合 / Neo4j 约束，幂等）
python scripts/init_db.py

# 5. 启动 API
uvicorn app.main:app --reload --port 8000

# 6. 启动 worker（另一终端）
celery -A app.infra.celery_app worker -l info -P solo

# 7. 冒烟
curl http://127.0.0.1:8000/api/v1/health
```

## 端到端冒烟（Hello Agent 任务）

```bash
# 注册
curl -X POST http://127.0.0.1:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"password123"}'
# 登录拿 token
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"password123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# 提交任务
curl -X POST http://127.0.0.1:8000/api/v1/tasks -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"agent":"hello"}'
# 订阅事件（SSE，curl 会持续打印）
curl -N http://127.0.0.1:8000/api/v1/tasks/<task_id>/events?after_seq=0 -H "Authorization: Bearer $TOKEN"
```

## 验证清单（对齐 08 §2.0 验收标准）

- [ ] 注册/登录/刷新/退出全流程 API 测试通过
- [ ] `GET /api/v1/health` 报告 Mongo/Milvus/Redis/MinIO/Neo4j 连通状态
- [ ] Hello Agent 任务端到端：提交 → worker 执行 → 状态落库 → SSE 事件推送
- [ ] `pytest tests -m "not integration"` 通过（无需基础设施）
