# 病理诊断科普助手后端

当前已提供 FastAPI、PostgreSQL、pgvector、SQLAlchemy、Alembic 和普通用户认证。

## AI 流式回答

项目通过 OpenAI 兼容协议调用模型。当前模型白名单（顺序即优先级）为
`deepseek-v4-flash`、`qwen3.8-flash`、`kimi-k2.6`、`glm-5.2`，密钥与基础地址分别读取：

```text
DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL
QWEN_API_KEY / QWEN_BASE_URL
KIMI_API_KEY / KIMI_BASE_URL
ZHIPUAI_API_KEY / ZHIPUAI_BASE_URL
```

`.env.example` 中仍保留的 `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` 是早期单模型配置。
密钥只能保存在后端，不能放进 Vue 环境变量。未配置时，已保存的用户消息不会丢失，
流式接口会返回明确提示。

用户消息保存阶段会执行独立于大模型的红旗症状预检，命中后跳过模型并显示固定紧急分流
提示；规则边界见 `docs/RED_FLAG_TRIAGE.md`。该预检只接受本轮文本，读不到健康记录。

**已接入、不再属于「后续阶段」**：LangGraph 咨询图与条件路由（`docs/LANGGRAPH.md`）、
医学 RAG 检索与引用核验、结构化追问卡、病理科普卡片、就医导航
（`docs/MCP_EXTERNAL_TOOLS.md`）、健康记录（`docs/HEALTH_RECORDS.md`）。
接口契约见 `docs/API.md` 与 `docs/CONSULTATIONS.md`。

## PostgreSQL + pgvector

本目录使用 Docker Compose 管理本地数据库。`.env` 保存本机开发凭据，不应提交到版本库。

启动并查看状态：

```powershell
docker compose up -d
docker compose ps
```

停止和重新启动：

```powershell
docker compose stop
docker compose start
```

删除容器但保留数据：

```powershell
docker compose down
```

不要随意运行 `docker compose down -v`，其中的 `-v` 会删除数据库数据卷。

## 第一次启动

在 VS Code 中打开 `backend` 目录，然后在 PowerShell 终端执行：

```powershell
docker compose up -d
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

如果 PowerShell 不允许激活虚拟环境，可以不激活，直接运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

启动后访问：

- 接口文档：<http://127.0.0.1:8000/api/v1/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

## 日常检查

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests migrations
.\.venv\Scripts\python.exe -m pytest -q
```

本地密钥和数据库密码只保存在 `.env` 中。请勿提交或截图传播该文件。
