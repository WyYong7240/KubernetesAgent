from mcp.server.fastmcp import FastMCP
from kubernetes import client, config

# 专门为你自定义的探测能力命名的 Server
mcp = FastMCP("Custom-Ops-Server")

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

@mcp.tool()
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

if __name__ == "__main__":
    mcp.run()
