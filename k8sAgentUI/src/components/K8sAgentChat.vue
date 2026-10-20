<template>
  <div class="app-container">
    <aside class="sidebar no-print">
      <div class="sidebar-header">
        <div class="logo-area">
          <span class="icon">☸️</span>
          <h1>K8s Copilot</h1>
        </div>
      </div>
      
      <div class="sidebar-actions">
        <button class="new-chat-btn" @click="startNewChat" :disabled="isLoading">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          开启新对话
        </button>
      </div>

      <div class="history-list">
        <div class="history-label">历史记录</div>
        <div 
          v-for="(msgs, id) in chatHistory" 
          :key="id"
          class="history-item"
          :class="{ active: id === currentThreadId }"
          @click="switchChat(id)"
        >
          <div class="chat-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="msg-icon">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
            <span>{{ getChatTitle(msgs) }}</span>
          </div>
          <button class="delete-btn" @click.stop="deleteChat(id)" title="删除对话">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </button>
        </div>
        <div v-if="Object.keys(chatHistory).length === 0" class="empty-history">
          暂无历史对话
        </div>
      </div>
    </aside>

    <main class="main-workspace">
      <header class="workspace-header no-print">
        <div class="current-chat-info">
          <span class="thread-badge">ID: {{ currentThreadId.substring(0, 8) }}...</span>
        </div>
        
        <div class="header-right-zone">
          <div class="export-group">
            <button class="action-btn" @click="exportToMarkdown" title="导出为 Markdown 文档">📝 导出 MD</button>
            <button class="action-btn" @click="exportToPDF" title="导出为 PDF 报表">📄 导出 PDF</button>
          </div>
          <div class="status-indicator">
            <div class="dot" :class="{ 'is-online': isConnected }"></div>
            <span>{{ isConnected ? 'Agent 在线' : '连接中...' }}</span>
          </div>
        </div>
      </header>

      <div class="chat-main" ref="messagesContainer" id="print-area">
        <div class="chat-content">
          <div 
            v-for="(msg, index) in currentMessages" 
            :key="index"
            :class="['message-row', msg.role]"
          >
            <div class="avatar">{{ msg.role === 'user' ? '🧑‍💻' : '🤖' }}</div>
            <div class="message-content">
              <div class="message-sender">{{ msg.role === 'user' ? (msg.name || 'User') : 'K8s Agent' }}</div>
              <div 
                v-if="msg.role === 'ai'" 
                class="markdown-body" 
                v-html="renderMarkdown(msg.content)"
              ></div>
              <div v-else class="text-body">{{ msg.content }}</div>
            </div>
          </div>

          <div v-if="isLoading" class="message-row ai no-print">
            <div class="avatar">🤖</div>
            <div class="message-content">
              <div class="message-sender">K8s Agent</div>
              <div class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <footer class="app-footer no-print">
        <div class="input-container">
          <textarea 
            v-model="inputText" 
            @keydown.enter.prevent="sendMessage()"
            placeholder="输入 K8s 排障需求，或从右侧选择预设问题..."
            :disabled="isLoading"
            rows="1"
            @input="autoResize"
            ref="textareaRef"
          ></textarea>
          <button 
            class="send-btn" 
            @click="sendMessage()" 
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
    </main>

    <aside class="right-sidebar no-print">
      <div class="config-section">
        <h3 class="section-title">💡 预设指令</h3>
        <div class="preset-list">
          <div 
            v-for="(question, index) in presetQuestions" 
            :key="index"
            class="preset-item-wrapper"
          >
            <button 
              class="preset-btn"
              @click="sendPreset(question)"
              :disabled="isLoading"
            >
              {{ question }}
            </button>
            <button class="del-preset-btn" @click.stop="deletePreset(question)">×</button>
          </div>
        </div>
        
        <div class="add-user-area" style="margin-top: 12px;">
          <input 
            type="text" 
            v-model="newPreset" 
            placeholder="添加新预设指令..." 
            @keydown.enter="addPreset"
          />
          <button @click="addPreset">+</button>
        </div>
      </div>

      <div class="divider"></div>

      <div class="config-section">
        <h3 class="section-title">👤 操作人身份</h3>
        
        <div class="user-list">
          <label 
            v-for="user in userList" 
            :key="user" 
            class="user-radio"
            :class="{ active: currentUser === user }"
          >
            <input type="radio" :value="user" v-model="currentUser" name="userSelect" />
            <span class="radio-custom"></span>
            {{ user }}
            <span v-if="user !== 'Admin'" class="del-user" @click.prevent="deleteUser(user)">×</span>
          </label>
        </div>

        <div class="add-user-area">
          <input 
            type="text" 
            v-model="newUserName" 
            placeholder="添加新操作人..." 
            @keydown.enter="addCustomUser"
          />
          <button @click="addCustomUser">+</button>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, watch } from 'vue';
