"""掌柜智库 CLI（对齐 docs/06 §9；复用同一 API 与 SSE 事件协议）。

用法：
  python -m app.cli --help
  python -m app.cli login
  python -m app.cli chat
  python -m app.cli upload <file> --space <sid> --domain dev
  python -m app.cli search "RAG 优化" --space <sid>
  python -m app.cli ask "LangGraph 是什么" --space <sid>
  python -m app.cli task <task_id>
  python -m app.cli health

依赖：httpx（已装）。配置：~/.shopkeer/config.toml（存 base_url 与双令牌）。
"""
import json
import sys
import time
from pathlib import Path

import httpx
import typer

app = typer.Typer(help="掌柜智库 CLI")

DEFAULT_BASE = "http://127.0.0.1:8000/api/v1"
CONFIG_DIR = Path.home() / ".shopkeer"
CONFIG_FILE = CONFIG_DIR / "config.toml"


# ---------------- 配置 ----------------

def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {"server": {"base_url": DEFAULT_BASE}, "auth": {}}
    try:
        import tomllib

        with open(CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {"server": {"base_url": DEFAULT_BASE}, "auth": {}}


def _save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f'base_url = "{cfg["server"]["base_url"]}"']
    auth = cfg.get("auth", {})
    if auth:
        lines.append(f'access_token = "{auth.get("access_token", "")}"')
        lines.append(f'refresh_token = "{auth.get("refresh_token", "")}"')
        lines.append(f'expires_at = "{auth.get("expires_at", "")}"')
    CONFIG_FILE.write_text("[server]\n" + lines[0] + "\n\n[auth]\n" + "\n".join(lines[1:]) + "\n", encoding="utf-8")


def _client() -> tuple[httpx.Client, dict, str]:
    cfg = _load_config()
    base = cfg["server"]["base_url"]
    token = cfg.get("auth", {}).get("access_token", "")
    # trust_env=False：绕过系统代理直连（同 smoke_test）
    return httpx.Client(base_url=base, timeout=60, trust_env=False), cfg, token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _ensure_login(cfg: dict, token: str) -> None:
    if not token:
        typer.echo("未登录，请先执行: skb login")
        raise typer.Exit(1)


# ---------------- 认证 ----------------

