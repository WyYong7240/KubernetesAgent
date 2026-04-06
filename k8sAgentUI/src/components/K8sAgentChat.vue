<template>
  <div class="full-screen-layout">
    <header class="app-header">
      <div class="logo-area">
        <span class="icon">☸️</span>
        <h1>K8s Copilot</h1>
      </div>
      <div class="status-indicator">
        <div class="dot" :class="{ 'is-online': isConnected }"></div>
        <span>{{ isConnected ? 'Agent 在线' : '连接中...' }}</span>
      </div>
    </header>

    <main class="chat-main" ref="messagesContainer">
      <div class="chat-content">
        <div 
          v-for="(msg, index) in messages" 
          :key="index"
          :class="['message-row', msg.role]"
        >
          <div class="avatar">{{ msg.role === 'user' ? '🧑‍💻' : '🤖' }}</div>
          <div class="message-content">
            <div class="message-sender">{{ msg.role === 'user' ? 'You' : 'K8s Agent' }}</div>
            <div 
              v-if="msg.role === 'ai'" 
              class="markdown-body" 
              v-html="renderMarkdown(msg.content)"
            ></div>
            <div v-else class="text-body">{{ msg.content }}</div>
          </div>
        </div>

        <div v-if="isLoading" class="message-row ai">
          <div class="avatar">🤖</div>
          <div class="message-content">
            <div class="message-sender">K8s Agent</div>
            <div class="typing-indicator">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </div>
    </main>

    <footer class="app-footer">
      <div class="input-container">
        <textarea 
          v-model="inputText" 
          @keydown.enter.prevent="sendMessage"
          placeholder="输入 K8s 排障需求，例如：查一下 default 命名空间的 Pod 状态..."
          :disabled="isLoading"
          rows="1"
          @input="autoResize"
          ref="textareaRef"
        ></textarea>
        <button 
          class="send-btn" 
          @click="sendMessage" 
          :disabled="isLoading || !inputText.trim()"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
      <div class="footer-tip">Powered by LangGraph & MCP K8s Server</div>
    </footer>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue';
import { marked } from 'marked';
import hljs from 'highlight.js';
// 引入代码高亮主题（推荐 github-dark 配合 K8s 运维风格）
import 'highlight.js/styles/github-dark.css';

// 配置 marked 使用 highlight.js 进行代码高亮
marked.setOptions({
  highlight: function (code, lang) {
    const language = hljs.getLanguage(lang) ? lang : 'plaintext';
    return hljs.highlight(code, { language }).value;
  },
  langPrefix: 'hljs language-', // 配合 highlight.js 样式
  breaks: true, // 支持回车换行
  gfm: true     // 开启 GitHub 风格 Markdown（支持表格）
});

const inputText = ref('');
const messages = ref([
  { role: 'ai', content: '你好！我是你的 Kubernetes 运维智能体。有什么可以帮你的？' }
]);
const isLoading = ref(false);
const isConnected = ref(true);
const messagesContainer = ref(null);
const textareaRef = ref(null);

// 渲染 Markdown
const renderMarkdown = (text) => marked(text || '');

// 自动滚动到底部
const scrollToBottom = async () => {
  await nextTick();
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
  }
};

// 文本框高度自适应
const autoResize = () => {
  const el = textareaRef.value;
  if (el) {
    el.style.height = 'auto';
    el.style.height = (el.scrollHeight < 200 ? el.scrollHeight : 200) + 'px';
  }
};

const sendMessage = async () => {
  const text = inputText.value.trim();
  if (!text || isLoading.value) return;

  messages.value.push({ role: 'user', content: text });
  inputText.value = '';
  // 重置文本框高度
  if (textareaRef.value) textareaRef.value.style.height = 'auto';
  
  isLoading.value = true;
  scrollToBottom();

  try {
    const response = await fetch('http://localhost:38888/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        message: text,
        thread_id: 'vue-fullscreen-user' 
      })
    });

    if (!response.ok) throw new Error('网络响应异常');

    const data = await response.json();
    messages.value.push({ role: 'ai', content: data.reply });
  } catch (error) {
    console.error('API Error:', error);
    messages.value.push({ role: 'ai', content: '**❌ 抱歉，与 K8s Agent 后端的连接发生故障。**' });
  } finally {
    isLoading.value = false;
    scrollToBottom();
  }
};
</script>

<style>
/* 全局重置，确保没有讨厌的默认滚动条 */
body, html {
  margin: 0;
  padding: 0;
  height: 100%;
  width: 100%;
}
</style>

<style scoped>
.full-screen-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background-color: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* Header 样式 */
.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  height: 60px;
  background-color: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  z-index: 10;
}

