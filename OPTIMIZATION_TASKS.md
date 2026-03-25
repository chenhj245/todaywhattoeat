# OPTIMIZATION_TASKS.md — KitchenMind 优化任务清单

> 本文件供 Claude Code 在 CLI 中逐项审查和修改代码使用。
> 每个任务标注了需要改的文件、改动目标和验收标准。

---

## 任务 1：推荐时过滤调味品（最高优先）

### 问题
推荐菜品时，调味品（盐、油、酱油、糖等）被计入匹配分母和缺失清单。
导致匹配度虚低（0%），缺失清单里出现"还缺：盐"这种无意义信息。

### 涉及文件
- `backend/tools.py` — `suggest_meals` 函数
- `backend/ingredient_classifier.py` — 需要用到 `classify_ingredient`

### 改动要求
1. 在 `suggest_meals` 的匹配度计算中，从菜谱食材列表里过滤掉分类为"调味品"的食材
2. 缺失清单（`missing_ingredients`）也要排除调味品
3. 匹配度分母只算非调味品食材

### 示例
番茄炒蛋的食材：西红柿、鸡蛋、食用油、盐、糖、葱花
- 改动前：6 种食材全部参与计算，有西红柿和鸡蛋 → 匹配度 33%
- 改动后：只算西红柿、鸡蛋、葱花（非调味品），有 2/3 → 匹配度 67%
- 缺失清单只显示"葱花（可选）"，不显示"盐""油""糖"

### 验收标准
- 库存里有鸡蛋和西红柿时，番茄炒蛋的匹配度应该 >= 60%
- 缺失清单里不出现"盐""油""酱油""糖""醋"等调味品
- 现有测试不被破坏

---

## 任务 2：最低匹配度阈值 + 容错推荐

### 问题
推荐结果全是 0% 匹配度的菜，等于告诉用户"你什么都做不了"。

### 涉及文件
- `backend/tools.py` — `suggest_meals` 函数

### 改动要求
1. 只返回匹配度 >= 20% 的菜品（阈值可配置，放到 `config.py`）
2. 如果没有任何菜超过阈值，改变回复策略：
   - 从菜谱库里选几道"只差 1-2 样关键食材"的菜
   - 回复消息改为建议采购方向，例如："家里食材不太够，如果买点XX就能做YY了"
3. 排序优先级：匹配度高的在前，相同匹配度下缺失食材少的在前

### 验收标准
- 不再返回匹配度 0% 的推荐
- 库存为空时，推荐消息是建议性的（"买点XX就能做YY"），不是"匹配度 0%"
- `config.py` 里新增 `MIN_MATCH_RATE = 0.2` 配置项

---

## 任务 3：避免重复推荐

### 问题
用户说"这三个我都不想吃"，系统返回一模一样的三道菜。

### 涉及文件
- `backend/agent.py` — 需要维护最近推荐记录
- `backend/tools.py` — `suggest_meals` 函数需要接受排除列表

### 改动要求
1. 在 `agent.py` 模块级别维护一个 `recent_suggestions: list[str]`（最近推荐过的菜名）
2. 每次 `suggest_meals` 返回结果后，把推荐的菜名追加到这个列表
3. 下次调用 `suggest_meals` 时，自动传入排除列表
4. 列表最多保留最近 20 条，超过就丢弃最早的
5. `suggest_meals` 函数新增 `exclude_recipes: list[str] = None` 参数

### 实现逻辑
```python
# agent.py 模块级别
recent_suggestions: list[str] = []

# suggest 硬路由分支里
result = await tools.suggest_meals(
    constraints=user_message,
    exclude_recipes=recent_suggestions[-20:],
    max_results=3
)

# 推荐完成后
if result.get("suggestions"):
    for s in result["suggestions"]:
        recent_suggestions.append(s["name"])
```

```python
# tools.py suggest_meals 函数
async def suggest_meals(
    constraints=None, max_results=3,
    exclude_recipes=None  # 新增参数
):
    ...
    # 在评分排序之后、取 top N 之前
    if exclude_recipes:
        scored_recipes = [
            s for s in scored_recipes
            if s["recipe"]["name"] not in exclude_recipes
        ]
```

### 验收标准
- 连续两次请求推荐，第二次不返回第一次出现过的菜
- `suggest_meals` 函数签名包含 `exclude_recipes` 参数

---

## 任务 4：匹配度数字对用户不可见

### 问题
回复里直接展示"匹配度 0.0%"，像系统报告而不是朋友聊天。

### 涉及文件
- `backend/agent.py` — suggest 硬路由分支里的回复生成逻辑

