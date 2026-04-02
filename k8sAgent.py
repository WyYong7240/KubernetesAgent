import asyncio
from email.message import Message
import os
import traceback
# import logging
# # 关闭底层的MCP与Agent的通信日志，让终端保持清爽
# # 屏蔽MCP协议的通信包打印
# logging.getLogger("mcp").setLevel(logging.WARNING)
# # 屏蔽HTTP库的请求日志，如果使用了SSE，会有这些信息
# logging.getLogger("httpx").setLevel(logging.WARNING)
# # 屏蔽LangChain的冗余调试信息
# logging.getLogger("langchain").setLevel(logging.WARNING)

from langchain_core.messages.tool import tool_call
from aioconsole import ainput
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver # 引入内存保存器件

# 引入 MCP 客户端依赖
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from langchain_mcp_adapters.tools import load_mcp_tools
from urllib3 import response

load_dotenv()

async def main():
    # ==========================================
    # 1. 定义两个 Server 的启动参数
    # ==========================================
    # Server A：你的自定义 Python 脚本
    server_a_params = StdioServerParameters(
        command="python",
        args=["custom_mcp_server.py"],
        env=None
    )
    
    # Server B： Kubernetes-mcp-server (替换为实际的启动命令)
    server_b_params = StdioServerParameters(
        command="npx", 
        args=["-y", "kubernetes-mcp-server@latest"], # 假设开源包通过模块启动
        env=None
    )
    
    # Server B：kubeShark-mcp
    kubeshark_url = "http://127.0.0.1:8898/mcp"

    # ==========================================
    # 2. 同时连接两个 Server 并获取 Tools
    # ==========================================
    # 使用上下文管理器维持底层进程流
    async with stdio_client(server_a_params) as (read_custom, write_custom), \
               stdio_client(server_b_params) as (read_kube, write_kube):
                # sse_client(kubeshark_url) as (read_ks, write_ks):
        
        async with ClientSession(read_custom, write_custom) as session_custom, \
                   ClientSession(read_kube, write_kube) as session_kube:
                    # ClientSession(read_ks, write_ks) as session_ks:
            
            # 初始化握手
            await session_custom.initialize()
            await session_kube.initialize()
            # await session_ks.initialize()
            
            # 将 MCP 工具转换为 LangChain 可识别的 Tools
            tools_custom = await load_mcp_tools(session_custom)
            tools_kube = await load_mcp_tools(session_kube)
            # tools_ks = await load_mcp_tools(session_ks)
            
            # 聚合所有能力
            all_tools = tools_custom + tools_kube
            print(f"✅ 成功从 Server 加载了 {len(all_tools)} 个工具！")


            # ==========================================
            # 3. 绑定至 LangGraph (与之前逻辑一致)
            # ==========================================
            # 构建带有记忆能力的图
            memory = MemorySaver()
            llm = ChatOpenAI(
                model=os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'),
                openai_api_key=os.getenv('DEEPSEEK_API_KEY'),
                openai_api_base=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
                temperature=0
            )
            llm_with_tools = llm.bind_tools(all_tools)

            def agent_node(state: MessagesState):
                """Agent 推理节点：调用 LLM 决定下一步行动，并处理 API 兼容性问题"""

                sanitized_message = []
                for msg in state['messages']:
                    # 拦截ToolMessage， 如果其内容是列表内容，将其提取为纯字符串，用以兼容DeepSeek等OpenAI的接口需求
                    if isinstance(msg, ToolMessage) and isinstance(msg.content, list):
                        extracted_text = ""
                        for block in msg.content:
                            if isinstance(block, dict) and "text" in block:
                                extracted_text += block["text"]
                            else:
                                extracted_text += str(block)
                        # 用提取出的纯文本重构一条兼容接口的ToolMessage
                        sanitized_msg = ToolMessage(
                            content=extracted_text,
                            name=msg.name,
                            tool_call_id = msg.tool_call_id
                        )
                        sanitized_message.append(sanitized_msg)
                    else:
                        sanitized_message.append(msg)

                # 注入系统提示词，强化它作为 K8s 运维助手的角色
                SYSTEM_PROMPT = """你是一个资深的高级 Kubernetes 运维专家。
                你的职责是诊断集群异常、分析性能瓶颈并提供修复建议。你已连接到多个 K8s 集群与观测工具链（如 MCP 提供的能力）。

                【排查原则】
                1. 严谨求证：在得出任何结论前，必须先调用相关工具获取客观数据（如 Pod 状态、事件、日志）。绝不凭空猜测。
                2. 关联分析：如果发现 Pod Crash，必须主动联想是否需要查询前置依赖（如 ConfigMap、Secret 是否存在，网络是否可达）。
                3. 最小权限：当用户要求执行高危操作（如删除、重启、扩缩容）时，必须先列出操作的影响范围，并在回答中明确要求用户确认。

                【数据格式化】
                当你调用工具（如 pods_list、pods_top 等）获取到集群资源时，底层接口通常会返回带有大量制表符、特殊字符（如 <none>）以及冗长 Labels 的原始乱码文本。
                **绝对不允许**将原始文本直接输出给用户！你必须从中提取关键信息，并严格使用整洁的 Markdown 表格呈现。

                表格只需包含核心字段，以Pod输出为例：
                | Namespace | Pod Name | Status | Restarts | Age | IP |
                |---|---|---|---|---|---|
                (过滤掉那些太长且不影响排障的列，如 Labels、Nominated Node 等)

                【输出规范】
                - 思考过程对用户不可见，你可以自由调用工具。
                - 在最终回复用户时，请使用清晰的 Markdown 格式（如表格、代码块）呈现数据。
                - 解释故障原因时，请尽量结合底层原理（如 Linux 内核、网络栈、K8s 调度机制）。
                """
                # 将系统消息插在对话最前面
                messages = [SYSTEM_PROMPT] + sanitized_message
                response = llm_with_tools.invoke(messages)
    
                return {"messages": [response]}
            
            def rag_node(state: MessagesState):
                RAG_PROMPT = """你是一个严谨的 Kubernetes 文档研究员。
                你的任务是使用 k8s_doc_retriever 工具查阅官方文档，并针对用户的报错或疑问，提取出最核心的排查步骤或修复建议。
                注意：
                1. 你的总结必须简明扼要，控制在 300 字以内。
                2. 只输出干货，不要说废话。
                """
                response = llm.invoke([RAG_PROMPT] + state["messages"])
                return {"message": [response]}
            
            def supervisor_node(state: MessagesState) -> dict:
                """主管：协调各专家 Agent 的工作"""
                system = SystemMessage(content="""你是一个工作流主管。
                根据任务进度决定下一步应该由哪个 Agent 处理。
                分析对话历史，只返回以下之一：RESEARCH、WRITING、REVIEW、FINISH
                - RESEARCH：需要收集更多信息
                - WRITING：信息充足，可以开始写作
                - REVIEW：写作完成，需要审核
                - FINISH：任务已完成
                """)

                response = llm.invoke([system] + state["messages"])
                return {"messages": [response]}


            builder = StateGraph(MessagesState)
            builder.add_node("agent", agent_node)
            builder.add_node("rag", rag_node)
            builder.add_node("tools", ToolNode(all_tools))

            builder.add_edge(START, "agent")
            builder.add_edge("agent", "rag")
            builder.add_conditional_edges("agent", tools_condition)
            builder.add_edge("tools", "agent")
            graph = builder.compile(checkpointer=memory)

            # 4. 进入循环提问环节
            print("\n" + "="*30)
            print("🚀 K8s 运维 Agent 已就绪")
            print("输入 'exit' 或 'quit' 退出程序")
            print("="*30)

            # 为当前会话定义一个唯一的 ID，用于检索记忆
            config = {"configurable": {"thread_id": "k8s_ops_session_001"}}

            while True:
                # 获取用户输入
                try:
                    user_input = await ainput("\n[User]>")
                except EOFError:
                    break

                # 退出判定
                if user_input.lower() in ["exit", "quit", "退出"]:
                    print("再见！正在关闭 K8s 运维助手...")
                    break

                if not user_input.strip():
                    continue

                try:
                    # 异步执行 Agent 逻辑
                    # 注意：这里传入了 config 以维持对话上下文
                    result = await graph.ainvoke(
                        {"messages": [HumanMessage(content=user_input)]}, 
                        config=config
                    )
                
                    # 打印 Agent 的最后一条回复内容
                    # 在 ReAct 循环中，通常最后一条是 AI 的总结陈词，由于引入了memory检查点，result不再是每次对话的增量，是从第一个问题到最后一个问题的所有答案
                    # 因此，只打印最后一条消息
                    last_msg = result["messages"][-1]
                    # 过滤掉中间过程的 tool_calls 打印，只输出最终自然语言回复
                    if last_msg.type == "ai" and last_msg.content and not last_msg.tool_calls:
                        print(f"\n[Agent] 🤖: {last_msg.content}")

                except Exception as e:
                    print("\n❌ 大脑推理或通信出现严重异常！")
                    traceback.print_exc() # 打印真实的报错堆栈
                    print("💡 提示：如果是 API 报错或 Token 超限，真正的错误原因会在上方显示。MCP Server 连接可能已断开，建议重启脚本。")
                    break # 发生严重异常后跳出循环

if __name__ == "__main__":
    # 运行异步事件循环
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass