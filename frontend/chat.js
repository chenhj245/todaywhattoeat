/**
 * 聊天界面 JavaScript
 *
 * 支持流式和非流式两种对话模式
 */

const API_BASE = 'http://127.0.0.1:8888';
let isProcessing = false;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('userInput');

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
                        // 显示意图识别结果（可选）
                        console.log('Intent:', data.content);
                    } else if (data.type === 'tool') {
                        // 显示工具调用结果（可选）
                        console.log('Tool:', data.content);
                        // 可以在界面上显示"正在添加食材..."等提示
                    } else if (data.type === 'message_chunk') {
                        // 移除加载状态
                        if (contentEl.querySelector('.typing-indicator')) {
                            contentEl.innerHTML = '';
                        }
                        // 追加消息片段
                        fullMessage += data.content;
                        contentEl.textContent = fullMessage;
                        scrollToBottom();
                    } else if (data.type === 'done') {
                        // 完成
                        console.log('Stream complete');
                    } else if (data.type === 'error') {
                        // 错误
                        contentEl.innerHTML = `<span class="error">❌ ${data.content}</span>`;
                    }
                }
            }
        }

        // 显示撤销按钮
        showUndoButton();

    } catch (error) {
        console.error('Stream error:', error);
        contentEl.innerHTML = `<span class="error">❌ 连接失败: ${error.message}</span>`;
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

        // 显示助手回复
        const reply = result.assistant_message || '已处理完成';
        contentEl.textContent = reply;

        // 显示撤销按钮
        showUndoButton();

    } catch (error) {
        console.error('Request error:', error);
        contentEl.innerHTML = `<span class="error">❌ 请求失败: ${error.message}</span>`;
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
    const messageList = document.getElementById('messageList');
    const msgId = `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

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
    scrollToBottom();

    return msgId;
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
