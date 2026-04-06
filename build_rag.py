import os
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

def build_markdown_knowledge_base(docs_dir: str, persist_dir: str):
    """
    遍历本地 Markdown 文件夹，提取内容及元数据，并构建向量数据库。
    """
    print(f"🔍 开始扫描目录: {docs_dir}")
    
    # 1. 定义我们想要保留作为元数据的 Markdown 标题层级
    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    
    # 2. 定义底层文本切分器（防止某个标题下的内容实在太长，超过 LLM 上下文）
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, 
        chunk_overlap=200
    )

    all_splits = []

    # 3. 遍历文件夹，加载所有 .md 文件
    for root, _, files in os.walk(docs_dir):
        for file in files:
            if file.endswith(".md"):
                file_path = os.path.join(root, file)
                
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        markdown_document = f.read()
                    
                    # 第一步：按 Markdown 标题切分，自动生成带 Header 元数据的 Document
                    header_splits = markdown_splitter.split_text(markdown_document)
                    
                    # 第二步：对长文本块进行二次长度切分，并注入【文件名】作为额外的元数据
                    for split in header_splits:
                        # 注入来源文件路径
                        split.metadata["source_file"] = file_path 
                        
                        # 按长度进一步切分
                        final_chunks = text_splitter.split_documents([split])
                        all_splits.extend(final_chunks)
                        
                except Exception as e:
                    print(f"⚠️ 读取文件 {file_path} 时出错: {e}")

    print(f"✂️ 共切割出 {len(all_splits)} 个带元数据的文本块。")
    if len(all_splits) > 0:
        print("📄 示例文本块 Metadata:", all_splits[0].metadata)

    # 4. 初始化 Embedding 模型
    print("🧠 正在加载 Embedding 模型 (首次运行会下载权重)...")
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    # 5. 持久化到 Chroma 数据库
    print(f"💾 正在写入向量数据库: {persist_dir}...")
    vectorstore = Chroma.from_documents(
        documents=all_splits,
        embedding=embeddings,
        persist_directory=persist_dir
    )
    
    print("✅ 本地 Markdown 知识库构建完成！")

if __name__ == "__main__":
    # 假设你的 markdown 文件存放在当前目录的 k8s_docs 文件夹下
    # 数据库将保存在 k8s_rag_db 文件夹下
    build_markdown_knowledge_base(
        docs_dir="./website/content/zh-cn/docs", 
        persist_dir="./k8s_rag_db"
    )