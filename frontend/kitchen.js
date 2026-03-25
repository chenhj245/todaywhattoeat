/**
 * 厨房概览 JavaScript
 */

const API_BASE = 'http://127.0.0.1:8888';

// 页面加载时自动获取状态
document.addEventListener('DOMContentLoaded', () => {
    loadKitchenState();
});

/**
 * 加载厨房状态
 */
async function loadKitchenState() {
    showLoading(true);

    try {
        const response = await fetch(`${API_BASE}/api/kitchen/state`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (data.success) {
            renderKitchenState(data);
        } else {
            showError('获取厨房状态失败');
        }

    } catch (error) {
        console.error('Load kitchen state error:', error);
        showError(`加载失败: ${error.message}`);
    } finally {
        showLoading(false);
    }
}

/**
 * 渲染厨房状态
 */
function renderKitchenState(data) {
    // 更新顶部摘要
    document.getElementById('totalItems').textContent = data.total_items;
    document.getElementById('highItems').textContent = data.high_confidence.length;
    document.getElementById('mediumItems').textContent = data.medium_confidence.length;
    document.getElementById('lowItems').textContent = data.low_confidence.length;

    // 渲染各个置信度区域
    renderItems('highConfidenceItems', 'highCount', data.high_confidence, 'high');
    renderItems('mediumConfidenceItems', 'mediumCount', data.medium_confidence, 'medium');
    renderItems('lowConfidenceItems', 'lowCount', data.low_confidence, 'low');
}

/**
 * 渲染食材列表（简化版，移除调试信息）
 */
function renderItems(containerId, countId, items, confidenceLevel) {
    const container = document.getElementById(containerId);
    const countEl = document.getElementById(countId);

    countEl.textContent = items.length;

    if (items.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无食材</div>';
        return;
    }

    container.innerHTML = items.map(item => {
        const confidence = (item.effective_confidence * 100).toFixed(0);

        // 根据置信度决定卡片样式（通过左边框颜色隐性表达）
        let confidenceClass = 'high';
        if (confidence < 30) {
            confidenceClass = 'low';
        } else if (confidence < 70) {
            confidenceClass = 'medium';
        }

        return `
            <div class="item-card ${confidenceClass}">
                <div class="item-header">
                    <span class="item-name">${item.name}</span>
                    <span class="item-category">${item.category}</span>
                </div>
                <div class="item-body">
                    <div class="item-quantity">${item.quantity_desc}</div>
                    <span class="item-time">${formatTime(item.last_mentioned_at)}</span>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * 格式化时间
 */
function formatTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
        if (diffHours === 0) {
            const diffMinutes = Math.floor(diffMs / (1000 * 60));
            return diffMinutes <= 1 ? '刚刚' : `${diffMinutes} 分钟前`;
        }
        return `${diffHours} 小时前`;
    } else if (diffDays === 1) {
        return '昨天';
    } else if (diffDays < 7) {
        return `${diffDays} 天前`;
    } else {
        return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' });
    }
}

/**
 * 显示加载状态
 */
function showLoading(show) {
    const loadingState = document.getElementById('loadingState');
    if (show) {
        loadingState.style.display = 'flex';
    } else {
        loadingState.style.display = 'none';
    }
}

/**
 * 显示错误
 */
function showError(message) {
    const container = document.querySelector('.kitchen-container');
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.textContent = message;
    container.insertBefore(errorDiv, container.firstChild);

    setTimeout(() => {
        errorDiv.remove();
    }, 5000);
}
