/**
 * 购物清单 JavaScript
 */

const API_BASE = 'http://127.0.0.1:8888';

// 全局状态
let plannedMeals = [];
let suggestions = [];

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
    loadShoppingList();

    // Enter 键添加菜品
    const mealInput = document.getElementById('mealInput');
    mealInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            addPlannedMeal();
        }
    });
});

/**
 * 加载购物清单
 */
async function loadShoppingList() {
    showLoading(true);

    try {
        const mealsParam = plannedMeals.join(',');
        const url = mealsParam
            ? `${API_BASE}/api/shopping?meals=${encodeURIComponent(mealsParam)}`
            : `${API_BASE}/api/shopping`;

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (data.success) {
            renderShoppingList(data.shopping_list);
        } else {
            showError('获取购物清单失败');
        }

    } catch (error) {
        console.error('Load shopping list error:', error);
        showError(`加载失败: ${error.message}`);
    } finally {
        showLoading(false);
    }
}

/**
 * 加载菜品推荐
 */
async function loadSuggestions() {
    const section = document.getElementById('suggestionsSection');
    const list = document.getElementById('suggestionsList');

    section.style.display = 'block';
    list.innerHTML = '<div class="loading-state"><div class="spinner"></div></div>';

    try {
        const response = await fetch(`${API_BASE}/api/suggest?max_results=10`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (data.success) {
            suggestions = data.suggestions;
            renderSuggestions(suggestions);
        } else {
            list.innerHTML = '<div class="empty-state">暂无推荐</div>';
        }

    } catch (error) {
        console.error('Load suggestions error:', error);
        list.innerHTML = `<div class="error-message">加载失败: ${error.message}</div>`;
    }
}

/**
 * 渲染菜品推荐
 */
function renderSuggestions(suggestions) {
    const list = document.getElementById('suggestionsList');

    if (suggestions.length === 0) {
        list.innerHTML = '<div class="empty-state">暂无推荐菜品</div>';
        return;
    }

    list.innerHTML = suggestions.map((item, index) => {
        const matchRate = item.match_rate.toFixed(0);  // 后端已经是百分比，不要再乘100
        const missingCount = item.missing_ingredients.length;

        return `
            <div class="suggestion-card">
                <div class="suggestion-header">
                    <div class="suggestion-name">${item.name}</div>
                    <button class="add-suggestion-btn" onclick="addPlannedMealFromSuggestion('${item.name}')">
                        +
                    </button>
                </div>
                <div class="suggestion-body">
                    <div class="match-rate">
                        <span class="match-label">匹配度</span>
                        <div class="match-bar">
                            <div class="match-fill" style="width: ${matchRate}%"></div>
                        </div>
                        <span class="match-text">${matchRate}%</span>
                    </div>
                    ${missingCount > 0 ? `
                        <div class="missing-ingredients">
                            <span class="missing-label">还需采购:</span>
                            <span class="missing-list">${item.missing_ingredients.slice(0, 3).join('、')}${missingCount > 3 ? '...' : ''}</span>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');
}

/**
 * 关闭推荐区
 */
function closeSuggestions() {
    const section = document.getElementById('suggestionsSection');
    section.style.display = 'none';
}

/**
 * 添加计划菜品
 */
function addPlannedMeal() {
    const input = document.getElementById('mealInput');
    const mealName = input.value.trim();

    if (!mealName) return;

    if (plannedMeals.includes(mealName)) {
        showError('该菜品已在计划中');
        return;
    }

    plannedMeals.push(mealName);
    input.value = '';

    renderPlannedMeals();
    loadShoppingList();
}

/**
 * 从推荐中添加菜品
 */
function addPlannedMealFromSuggestion(mealName) {
    if (plannedMeals.includes(mealName)) {
        showError('该菜品已在计划中');
        return;
    }

    plannedMeals.push(mealName);
    renderPlannedMeals();
    loadShoppingList();
}

/**
 * 移除计划菜品
 */
function removePlannedMeal(mealName) {
    plannedMeals = plannedMeals.filter(m => m !== mealName);
    renderPlannedMeals();
    loadShoppingList();
}

/**
 * 渲染计划菜品
 */
function renderPlannedMeals() {
    const container = document.getElementById('plannedMealTags');

    if (plannedMeals.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无计划菜品</div>';
        return;
    }

    container.innerHTML = plannedMeals.map(meal => `
        <div class="meal-tag">
            <span>${meal}</span>
            <button class="remove-meal-btn" onclick="removePlannedMeal('${meal}')">×</button>
        </div>
    `).join('');
}

/**
 * 渲染购物清单
 */
function renderShoppingList(items) {
    const container = document.getElementById('shoppingItems');

    if (items.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无需要采购的食材</div>';
        return;
    }

    container.innerHTML = items.map(item => `
        <div class="shopping-item">
            <div class="item-checkbox">
                <input type="checkbox" id="item-${item.name}" />
            </div>
            <label for="item-${item.name}" class="item-label">
                <span class="item-name">${item.name}</span>
                ${item.amount ? `<span class="item-amount">${item.amount}</span>` : ''}
                ${item.for_recipes && item.for_recipes.length > 0 ? `
                    <span class="item-recipes">${item.for_recipes.join('、')}</span>
                ` : ''}
            </label>
        </div>
    `).join('');
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
    const container = document.querySelector('.shopping-container');
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.textContent = message;
    container.insertBefore(errorDiv, container.firstChild);

    setTimeout(() => {
        errorDiv.remove();
    }, 3000);
}