@app.command()
def login(username: str = typer.Option(..., prompt=True), password: str = typer.Option(..., prompt=True, hide_input=True)):
    """登录并保存令牌。"""
    client, cfg, _ = _client()
    r = client.post("/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        typer.echo(f"登录失败: {r.status_code} {r.text}")
        raise typer.Exit(1)
    body = r.json()
    cfg["auth"] = {
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_at": "",
    }
    _save_config(cfg)
    typer.echo(f"登录成功: {body['user']['username']} ({body['user']['role']})")


@app.command()
def logout():
    """登出并清除令牌。"""
    client, cfg, token = _client()
    if token:
        try:
            client.post("/auth/logout", headers=_headers(token))
        except Exception:
            pass
    cfg["auth"] = {}
    _save_config(cfg)
    typer.echo("已登出")


@app.command()
def health():
    """检查服务与基础设施状态。"""
    client, _, _ = _client()
    r = client.get("/health")
    if r.status_code != 200:
        typer.echo(f"health 失败: {r.status_code} {r.text}")
        raise typer.Exit(1)
    body = r.json()
    typer.echo(f"status: {body['status']}")
    for name, st in body["services"].items():
        typer.echo(f"  {name}: {'ok' if st['ok'] else st.get('error', 'down')}")


# ---------------- 对话 ----------------

def _stream_print(resp) -> str:
    """打印 SSE 事件流，返回 FINAL 文本。"""
    final_text = ""
    for line in resp.iter_lines():
        if line.startswith("event: "):
            evt = line[7:]
            if evt == "agent.thinking":
                pass
        elif line.startswith("data: "):
            try:
                payload = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if "text" in payload:
                typer.echo(payload["text"], nl=False)
                sys.stdout.flush()
            if "sources" in payload and payload.get("sources"):
                typer.echo("\n\n来源：")
                for s in payload["sources"]:
                    typer.echo(f"  - {s.get('title')} ({s.get('doc_id')}) score={s.get('score')}")
            final_text = payload.get("text", final_text)
    typer.echo()
    return final_text


@app.command()
def chat(
    query: str | None = typer.Argument(None, help="直接提问；不填进入交互模式"),
    space: str | None = typer.Option(None, "--space", help="知识空间 id"),
):
    """交互式对话（SSE 流式）。支持 /help /exit。"""
    client, cfg, token = _client()
    _ensure_login(cfg, token)
    context = {"spaces": [space]} if space else {}
    if query:
        r = client.post("/chat/stream", headers=_headers(token), json={"query": query, "context": context})
        _stream_print(r)
        return
    typer.echo("掌柜智库 CLI 对话（输入 /exit 退出，/help 帮助）")
    while True:
        q = typer.prompt("你")
        if q == "/exit":
            break
        if q == "/help":
            typer.echo("直接输入问题提问；/exit 退出")
            continue
        try:
            with client.stream("POST", "/chat/stream", headers=_headers(token),
                               json={"query": q, "context": context}) as resp:
                _stream_print(resp)
        except httpx.HTTPError as e:
            typer.echo(f"\n请求失败: {e}")


# ---------------- 任务 ----------------

@app.command()
def task(task_id: str):
    """查看任务状态与事件流。"""
    client, cfg, token = _client()
    _ensure_login(cfg, token)
    r = client.get(f"/tasks/{task_id}", headers=_headers(token))
    if r.status_code != 200:
        typer.echo(f"查询失败: {r.status_code} {r.text}")
        raise typer.Exit(1)
    body = r.json()
    typer.echo(f"task: {body['task_id']} status={body['status']} agent={body['agent']}")
    typer.echo(f"result: {json.dumps(body.get('result'), ensure_ascii=False)}")
    with client.stream("GET", f"/tasks/{task_id}/events?after_seq=0", headers=_headers(token)) as resp:
        for line in resp.iter_lines():
            if line.startswith("event: "):
                typer.echo(f"  event: {line[7:]}")


@app.command()
def tasks(status: str | None = typer.Option(None, "--status"), agent: str | None = typer.Option(None, "--agent")):
    """任务列表。"""
    client, cfg, token = _client()
    _ensure_login(cfg, token)
    params = {}
    if status:
        params["status"] = status
    if agent:
        params["agent"] = agent
    r = client.get("/tasks", headers=_headers(token), params=params)
    if r.status_code != 200:
        typer.echo(f"查询失败: {r.status_code} {r.text}")
        raise typer.Exit(1)
    for item in r.json().get("items", []):
        typer.echo(f"{item['task_id'][:8]}  {item['status']:<12} {item['agent']}  {item.get('created_at', '')}")


# ---------------- 知识库 ----------------

@app.command()
def upload(
    file: str = typer.Argument(...),
    space: str = typer.Option(..., "--space", help="知识空间 id（必填）"),
    domain: str = typer.Option("general", "--domain"),
):
    """上传文档到知识空间（任务化导入）。"""
    client, cfg, token = _client()
    _ensure_login(cfg, token)
    path = Path(file)
    if not path.exists():
        typer.echo(f"文件不存在: {file}")
        raise typer.Exit(1)
    with open(path, "rb") as f:
        r = client.post(
            f"/knowledge/spaces/{space}/documents", headers=_headers(token),
            files={"file": (path.name, f)}, data={"domain": domain},
        )
    if r.status_code != 202:
        typer.echo(f"上传失败: {r.status_code} {r.text}")
        raise typer.Exit(1)
    doc_id, task_id = r.json()["doc_id"], r.json()["task_id"]
    typer.echo(f"上传成功: doc={doc_id} task={task_id}")
    # 轮询导入状态
    for _ in range(60):
        r2 = client.get(f"/knowledge/documents/{doc_id}", headers=_headers(token))
        st = r2.json().get("status")
        typer.echo(f"  状态: {st}", nl=False)
        typer.echo()
        if st in ("completed", "failed"):
            break
        time.sleep(3)


@app.command()
def search(query: str, space: str | None = typer.Option(None, "--space"), top_k: int = typer.Option(5, "--top-k")):
    """知识库检索。"""
    client, cfg, token = _client()
    _ensure_login(cfg, token)
    body = {"query": query, "space_ids": [space] if space else [], "top_k": top_k}
    r = client.post("/knowledge/search", headers=_headers(token), json=body)
    if r.status_code != 200:
        typer.echo(f"检索失败: {r.status_code} {r.text}")
        raise typer.Exit(1)
    data = r.json()
    typer.echo(f"命中 {len(data['results'])} 条（{data['elapsed_ms']}ms）")
    for hit in data["results"]:
        typer.echo(f"\n[{hit['score']}] {hit['doc_id'][:8]} {hit['text'][:80]}...")


@app.command()
def ask(query: str, space: str | None = typer.Option(None, "--space")):
    """知识问答（非流式，带引用）。"""
    client, cfg, token = _client()
    _ensure_login(cfg, token)
    body = {"query": query, "space_ids": [space] if space else [], "top_k": 5}
    r = client.post("/knowledge/ask", headers=_headers(token), json=body)
    if r.status_code != 200:
        typer.echo(f"问答失败: {r.status_code} {r.text}")
        raise typer.Exit(1)
    data = r.json()
    typer.echo(data["answer"])
    for s in data.get("sources", []):
        typer.echo(f"来源: {s.get('title')} ({s.get('doc_id')})")


if __name__ == "__main__":
    app()
