/**
 * 聊天界面 JavaScript
 *
 * 支持流式和非流式两种对话模式
 */

const API_BASE = 'http://127.0.0.1:8888';
const CHAT_HISTORY_KEY = 'kitchenmind_chat_history';
let isProcessing = false;
let chatHistory = [];
let lastSubmittedMessage = '';
let lastSubmittedAt = 0;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('userInput');
    loadChatHistory();

    // 自动调整文本框高度
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = input.scrollHeight + 'px';
    });

    // Enter 发送，Shift+Enter 换行
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
});

/**
 * 发送消息（主入口）
 */
async function sendMessage() {
    const input = document.getElementById('userInput');
    const message = input.value.trim();

    if (!message || isProcessing) return;

    const now = Date.now();
    if (message === lastSubmittedMessage && now - lastSubmittedAt < 1500) {
        console.warn('Duplicate message suppressed:', message);
        return;
    }

    lastSubmittedMessage = message;
    lastSubmittedAt = now;

    // 清空输入框
    input.value = '';
    input.style.height = 'auto';

    // 添加用户消息到界面
    addMessage('user', message);

    // 发送请求（使用流式响应）
    await sendStreamingMessage(message);
}

/**
 * 快速消息按钮
 */
function sendQuickMessage(text) {
    if (isProcessing) return;
    const input = document.getElementById('userInput');
    input.value = text;
    sendMessage();
}

/**
 * 流式对话（SSE）
 */
async function sendStreamingMessage(message) {
    isProcessing = true;
    updateSendButton(true);

    // 创建助手消息容器
    const assistantMsgId = addMessage('assistant', '');
    const assistantMsgEl = document.getElementById(assistantMsgId);
    const contentEl = assistantMsgEl.querySelector('.message-content');

    // 添加加载状态
    contentEl.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';

    let fullMessage = '';

    try {
        const response = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: message,
                stream: true
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.slice(6));

                    if (data.type === 'intent') {
                        console.log('Intent:', data.content);
                    } else if (data.type === 'tool') {
                        console.log('Tool:', data.content);
                    } else if (data.type === 'message_chunk') {
                        if (contentEl.querySelector('.typing-indicator')) {
                            contentEl.innerHTML = '';
                        }
                        fullMessage += data.content;
                        contentEl.textContent = fullMessage;
                        updateLastAssistantMessage(fullMessage);
                        scrollToBottom();
                    } else if (data.type === 'done') {
                        console.log('Stream complete');
                    } else if (data.type === 'error') {
                        contentEl.innerHTML = `<span class="error">❌ ${data.content}</span>`;
                        updateLastAssistantMessage(`❌ ${data.content}`);
                    }
                }
            }
        }

        showUndoButton();
    } catch (error) {
        console.error('Stream error:', error);
        contentEl.innerHTML = `<span class="error">❌ 连接失败: ${error.message}</span>`;
        updateLastAssistantMessage(`❌ 连接失败: ${error.message}`);
    } finally {
        isProcessing = false;
        updateSendButton(false);
    }
}

/**
 * 非流式对话（备用）
 */
async function sendNormalMessage(message) {
    isProcessing = true;
    updateSendButton(true);

    const assistantMsgId = addMessage('assistant', '');
    const assistantMsgEl = document.getElementById(assistantMsgId);
    const contentEl = assistantMsgEl.querySelector('.message-content');

    contentEl.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';

    try {
        const response = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: message,
                stream: false
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const result = await response.json();

        const reply = result.assistant_message || '已处理完成';
        contentEl.textContent = reply;
        updateLastAssistantMessage(reply);
        showUndoButton();
    } catch (error) {
        console.error('Request error:', error);
        contentEl.innerHTML = `<span class="error">❌ 请求失败: ${error.message}</span>`;
        updateLastAssistantMessage(`❌ 请求失败: ${error.message}`);
    } finally {
        isProcessing = false;
        updateSendButton(false);
    }
}

/**
 * 撤销上一次操作
 */
async function undoLastAction() {
    if (isProcessing) return;

    try {
        const response = await fetch(`${API_BASE}/api/kitchen/undo`, {
            method: 'POST'
        });

        const result = await response.json();

        if (result.success) {
            addMessage('system', `✅ ${result.message}`);
            hideUndoButton();
        } else {
            addMessage('system', `❌ ${result.message}`);
        }
    } catch (error) {
        console.error('Undo error:', error);
        addMessage('system', `❌ 撤销失败: ${error.message}`);
    }
}

/**
 * 添加消息到界面
 *
 * @param {string} role - 'user', 'assistant', 'system'
 * @param {string} content - 消息内容
 * @returns {string} 消息元素 ID
 */
function addMessage(role, content) {
    const msgId = renderMessage(role, content);
    chatHistory.push({ role, content });
    saveChatHistory();
    scrollToBottom();
    return msgId;
}

function renderMessage(role, content) {
    const messageList = document.getElementById('messageList');
    const msgId = `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    clearWelcomeMessage();

    const messageDiv = document.createElement('div');
    messageDiv.id = msgId;
    messageDiv.className = `message message-${role}`;

    if (role === 'system') {
        messageDiv.innerHTML = `<div class="message-content system">${content}</div>`;
    } else {
        const avatar = role === 'user' ? '👤' : '🤖';
        messageDiv.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-bubble">
                <div class="message-content">${content}</div>
            </div>
        `;
    }

    messageList.appendChild(messageDiv);
    return msgId;
}

function clearWelcomeMessage() {
    const welcome = document.querySelector('.welcome-message');
    if (welcome) {
        welcome.remove();
    }
}

function saveChatHistory() {
    sessionStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(chatHistory));
}

function loadChatHistory() {
    const raw = sessionStorage.getItem(CHAT_HISTORY_KEY);
    if (!raw) return;

    try {
        const storedHistory = JSON.parse(raw);
        if (!Array.isArray(storedHistory) || storedHistory.length === 0) return;

        chatHistory = storedHistory;

        const messageList = document.getElementById('messageList');
        messageList.innerHTML = '';

        for (const message of chatHistory) {
            renderMessage(message.role, message.content);
        }
        scrollToBottom();
    } catch (error) {
        console.error('Load chat history error:', error);
        sessionStorage.removeItem(CHAT_HISTORY_KEY);
        chatHistory = [];
    }
}

function updateLastAssistantMessage(content) {
    for (let i = chatHistory.length - 1; i >= 0; i--) {
        if (chatHistory[i].role === 'assistant') {
            chatHistory[i].content = content;
            saveChatHistory();
            return;
        }
    }
}

/**
 * 滚动到底部
 */
function scrollToBottom() {
    const messageList = document.getElementById('messageList');
    messageList.scrollTop = messageList.scrollHeight;
}

/**
 * 更新发送按钮状态
 */
function updateSendButton(processing) {
    const sendBtn = document.getElementById('sendBtn');
    if (processing) {
        sendBtn.classList.add('processing');
        sendBtn.disabled = true;
    } else {
        sendBtn.classList.remove('processing');
        sendBtn.disabled = false;
    }
}

/**
 * 显示撤销按钮
 */
function showUndoButton() {
    const undoBtn = document.getElementById('undoBtn');
    undoBtn.style.display = 'flex';
}

/**
 * 隐藏撤销按钮
 */
function hideUndoButton() {
    const undoBtn = document.getElementById('undoBtn');
    undoBtn.style.display = 'none';
}
