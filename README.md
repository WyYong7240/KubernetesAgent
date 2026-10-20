# Kubernetes 运维智能体 (K8s-Ops-Agent)

这是一个基于 **LangGraph** 和 **MCP (Model Context Protocol)** 构建的高级 Kubernetes 运维智能体。它能够通过自然语言与用户交互，自动执行集群诊断、日志查询、资源管理等任务，并结合 RAG 知识库提供专业的排错建议。

## 🚀 核心功能

- **多智能体协作 (Multi-Agent)**：采用“主管 (Supervisor) + 专家 (Experts)”架构。
    - **Supervisor**：负责任务分发与流程控制。
    - **OPS (运维专家)**：直接对接 K8s 集群，执行 Pod 查询、日志获取、资源描述等操作。
    - **RESEARCH (研究员)**：查阅 K8s 官方文档及内部 SOP，提供理论支持和排错指南。
    - **CHAT (接待员)**：负责日常问候与通用问答。
- **MCP 协议集成**：通过 MCP 协议连接多个工具服务器，实现大脑（LLM）与手脚（Tools）的解耦。
    - 支持本地 stdio 模式 (`local_mcp_server.py`)。
    - 支持外部网络 SSE 模式 (`kubernetes-mcp-server`)。
- **持久化记忆**：使用 `MemorySaver` 实现基于 `thread_id` 的多轮对话记忆，能够联系上下文进行推理。
- **数据清洗与兼容**：针对 DeepSeek 等模型进行了 ToolMessage 的数据清洗，确保复杂工具输出的兼容性。
- **REST API 服务**：基于 FastAPI 构建，方便前端（如 Vue）集成。

## 🛠️ 技术栈

- **后端框架**：FastAPI
- **Agent 编排**：LangGraph (StateGraph)
- **大语言模型**：DeepSeek (通过 LangChain 调用)
- **通信协议**：MCP (Model Context Protocol)
- **工具链**：kubernetes-mcp-server, langchain-mcp-adapters

## 🏗️ 架构设计

智能体内部采用有向无环图 (DAG) 进行状态流转：

1. **START** -> **Supervisor** (决策下一步路由)
2. **Supervisor** -> **OPS** / **RESEARCH** / **CHAT**
3. **OPS** <-> **ops_tools** (调用 K8s MCP 工具)
4. **RESEARCH** <-> **rag_tools** (调用 RAG 文档工具)
5. 专家处理完毕后返回 **Supervisor**，决定是否 **FINISH**。

## 📦 部署与运行

### 1. 环境准备

确保已安装 Python 3.10+，并安装相关依赖：

```bash
pip install fastapi uvicorn langchain-openai langgraph mcp langchain-mcp-adapters python-dotenv
```

### 2. 配置文件

```bash
# 复制模板文件并填入你的真实 API Key
cp .env.example .env
```

然后编辑 `.env`，将 `sk-xxx` 替换为你的真实 API Key。

### 3. 启动服务

```bash
python k8sAgent.py
```

服务将启动在 `http://0.0.0.0:38888`。你可以通过 POST 请求访问 `/api/chat` 接口：

```json
{
  "message": "查看 kube-system 命名空间下的 Pod 状态",
  "thread_id": "user-001"
}
```

## 📝 运维原则

1. **严谨求证**：不凭空猜测，所有结论均基于工具获取的客观数据。
2. **格式化输出**：所有集群资源数据均以整洁的 Markdown 表格呈现。
3. **安全确认**：高危操作（如删除、重启）前会明确列出影响范围并要求用户确认。

## 工单控制面（进行中）

首个控制面切片已经提供了持久化事件接收和工单状态机；它没有 Kubernetes 写能力，也不会执行任何命令。旧聊天 Demo 仍以 `python k8sAgent.py` 启动，新控制面以独立 ASGI 入口运行：

```bash
# 1. 安装控制面依赖（首次）
pip install -e ".[dev]"

# 2. 启动本地 PostgreSQL（需要 Docker）
docker compose up -d postgres

# 3. 首次配置时复制模板（已有 .env 时直接编辑，不要覆盖），然后执行迁移
cp .env.example .env
python -m alembic upgrade head

# 4. 启动工单 API
python -m uvicorn main:app --reload --host 127.0.0.1 --port 38889
```

开发环境的 `POST /api/v1/root-cause-events` 接收版本化 DAGGER 事件；`manual_only` 工单先进入 `WAITING_MANUAL`，然后由 `POST /api/v1/work-orders/{id}/trigger` 进入队列。可通过 `GET /api/v1/work-orders` 与 `GET /api/v1/work-orders/{id}` 查询。生产环境必须设置 `DAGGER_WEBHOOK_SECRET`，并通过 `X-Dagger-Signature: sha256=<hex>` 对请求体进行 HMAC-SHA256 验签。

控制面需要 Python 3.12+。FastAPI 和 Alembic 均自动读取项目根目录的 `.env`，进程环境变量优先于文件；Windows 访问 WSL PostgreSQL 时使用 `127.0.0.1:5432`。工单测试不需要 LLM API Key。当前支持的自动化模式为 `manual_only` 和 `auto_triage`，其他模式返回 `422`。人工操作 API 暂用于本地开发，`X-Actor-Id` 仅记录操作者，不代表身份认证；正式部署前需要接入认证和权限控制。

API 启动后，打开 `http://127.0.0.1:38889/docs` 即可在 Swagger 中提交 `examples/root-cause-event.json` 的样例。也可以在 Windows PowerShell 中执行：

```powershell
$baseUrl = 'http://127.0.0.1:38889'
$receipt = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/root-cause-events" `
  -ContentType 'application/json' -InFile '.\examples\root-cause-event.json'
$receipt

# 原样再次提交应返回同一工单，deduplicated 为 true；首次 201，重复 200。
Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/root-cause-events" `
  -ContentType 'application/json' -InFile '.\examples\root-cause-event.json'

Invoke-RestMethod -Uri "$baseUrl/api/v1/work-orders/$($receipt.work_order_id)"
```

`/healthz` 仅检查 API 进程，真实数据库连通性应通过工单查询或事件写入验证。首期人工触发后状态停留在 `QUEUED`，后续 PR 才会接入 Worker。为了重复测试新建路径，可以修改样例中的 `external_event_id`。

运行默认测试使用 `python -m pytest -q`。真实 PostgreSQL 集成测试需要显式提供测试连接；每个测试会创建并清理独立的 `pr1_test_<随机ID>` schema，通过 Alembic 建表，不修改现有工单：

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://ops_agent:ops_agent_dev@127.0.0.1:5432/kubernetes_agent'
python -m pytest -q
```

集成测试覆盖迁移重复执行、ORM/迁移一致性、事件创建与并发幂等、脱敏、人工操作及新应用实例读取已有工单。

详细状态机、取消语义及 PR 1 边界请参阅 [自愈 Agent 设计](docs/self-healing-agent-design.md)。
