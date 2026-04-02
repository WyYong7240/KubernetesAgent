import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from kubernetes import client, config
from kubernetes.client.rest import ApiException

load_dotenv()

# ==========================================
# 1. 初始化 Kubernetes 客户端
# ==========================================
def init_k8s_client():
    """初始化 K8s 客户端，优先尝试使用 kubeconfig"""
    try:
        # 因为你在 master 节点，通常可以直接加载 ~/.kube/config
        config.load_kube_config()
        print("✅ 成功加载 kubeconfig 配置文件。")
    except Exception as e:
        print(f"⚠️ 加载 kubeconfig 失败，尝试 In-Cluster 模式: {e}")
        try:
            # 如果你以后把它打包成 Pod 运行在集群内，会 fallback 到这里
            config.load_incluster_config()
            print("✅ 成功加载 In-Cluster 配置。")
        except Exception as inner_e:
            raise RuntimeError(f"❌ 无法初始化 Kubernetes 客户端: {inner_e}")

init_k8s_client()
v1 = client.CoreV1Api()

# ==========================================
# 2. 定义 Kubernetes 运维工具
# ==========================================
@tool
def list_namespaced_pods(namespace: str) -> str:
    """
    当用户需要查询、列出或获取某个命名空间 (namespace) 下的 Pod 列表时，调用此工具。
    必须传入指定的 namespace 名称。如果用户没有指定，默认使用 'default'。
    """
    try:
        print(f"\n🔧 [Tool Execution] 正在调用 K8s API 获取 '{namespace}' 命名空间的 Pods...")
        pods = v1.list_namespaced_pod(namespace=namespace)
        
        if not pods.items:
            return f"命名空间 '{namespace}' 下当前没有任何 Pod。"
            
        result_lines = [f"命名空间 '{namespace}' 下的 Pod 列表："]
        for pod in pods.items:
            # 提取核心信息：名称、状态、IP、所在节点
            name = pod.metadata.name
            status = pod.status.phase
            pod_ip = pod.status.pod_ip or "N/A"
            node_name = pod.spec.node_name or "N/A"
            result_lines.append(f"- 名称: {name} | 状态: {status} | IP: {pod_ip} | 节点: {node_name}")
            
        return "\n".join(result_lines)
        
    except ApiException as e:
        if e.status == 404:
            return f"错误：找不到命名空间 '{namespace}'。"
        elif e.status == 403:
            return f"错误：权限不足，无法访问命名空间 '{namespace}'。"
        return f"调用 K8s API 发生异常: {e.reason} ({e.status})"
    except Exception as e:
        return f"执行工具时发生未知错误: {str(e)}"

# 将我们的 K8s 工具打包
tools = [list_namespaced_pods]

# ==========================================
# 3. 初始化 LLM 并绑定工具
# ==========================================
llm = ChatOpenAI(
    model=os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'),
    openai_api_key=os.getenv('DEEPSEEK_API_KEY'),
    openai_api_base=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
    temperature=0
)
llm_with_tools = llm.bind_tools(tools)

# ==========================================
# 4. 定义图节点与状态机
# ==========================================
def agent_node(state: MessagesState) -> dict:
    """Agent 推理节点：调用 LLM 决定下一步行动"""
    
    # 注入系统提示词，强化它作为 K8s 运维助手的角色
    sys_msg = SystemMessage(
        content="你是一个专业的 Kubernetes 运维助手。你可以通过调用提供的工具来管理和查询 K8s 集群状态。"
                "请根据用户的需求，准确提取命名空间等参数并调用相应工具。如果用户没有指明命名空间，请默认使用 'default' 或者向用户确认。"
    )
    
    # 将系统消息插在对话最前面
    messages = [sys_msg] + state["messages"]
    response = llm_with_tools.invoke(messages)
    
    return {"messages": [response]}

# 构建 ReAct 图
builder = StateGraph(MessagesState)

# 添加节点
builder.add_node("agent", agent_node)
builder.add_node("tools", ToolNode(tools))  

# 添加边
builder.add_edge(START, "agent")
builder.add_conditional_edges(
    "agent",
    tools_condition,
    {
        "tools": "tools",
        END: END
    }
)
builder.add_edge("tools", "agent")

graph = builder.compile()

# ==========================================
# 5. 测试运行
# ==========================================
if __name__ == "__main__":
    # 测试用例 1：明确指定 kube-system
    user_query = "帮我看一下 kube-system 命名空间下面现在有哪些 Pod 在运行，它们的状态正常吗？"
    print(f"\n🧑‍💻 用户提问: {user_query}")
    print("-" * 50)
    
    result = graph.invoke({
        "messages": [HumanMessage(content=user_query)]
    })

    print("-" * 50)
    print("🤖 Agent 最终回复:\n")
    # 只打印最后一条 AI 的回复
    for message in result["messages"]:
        if message.type == "ai" and not message.tool_calls:
            print(message.content)