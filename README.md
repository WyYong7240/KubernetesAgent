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

在根目录下创建 `.env` 文件：

```env
DEEPSEEK_API_KEY="your-api-key"
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL="deepseek-chat"
```

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
