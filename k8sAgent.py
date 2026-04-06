import asyncio
import os
import traceback
from typing import Literal, TypedDict

from aioconsole import ainput
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver # 引入内存保存器件

# 引入 MCP 客户端依赖
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from langchain_mcp_adapters.tools import load_mcp_tools

load_dotenv()

class AgentState(MessagesState):
    next: str

async def main():
    # ==========================================
    # 1. 定义两个 Server 的启动参数
    # ==========================================
    # Server A：你的自定义 Python 脚本
    server_a_params = StdioServerParameters(
        command="python",
        args=["local_mcp_server.py"],
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
            # all_tools = tools_custom + tools_kube
            # print(f"✅ 成功从 Server 加载了 {len(all_tools)} 个工具！")


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

            def sanitize_messages(messages: list) -> list:
                """
                无副作用的数据清洗逻辑：重建 ToolMessage，兼容 DeepSeek/OpenAI
                """
                sanitized_messages = []
                for msg in messages:
                    if isinstance(msg, ToolMessage) and isinstance(msg.content, list):
                        extracted_text = ""
                        for block in msg.content:
                            if isinstance(block, dict) and "text" in block:
                                extracted_text += block["text"]
                            else:
                                extracted_text += str(block)

                        sanitized_msg = ToolMessage(
                            content=extracted_text,
                            name=msg.name,
                            tool_call_id=msg.tool_call_id
                        )
                        sanitized_messages.append(sanitized_msg)
                    else:
                        sanitized_messages.append(msg)

                return sanitized_messages

            class Route(TypedDict):
                next: Literal["RESEARCH", "OPS", "CHAT", "FINISH"]
            def supervisor_node(state: AgentState) -> dict:
                """主管：大统领，只负责看历史消息并派单，不干脏活"""
    
                system_prompt = f"""你是一个 Kubernetes 运维专家团队的主管。
                根据用户需求和当前对话历史，决定下一步应该交由哪个专家处理。

                【重要指令】：你必须以 JSON 格式输出，且 JSON 中只能包含一个 `next` 字段。

                分析对话历史，只返回以下选项之一：
                - RESEARCH：需要收集知识、查阅 K8s 官方文档、排错指南或内部 SOP 时。
                - OPS：信息充足，需要直接操作 K8s 集群（如查Pod、看日志、删资源等）时。
                - CHAT：当用户只是在进行日常问候（如“你好”、“在吗”），或者提出完全不需要工具就能回答的常识性问题时。
                - FINISH：
                    1. 用户的提问已经得到了完整的解答。
                    2. 对话历史中的最后一条消息是 AI 发出的（例如 AI 正在向用户打招呼、或者 AI 正在反问用户以获取更多信息），此时必须选择 FINISH，暂停系统内部流转，等待用户的真实回答。
                    3. 用户只是在进行日常问候或闲聊（如“你好”、“在吗”）。
                """
                # 强制大模型只输出包含 next 字段的 JSON，完美匹配路由词
                router_llm = llm.with_structured_output(Route, method="json_mode")

                clean_message = sanitize_messages(state["messages"])
                response = router_llm.invoke(
                    [SystemMessage(content=system_prompt)] + clean_message
                )

                print(f"\n[主管派单] 🎯 决定将任务交给: {response['next']}")

                # 只需要返回 next 状态，不需要添加 messages，因为主管不直接和用户说话
                return {"next": response["next"]}

            def ops_node(state: AgentState) -> dict:
                """Agent 推理节点：调用 LLM 决定下一步行动，并处理 API 兼容性问题"""

                # 注入系统提示词，强化它作为 K8s 运维助手的角色
                SYSTEM_PROMPT = """你是 K8s 运维专员，请使用工具完成主管派发的任务。
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

                ops_llm = llm.bind_tools(tools_kube)

                # 将系统消息插在对话最前面
                clean_message = sanitize_messages(state["messages"])
                messages = [SystemMessage(content=SYSTEM_PROMPT)] + clean_message
                response = ops_llm.invoke(messages)
    
                return {"messages": [response]}

            def route_after_ops(state: AgentState) -> Literal["ops_tools", "supervisor"]:
                """判断 OPS 专员是否请求了工具"""
                messages = state["messages"]
                last_message = messages[-1]

                # 如果最后一条消息包含 tool_calls，说明大模型想用工具，必须去执行！
                if hasattr(last_message, 'tool_calls') and len(last_message.tool_calls) > 0:
                    print("[流转日志] 🛠️ OPS 专员正在执行 K8s 工具...")
                    return "ops_tools"

                # 如果没有 tool_calls，说明专员已经得出结论，直接向主管汇报
                print("[流转日志] 📝 OPS 专员操作完毕，向主管汇报。")
                return "supervisor"
            
            def rag_node(state: AgentState):
                RAG_PROMPT = """你是一个严谨的 Kubernetes 文档研究员。
                你的任务是使用 k8s_doc_retriever 工具查阅官方文档，并针对用户的报错或疑问，提取出最核心的排查步骤或修复建议。
                注意：
                1. 你的总结必须简明扼要，控制在 300 字以内。
                2. 只输出干货，不要说废话。
                """
                rag_llm = llm.bind_tools(tools_custom)

                clean_message = sanitize_messages(state["messages"])
                response = rag_llm.invoke([SystemMessage(content=RAG_PROMPT)] + clean_message)
                return {"message": [response]}

            def route_after_rag(state: AgentState) -> Literal["rag_tools", "supervisor"]:
                """判断 RAG 专员是否请求了工具"""
                messages = state["messages"]
                last_message = messages[-1]

                # 如果最后一条消息包含 tool_calls，说明大模型想用工具，必须去执行！
                if hasattr(last_message, 'tool_calls') and len(last_message.tool_calls) > 0:
                    print("[流转日志] 🛠️ RAG 专员正在执行 RAG 工具...")
                    return "rag_tools"

                # 如果没有 tool_calls，说明专员已经得出结论，直接向主管汇报
                print("[流转日志] 📝 RAG 专员操作完毕，向主管汇报。")
                return "supervisor"

            def chat_node(state: AgentState) -> dict:
                """接待员：没有绑定任何工具，只负责用大模型的常识和用户友好地闲聊"""
    
                # 这里不需要绑定 bind_tools，直接用普通的 llm
                sys_msg = SystemMessage(content="你是 K8s 运维团队的 AI 助理。请用简短、友好的语言回复用户的问候或闲聊。不要使用任何 Markdown 表格。")
    
                response = llm.invoke([sys_msg] + state["messages"])
    
                return {"messages": [response]}


            # 注册节点
            builder = StateGraph(AgentState)
            builder.add_node("supervisor", supervisor_node)
            builder.add_node("OPS", ops_node)
            builder.add_node("CHAT", chat_node)
            builder.add_node("RESEARCH", rag_node)
            builder.add_node("ops_tools", ToolNode(tools_kube))
            builder.add_node("rag_tools", ToolNode(tools_custom))


            # 2. 定义控制流
            # 每次开始都先找主管
            builder.add_edge(START, "supervisor")

            # 主管根据 state["next"] 的值决定走哪条路
            builder.add_conditional_edges(
                "supervisor",
                lambda state: state["next"],
                {
                    "OPS": "OPS",
                    "RESEARCH": "RESEARCH",
                    "CHAT": "CHAT",
                    "FINISH": END
                }
            )

            # 员工干完活后，必须无条件向主管汇报（跳回主管节点，由主管决定是继续还是结束）
            # builder.add_edge("OPS", "supervisor")
            # 替换为条件路由：OPS 思考完后，根据情况决定是去用工具，还是找主管
            builder.add_conditional_edges(
                "OPS",
                route_after_ops
            )
            # builder.add_edge("RESEARCH", "supervisor")
            builder.add_conditional_edges(
                "RESEARCH",
                route_after_rag 
            )
            builder.add_edge("CHAT", "supervisor")
            builder.add_edge("ops_tools", "OPS")
            builder.add_edge("rag_tools", "RESEARCH")

            # 3. 编译图
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