### 改动要求
1. 推荐回复里不再显示具体匹配度百分比
2. 改用自然语言描述：
   - 匹配度 >= 80%："家里食材齐了，直接能做"
   - 匹配度 50%-80%："大部分食材都有，只差X"
   - 匹配度 20%-50%："还差几样，需要买X和Y"
3. 回复语气保持口语化、像朋友推荐
4. 匹配度数字保留在 API JSON 响应里（前端可用），但不出现在自然语言回复文本中

### 回复示例
改动前：
> 清炒花菜（匹配度 0.0%），还缺：花菜、大蒜、盐

改动后：
> 清炒花菜 —— 还差花菜和大蒜，买回来就能做

### 验收标准
- 自然语言回复里不包含"匹配度"或百分比数字
- API 的 JSON 响应里 `match_rate` 字段保留
- 回复读起来像口语，不像报表

---

## 任务 5：consume_items 扣减逻辑修复

### 问题
消耗食材时直接 `remove_item()`（软删除整条记录）。
用户说"做了番茄炒蛋"，鸡蛋整条记录被删，但实际可能还剩 7 个。

### 涉及文件
- `backend/tools.py` — `consume_items` 函数
- `backend/database.py` — 需要新增 `update_item_quantity` 函数

### 改动要求
1. `database.py` 新增 `update_item_quantity(item_id, new_quantity_desc, new_quantity_num=None)` 函数
2. `consume_items` 的逻辑改为：
   - 如果有 `quantity_num`：减去消耗量，减到 0 以下才 `remove_item`
   - 如果只有 `quantity_desc`：按等级降级
     - "充足" → "一些"
     - "一些" → "快没了"
     - "快没了" → `remove_item`（标记不活跃）
3. action_log 的 payload 里保存修改前的完整状态快照（用于撤销恢复）
4. 撤销逻辑也要更新：从快照恢复原始 quantity_desc / quantity_num

### 验收标准
- 用户说"做了番茄炒蛋"后，鸡蛋记录仍然存在（降级而非删除）
- 连续做三次菜后，quantity_desc 从"充足"→"一些"→"快没了"→消失
- 撤销后恢复到修改前的状态

---

## 任务 6：add_items 去重合并

### 问题
每次"买了鸡蛋"都 INSERT 新记录，导致库存里出现多条同名食材。

### 涉及文件
- `backend/tools.py` — `add_items` 函数
- `backend/ingredient_classifier.py` — 用 `find_similar_ingredients` 查重

### 改动要求
1. `add_items` 添加前先查库存：用 `find_similar_ingredients` 检查是否已有同名/同义词食材
2. 如果已有活跃的同名食材：
   - 更新 `last_mentioned_at` 为当前时间
   - 重置 `confidence` 为 1.0
   - 如果用户说了新的数量（如"买了两盒"），更新 `quantity_desc` 和 `quantity_num`
   - 不插入新记录
3. 如果没有同名食材：正常 INSERT
4. 回复里区分"已更新"和"新添加"

### 验收标准
- 连续说两次"买了鸡蛋"，库存里只有一条鸡蛋记录
- 第二次说"买了鸡蛋"后，置信度重置为 1.0、last_mentioned_at 更新
- 说"买了3盒牛奶"时，如果已有"牛奶"记录，更新数量而非新增

---

## 任务 7：简化厨房概览页

### 问题
页面展示了置信度百分比、进度条、来源标签，太像"库存管理系统"。

### 涉及文件
- `frontend/kitchen.js` — `renderItems` 函数
- `frontend/styles.css` — 相关样式

### 改动要求
1. 移除置信度百分比数字和进度条组件
2. 移除 source 来源标签
3. 每项食材只显示：
   - 食材名
   - 模糊数量（充足/一些/快没了）
   - 相对时间（"今天""昨天""3天前"）
4. 用卡片左边框颜色隐性表达置信度等级（绿/黄/红），保留现有的 `.item-card.high/.medium/.low` 样式
5. 保持三个分组（确定有的/可能有的/不确定了）

### 验收标准
- 页面上看不到任何百分比数字
- 页面上看不到"手动添加""对话中提及"等来源标签
- 食材卡片简洁：名称 + 数量 + 时间
- 三色分组仍然正常工作

---

## 执行顺序

按数字顺序执行，每完成一个任务后运行测试确保不破坏现有功能：

```bash
# 每个任务改完后
cd /path/to/kitchenmind
./venv/bin/python -m pytest tests/ -v
```

任务 1-4 是体验优化，改动较小，风险低。
任务 5-6 是数据逻辑修改，需要同步更新撤销逻辑和测试。
任务 7 是纯前端改动，独立于后端。