.logo-area { display: flex; align-items: center; gap: 10px; }
.logo-area .icon { font-size: 24px; }
.logo-area h1 { margin: 0; font-size: 18px; color: #0f172a; font-weight: 600; }

.status-indicator { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #64748b; }
.dot { width: 8px; height: 8px; border-radius: 50%; background-color: #cbd5e1; }
.dot.is-online { background-color: #10b981; box-shadow: 0 0 8px rgba(16, 185, 129, 0.4); }

/* 主聊天区 */
.chat-main {
  flex: 1;
  overflow-y: auto;
  padding: 20px 0;
  scroll-behavior: smooth;
}

.chat-content {
  max-width: 850px; /* 限制居中最大宽度，阅读体验更好 */
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 30px;
  padding: 0 20px;
}

.message-row {
  display: flex;
  gap: 16px;
  width: 100%;
}

.message-row.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  flex-shrink: 0;
}

.user .avatar { background: #3b82f6; }

.message-content {
  flex: 1;
  max-width: calc(100% - 52px);
  display: flex;
  flex-direction: column;
}

.user .message-content { align-items: flex-end; }

.message-sender {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 6px;
  font-weight: 500;
}

.text-body {
  background: #3b82f6;
  color: white;
  padding: 12px 18px;
  border-radius: 12px 2px 12px 12px;
  font-size: 15px;
  line-height: 1.5;
  white-space: pre-wrap;
}

/* --- 🌟 深度优化的 Markdown 样式 --- */
.markdown-body {
  background: #ffffff;
  padding: 16px 20px;
  border-radius: 2px 12px 12px 12px;
  font-size: 15px;
  line-height: 1.6;
  color: #334155;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  border: 1px solid #e2e8f0;
  width: 100%;
  box-sizing: border-box;
}

.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) { margin-top: 0; margin-bottom: 12px; font-weight: 600; color: #0f172a; }
.markdown-body :deep(p) { margin: 0 0 12px 0; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }

/* 代码块高亮优化 */
.markdown-body :deep(pre) {
  margin: 12px 0;
  padding: 16px;
  background-color: #0d1117 !important; /* 暗黑背景 */
  border-radius: 8px;
  overflow-x: auto;
}
.markdown-body :deep(pre code) {
  background: transparent;
  padding: 0;
  color: #e6edf3;
  font-size: 13.5px;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
}

/* 行内代码优化 */
.markdown-body :deep(code) {
  background-color: #f1f5f9;
  color: #ef4444;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13.5px;
  font-family: monospace;
}

/* K8s Table 表格优化 */
.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
  font-size: 14px;
}
.markdown-body :deep(th), .markdown-body :deep(td) {
  border: 1px solid #e2e8f0;
  padding: 8px 12px;
  text-align: left;
}
.markdown-body :deep(th) { background-color: #f8fafc; font-weight: 600; }
.markdown-body :deep(tr:nth-child(even)) { background-color: #fcfcfc; }

/* 列表优化 */
.markdown-body :deep(ul), .markdown-body :deep(ol) { margin: 0 0 12px 0; padding-left: 24px; }
.markdown-body :deep(li) { margin-bottom: 4px; }

/* 底部输入区 */
.app-footer {
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
  padding: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.input-container {
  max-width: 850px;
  width: 100%;
  position: relative;
  display: flex;
  align-items: flex-end;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 16px;
  padding: 4px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.input-container:focus-within {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  background: #ffffff;
}

textarea {
  flex: 1;
  min-height: 24px;
  max-height: 200px;
  padding: 12px 16px;
  background: transparent;
  border: none;
  resize: none;
  font-size: 15px;
  line-height: 1.5;
  color: #0f172a;
  outline: none;
}

.send-btn {
  width: 40px;
  height: 40px;
  margin: 4px;
  border-radius: 12px;
  background: #3b82f6;
  color: white;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.send-btn svg { width: 20px; height: 20px; }
.send-btn:hover:not(:disabled) { background: #2563eb; transform: translateY(-1px); }
.send-btn:disabled { background: #cbd5e1; cursor: not-allowed; color: #94a3b8; }

.footer-tip {
  margin-top: 12px;
  font-size: 12px;
  color: #94a3b8;
}

/* 加载动画 */
.typing-indicator {
  display: inline-flex;
  background: #ffffff;
  padding: 14px 18px;
  border-radius: 2px 12px 12px 12px;
  border: 1px solid #e2e8f0;
}
.typing-indicator span {
  width: 6px; height: 6px;
  background: #94a3b8;
  border-radius: 50%;
  margin: 0 3px;
  animation: bounce 1.4s infinite ease-in-out both;
}
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}
</style>