import { marked } from 'marked';
import hljs from 'highlight.js';
import 'highlight.js/styles/github-dark.css';

marked.setOptions({
  highlight: function (code, lang) {
    const language = hljs.getLanguage(lang) ? lang : 'plaintext';
    return hljs.highlight(code, { language }).value;
  },
  langPrefix: 'hljs language-', 
  breaks: true, 
  gfm: true     
});

// --- 常量与 Storage ---
const LOCAL_STORAGE_KEY = 'k8s_agent_chat_history';
const USER_STORAGE_KEY = 'k8s_agent_users';
const PRESET_STORAGE_KEY = 'k8s_agent_presets'; // 🌟 新增预设 Storage Key
const generateThreadId = () => 'chat_' + Math.random().toString(36).substring(2, 9);
const defaultGreeting = { role: 'ai', content: '你好！我是你的 Kubernetes 运维智能体。有什么可以帮你的？' };

// --- 状态管理 ---
const chatHistory = ref({});
const currentThreadId = ref('');
const inputText = ref('');
const isLoading = ref(false);
const isConnected = ref(true);
const messagesContainer = ref(null);
const textareaRef = ref(null);

// 右侧栏状态
const presetQuestions = ref([
  "帮我检查 default 命名空间下所有报错的 Pod",
  "查看 kube-system 组件的健康状态",
  "创建一个 Nginx 测试服务暴露 80 端口",
  "获取当前集群的 Node 节点资源利用率"
]);
const newPreset = ref(''); // 🌟 新增绑定

const userList = ref(['Admin']);
const currentUser = ref('Admin');
const newUserName = ref('');

// --- 初始化与持久化 ---
onMounted(() => {
  const storedHistory = localStorage.getItem(LOCAL_STORAGE_KEY);
  if (storedHistory) {
    chatHistory.value = JSON.parse(storedHistory);
    const keys = Object.keys(chatHistory.value);
    if (keys.length > 0) {
      currentThreadId.value = keys[keys.length - 1];
    } else {
      startNewChat();
    }
  } else {
    startNewChat();
  }
  
  const storedUsers = localStorage.getItem(USER_STORAGE_KEY);
  if (storedUsers) {
    const parsed = JSON.parse(storedUsers);
    userList.value = parsed.list;
    currentUser.value = parsed.current;
  }

  // 🌟 恢复自定义预设指令
  const storedPresets = localStorage.getItem(PRESET_STORAGE_KEY);
  if (storedPresets) {
    presetQuestions.value = JSON.parse(storedPresets);
  }
  
  scrollToBottom();
});

watch(chatHistory, (newVal) => {
  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(newVal));
}, { deep: true });

watch([userList, currentUser], () => {
  localStorage.setItem(USER_STORAGE_KEY, JSON.stringify({
    list: userList.value,
    current: currentUser.value
  }));
}, { deep: true });

// 🌟 监听保存自定义预设
watch(presetQuestions, (newVal) => {
  localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(newVal));
}, { deep: true });


// --- 核心方法 ---
const currentMessages = computed(() => {
  return chatHistory.value[currentThreadId.value] || [];
});

const getChatTitle = (msgs) => {
  const firstUserMsg = msgs.find(m => m.role === 'user');
  if (firstUserMsg) {
    const content = firstUserMsg.content.trim();
    return content.length > 14 ? content.substring(0, 14) + '...' : content;
  }
  return '全新的对话';
};

const getSafeTimestamp = () => {
  const now = new Date();
  const YYYY = now.getFullYear();
  const MM = String(now.getMonth() + 1).padStart(2, '0');
  const DD = String(now.getDate()).padStart(2, '0');
  const HH = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');
  return `${YYYY}-${MM}-${DD}__${HH}-${mm}-${ss}`;
};

const getSafeFileNameTitle = () => {
  const rawTitle = getChatTitle(currentMessages.value);
  if (rawTitle === '全新的对话') return 'K8s_Report';
  return rawTitle.replace(/[\\/:*?"<>|\s]/g, '_');
};

// 🌟 提取当前操作员的安全名称（过滤掉可能的非法符号）
const getSafeOperatorName = () => {
  return currentUser.value.replace(/[\\/:*?"<>|\s]/g, '_');
};

const exportToMarkdown = () => {
  if (currentMessages.value.length <= 1) return;
  const fileTitle = getSafeFileNameTitle();
  const safeOperator = getSafeOperatorName(); // 获取操作员
  const displayTitle = getChatTitle(currentMessages.value);
  
  let mdContent = `# K8s 运维排障报告 - ${displayTitle}\n\n`;
  mdContent += `- **会话 ID:** \`${currentThreadId.value}\`\n`;
  mdContent += `- **操作人员:** ${currentUser.value}\n`;
  mdContent += `- **导出时间:** ${new Date().toLocaleString()}\n\n`;
  mdContent += `---\n\n`;

  currentMessages.value.forEach(msg => {
    if (msg.role === 'user') {
      const uName = msg.name || 'User';
      mdContent += `### 🧑‍💻 [${uName}]\n\n> ${msg.content}\n\n`;
    } else {
      mdContent += `### 🤖 K8s Agent\n\n${msg.content}\n\n`;
    }
    mdContent += `---\n\n`;
  });

  const blob = new Blob([mdContent], { type: 'text/markdown;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  // 🌟 拼装：标题_操作员_时间戳
  link.download = `${fileTitle}_${safeOperator}_${getSafeTimestamp()}.md`;
  link.click();
  URL.revokeObjectURL(url);
};

const exportToPDF = () => {
  const fileTitle = getSafeFileNameTitle();
  const safeOperator = getSafeOperatorName(); // 获取操作员
  const originalTitle = document.title;
  // 🌟 拼装：标题_操作员_时间戳
  document.title = `${fileTitle}_${safeOperator}_${getSafeTimestamp()}`;
  window.print();
  document.title = originalTitle;
};

// --- 右侧栏逻辑 ---
const sendPreset = (question) => {
  if (isLoading.value) return;
  inputText.value = question;
  sendMessage();
};

// 🌟 添加预设
const addPreset = () => {
  const text = newPreset.value.trim();
  if (text && !presetQuestions.value.includes(text)) {
    presetQuestions.value.push(text);
  }
  newPreset.value = '';
};

// 🌟 删除预设
const deletePreset = (question) => {
  presetQuestions.value = presetQuestions.value.filter(q => q !== question);
};

const addCustomUser = () => {
  const name = newUserName.value.trim();
  if (name && !userList.value.includes(name)) {
    userList.value.push(name);
    currentUser.value = name; 
  }
  newUserName.value = '';
};

const deleteUser = (name) => {
  userList.value = userList.value.filter(u => u !== name);
  if (currentUser.value === name) {
    currentUser.value = userList.value[0]; 
  }
};

const startNewChat = () => {
  if (isLoading.value) return;
  const newId = generateThreadId();
  chatHistory.value[newId] = [{ ...defaultGreeting }];
  currentThreadId.value = newId;
  resetInput();
  scrollToBottom();
};

const switchChat = (id) => {
  if (isLoading.value || currentThreadId.value === id) return;
  currentThreadId.value = id;
  resetInput();
  scrollToBottom();
};

const deleteChat = (id) => {
  if (isLoading.value) return;
  const temp = { ...chatHistory.value };
  delete temp[id];
  chatHistory.value = temp;
  const remainingKeys = Object.keys(chatHistory.value);
  if (remainingKeys.length === 0) {
    startNewChat();
  } else if (currentThreadId.value === id) {
    currentThreadId.value = remainingKeys[remainingKeys.length - 1];
  }
};

const renderMarkdown = (text) => marked(text || '');

const scrollToBottom = async () => {
  await nextTick();
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
  }
};

const resetInput = () => {
  inputText.value = '';
  if (textareaRef.value) textareaRef.value.style.height = 'auto';
};

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

  if (!chatHistory.value[currentThreadId.value]) {
    chatHistory.value[currentThreadId.value] = [];
  }
  
  chatHistory.value[currentThreadId.value].push({ 
    role: 'user', 
    name: currentUser.value, 
    content: text 
  });
  
  resetInput();
  isLoading.value = true;
  scrollToBottom();

  const activeThreadId = currentThreadId.value;

  try {
    const response = await fetch('http://localhost:38888/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, thread_id: activeThreadId })
    });

    if (!response.ok) throw new Error('网络响应异常');

    const data = await response.json();
    chatHistory.value[activeThreadId].push({ role: 'ai', content: data.reply });
  } catch (error) {
    console.error('API Error:', error);
    chatHistory.value[activeThreadId].push({ role: 'ai', content: '**❌ 抱歉，与 K8s Agent 后端的连接发生故障。**' });
  } finally {
    isLoading.value = false;
    if (currentThreadId.value === activeThreadId) {
      scrollToBottom();
    }
  }
};
</script>

<style>
/* ================= 全局重置区 ================= */
/* 🌟 核心修复 1：彻底粉碎 Vue/Vite 默认样式的干扰 */
html, body, #app { 
  margin: 0 !important; 
  padding: 0 !important; 
  width: 100% !important; 
  height: 100% !important; 
  max-width: 100% !important; /* 覆盖 Vite 默认的 max-width: 1280px */
  overflow: hidden !important; 
  background-color: #ffffff !important; /* 强制白底，消灭黑边 */
  text-align: left !important; /* 强制左对齐，解决居中问题 */
}

/* 打印 PDF 时的媒体查询保持不变 */
@media print {
  .sidebar, .workspace-header, .app-footer, .no-print, .send-btn { display: none !important; }
  .app-container, .main-workspace, .chat-main { display: block !important; width: 100% !important; height: auto !important; overflow: visible !important; background: #fff !important; }
  .chat-content { max-width: 100% !important; padding: 0 !important; }
  .markdown-body { border: none !important; box-shadow: none !important; padding: 0 !important; }
  .message-row { page-break-inside: avoid; margin-bottom: 20px; }
}
</style>

<style scoped>
/* ================= 组件样式区 ================= */
/* 🌟 将 100vw 改为 100%，彻底防止水平溢出 */
.app-container { display: flex; height: 100%; width: 100%; background-color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }

/* 侧边栏及历史记录样式保持不变 */
.sidebar { width: 260px; background-color: #f8fafc; border-right: 1px solid #e2e8f0; display: flex; flex-direction: column; flex-shrink: 0; }
.sidebar-header { padding: 16px 20px; height: 60px; box-sizing: border-box; display: flex; align-items: center; }
.logo-area { display: flex; align-items: center; gap: 10px; }
.logo-area .icon { font-size: 24px; }
.logo-area h1 { margin: 0; font-size: 16px; color: #0f172a; font-weight: 600; }
.sidebar-actions { padding: 0 12px 16px 12px; }
.new-chat-btn { width: 100%; display: flex; align-items: center; justify-content: center; gap: 8px; padding: 10px 16px; background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.2s; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
.new-chat-btn svg { width: 16px; height: 16px; }
.new-chat-btn:hover:not(:disabled) { border-color: #94a3b8; background-color: #f1f5f9; }
.new-chat-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.history-list { flex: 1; overflow-y: auto; padding: 0 12px; }
.history-label { font-size: 12px; color: #94a3b8; font-weight: 600; margin: 8px 8px 12px 8px; }
.history-item { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; margin-bottom: 4px; border-radius: 8px; cursor: pointer; color: #475569; transition: background-color 0.2s; }
.history-item:hover { background-color: #e2e8f0; }
.history-item.active { background-color: #e2e8f0; color: #0f172a; font-weight: 500; }
.chat-title { display: flex; align-items: center; gap: 8px; overflow: hidden; }
.chat-title span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px;}
.msg-icon { width: 16px; height: 16px; flex-shrink: 0; opacity: 0.7;}
.delete-btn { background: transparent; border: none; color: #94a3b8; cursor: pointer; padding: 4px; border-radius: 4px; display: flex; align-items: center; justify-content: center; opacity: 0; transition: all 0.2s; }
.delete-btn svg { width: 14px; height: 14px; }
.history-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover { background-color: #cbd5e1; color: #ef4444; }
.empty-history { text-align: center; font-size: 13px; color: #94a3b8; margin-top: 20px; }

/* 右侧主工作区及 Header */
.main-workspace { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.workspace-header { height: 60px; padding: 0 24px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; }
.thread-badge { font-size: 12px; background: #f1f5f9; color: #64748b; padding: 4px 10px; border-radius: 12px; font-family: monospace; }
.header-right-zone { display: flex; align-items: center; gap: 24px; }
.export-group { display: flex; gap: 8px; }
.action-btn { background: #ffffff; border: 1px solid #cbd5e1; padding: 6px 12px; border-radius: 6px; font-size: 13px; color: #334155; cursor: pointer; font-weight: 500; transition: all 0.2s; }
.action-btn:hover { background: #f8fafc; border-color: #94a3b8; color: #0f172a; }
.status-indicator { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #64748b; }
.dot { width: 8px; height: 8px; border-radius: 50%; background-color: #cbd5e1; }
.dot.is-online { background-color: #10b981; box-shadow: 0 0 8px rgba(16, 185, 129, 0.4); }

/* 聊天流容器 */
.chat-main { flex: 1; overflow-y: auto; padding: 20px 0; scroll-behavior: smooth; }
.chat-content { max-width: 850px; margin: 0 auto; display: flex; flex-direction: column; gap: 30px; padding: 0 20px; }

/* 🌟 恢复原有的一左一右气泡布局 */
.message-row { display: flex; gap: 16px; width: 100%; }
.message-row.user { flex-direction: row-reverse; } /* 保持 User 靠右 */
.avatar { width: 36px; height: 36px; border-radius: 8px; background: #f8fafc; display: flex; align-items: center; justify-content: center; font-size: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); flex-shrink: 0; border: 1px solid #e2e8f0; }
.user .avatar { background: #3b82f6; border: none; }
.message-content { flex: 1; max-width: calc(100% - 52px); display: flex; flex-direction: column; }
.user .message-content { align-items: flex-end; }
.message-sender { font-size: 13px; color: #64748b; margin-bottom: 6px; font-weight: 500; }
.text-body { background: #3b82f6; color: white; padding: 12px 18px; border-radius: 12px 2px 12px 12px; font-size: 15px; line-height: 1.5; white-space: pre-wrap; text-align: left; }

/* 🌟 核心修复 2：恢复卡片样式并强制左对齐 */
.markdown-body { 
  background: #ffffff; /* 保留白色卡片底 */
  padding: 16px 20px;  /* 保留边距 */
  border-radius: 2px 12px 12px 12px; /* 保留圆角 */
  border: 1px solid #e2e8f0; /* 保留边框 */
  box-shadow: 0 1px 3px rgba(0,0,0,0.05); /* 保留阴影 */
  font-size: 15px; 
  line-height: 1.6; 
  color: #334155; 
  width: 100%; 
  box-sizing: border-box; 
  text-align: left !important; /* 强制绝对左对齐，不受任何外部干扰 */
}

.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) { margin-top: 0; margin-bottom: 12px; font-weight: 600; color: #0f172a; text-align: left; }
.markdown-body :deep(p) { margin: 0 0 12px 0; text-align: left; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(pre) { margin: 12px 0; padding: 16px; background-color: #0d1117 !important; border-radius: 8px; overflow-x: auto; text-align: left; }
.markdown-body :deep(pre code) { background: transparent; padding: 0; color: #e6edf3; font-size: 13.5px; font-family: ui-monospace, SFMono-Regular, monospace; }
.markdown-body :deep(code) { background-color: #f1f5f9; color: #ef4444; padding: 2px 6px; border-radius: 4px; font-size: 13.5px; font-family: monospace; }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; text-align: left; }
.markdown-body :deep(th), .markdown-body :deep(td) { border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }
.markdown-body :deep(th) { background-color: #f8fafc; font-weight: 600; }
.markdown-body :deep(tr:nth-child(even)) { background-color: #fcfcfc; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { margin: 0 0 12px 0; padding-left: 24px; text-align: left; }
.markdown-body :deep(li) { margin-bottom: 4px; }

/* 底部输入区 */
.app-footer { background: #ffffff; padding: 20px; display: flex; flex-direction: column; align-items: center; }
.input-container { max-width: 850px; width: 100%; position: relative; display: flex; align-items: flex-end; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 16px; padding: 4px; transition: border-color 0.2s, box-shadow 0.2s; }
.input-container:focus-within { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1); background: #ffffff; }
textarea { flex: 1; min-height: 24px; max-height: 200px; padding: 12px 16px; background: transparent; border: none; resize: none; font-size: 15px; line-height: 1.5; color: #0f172a; outline: none; }
.send-btn { width: 40px; height: 40px; margin: 4px; border-radius: 12px; background: #3b82f6; color: white; border: none; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s; flex-shrink: 0; }
.send-btn svg { width: 20px; height: 20px; }
.send-btn:hover:not(:disabled) { background: #2563eb; transform: translateY(-1px); }
.send-btn:disabled { background: #cbd5e1; cursor: not-allowed; color: #94a3b8; }
.footer-tip { margin-top: 12px; font-size: 12px; color: #94a3b8; }
.typing-indicator { display: inline-flex; background: #ffffff; padding: 14px 18px; border-radius: 2px 12px 12px 12px; border: 1px solid #e2e8f0; }
.typing-indicator span { width: 6px; height: 6px; background: #94a3b8; border-radius: 50%; margin: 0 3px; animation: bounce 1.4s infinite ease-in-out both; }
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce { 0%, 80%, 100% { transform: scale(0); } 40% { transform: scale(1); } }

/* --- 右侧栏 --- */
.right-sidebar { width: 260px; background-color: #fafafa; border-left: 1px solid #e2e8f0; display: flex; flex-direction: column; overflow-y: auto; flex-shrink: 0; padding: 20px 0; }
.config-section { padding: 0 20px; margin-bottom: 24px; }
.section-title { font-size: 13px; color: #64748b; font-weight: 600; margin-top: 0; margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.5px; }
.divider { height: 1px; background-color: #e2e8f0; margin: 0 20px 24px 20px; }

/* 🌟 预设问题区更新 */
.preset-list { display: flex; flex-direction: column; gap: 10px; }
.preset-item-wrapper { position: relative; display: flex; align-items: stretch; }
.preset-btn { flex: 1; text-align: left; background: #ffffff; border: 1px solid #e2e8f0; padding: 10px 32px 10px 12px; border-radius: 8px; font-size: 13px; color: #334155; cursor: pointer; transition: all 0.2s; line-height: 1.4; box-shadow: 0 1px 2px rgba(0,0,0,0.02); }
.preset-btn:hover:not(:disabled) { border-color: #3b82f6; color: #3b82f6; box-shadow: 0 2px 4px rgba(59, 130, 246, 0.1); transform: translateY(-1px); }
.preset-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.del-preset-btn { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: transparent; border: none; color: #94a3b8; font-size: 16px; cursor: pointer; opacity: 0; transition: opacity 0.2s; }
.preset-item-wrapper:hover .del-preset-btn { opacity: 1; }
.del-preset-btn:hover { color: #ef4444; font-weight: bold; }

/* 用户设置区 */
.user-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.user-radio { display: flex; align-items: center; gap: 10px; font-size: 14px; color: #334155; cursor: pointer; padding: 8px 12px; border-radius: 6px; transition: background 0.2s; position: relative; }
.user-radio:hover { background: #f1f5f9; }
.user-radio.active { background: #eff6ff; color: #1d4ed8; font-weight: 500; }
.user-radio input { display: none; }
.radio-custom { width: 14px; height: 14px; border: 2px solid #cbd5e1; border-radius: 50%; position: relative; }
.user-radio.active .radio-custom { border-color: #3b82f6; }
.user-radio.active .radio-custom::after { content: ''; position: absolute; width: 8px; height: 8px; background: #3b82f6; border-radius: 50%; top: 50%; left: 50%; transform: translate(-50%, -50%); }

.del-user { position: absolute; right: 12px; font-size: 16px; color: #94a3b8; opacity: 0; transition: opacity 0.2s; }
.user-radio:hover .del-user { opacity: 1; }
.del-user:hover { color: #ef4444; font-weight: bold; }

.add-user-area { display: flex; gap: 8px; }
.add-user-area input { flex: 1; min-width: 0; padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 13px; outline: none; }
.add-user-area input:focus { border-color: #3b82f6; }
.add-user-area button { width: 32px; background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; color: #475569; cursor: pointer; transition: all 0.2s; }
.add-user-area button:hover { background: #e2e8f0; color: #0f172a; }
</style>