# 第二周代码审核报告

生成时间: 2024-03-23
审核对象: Week 2 Agent 核心代码
审核人: Claude Code

---

## 审核结论

**第二周状态**: 主体代码已落地，但**还不够到已充分验证的程度**

- ✅ 所有模块文件存在且通过语法检查
- ❌ 存在 4 处中高严重度问题
- ❌ 缺少端到端自动化测试
- ❌ 文档与实现存在不一致

**建议**: 可以继续第三周，但需先完成以下两项前置工作（见"修复建议"章节）

---

## 问题清单（按严重度排序）

### 1. 【高严重度】undo_last_action 对 consume 操作未实现反向恢复

**问题描述**:
- `undo_last_action()` 对 `consume` 操作并没有执行反向恢复
- 代码中明确写了"暂时不实现完整逻辑"，只是把 action_log 标记为已撤销
- 但文档（WEEK2_SUMMARY.md）声称"执行反向操作"，并展示了完整撤销效果

**定位到具体行号**:

**backend/tools.py:375-378**:
```python
elif action_type == "consume":
    # 撤销消耗比较复杂，暂时不实现完整逻辑
    # 简化处理：标记为已撤销即可
    pass
```

**backend/tools.py:383-387**（返回消息）:
```python
return {
    "success": True,
    "action_type": action_type,
    "message": f"已撤销{action_type}操作"  # 误导性消息
}
```

**WEEK2_SUMMARY.md:68-71**（文档声称）:
```markdown
6. **undo_last_action** - 撤销操作
   - 查找最后一次操作
   - 执行反向操作  # ← 实际并未执行
   - 标记为已撤销
```

**WEEK2_SUMMARY.md:225-227**（使用示例）:
```
你: 撤销
KitchenMind: 已撤销 consume 操作  # ← 实际库存未恢复
```

**影响**:
- 用户以为库存恢复了，实际上没有恢复
- 会导致库存数据与用户预期严重不符
- 影响后续推荐的准确性

**严重度理由**:
这是核心业务逻辑缺失，直接影响用户体验和数据一致性。

---

### 2. 【中严重度】add_items 未实现文档声称的"自动分类"

**问题描述**:
- 代码只是把未提供分类的食材统一写成 `"其他"`
- 并没有任何自动推断分类的逻辑（如通过 LLM 或规则库）
- 但文档把"自动分类"列为已完成能力

**定位到具体行号**:

**backend/tools.py:45-53**（实际实现）:
```python
item_id = await db.add_kitchen_item(
    name=name,
    category=item.get("category", "其他"),  # ← 直接取 "其他"，无推断
    quantity_desc=item.get("quantity_desc", "一些"),
    quantity_num=item.get("quantity_num"),
    unit=item.get("unit"),
    confidence=1.0,
    source="user_input"
)
```

**WEEK2_SUMMARY.md:43-46**（文档声称）:
```markdown
1. **add_items** - 添加食材
   - 支持模糊数量和精确数量
   - 自动分类  # ← 实际并未自动分类
   - 记录操作日志
```

**影响**:
- 所有未显式指定分类的食材都会被标记为 `"其他"`
- 这些食材将使用默认衰减率（0.10），而不是正确的类别衰减率
- 例如：蔬菜应该用 0.15（约 5 天归零），但会被当成 0.10（约 7 天）
- 会影响置信度衰减的准确性，进而影响推荐质量

**严重度理由**:
影响置信度衰减模型的准确性，但不会导致系统崩溃，属于功能缺失。

---

### 3. 【中严重度】consume_items 实现能力弱于文档描述

**问题描述**:
- 实现是按食材名**精确匹配**并直接软删除**一条**库存记录
- 没有数量扣减、没有模糊匹配、没有同义食材映射
- 文档写"支持按菜谱扣减""自动查找库存匹配"，描述比实际实现更强

**定位到具体行号**:

**backend/tools.py:94-128**（实际实现）:
```python
# 如果指定了菜谱，从数据库查找并扣减
if recipe_name:
    recipe = await db.get_recipe_by_name(recipe_name)
    if recipe:
        # 遍历菜谱中的食材，标记为消耗
        for ingredient in recipe.get("ingredients", []):
            ing_name = ingredient.get("name")
            if ing_name:
                # 查找厨房中是否有这个食材
                kitchen_items = await db.get_active_items()
                for kit_item in kitchen_items:
                    if kit_item["name"] == ing_name:  # ← 精确匹配
                        # 标记为不活跃（消耗掉）
                        await db.remove_item(kit_item["id"])  # ← 直接删除整条
                        consumed.append({
                            "name": ing_name,
                            "amount": ingredient.get("amount", "")
                        })
                        break  # ← 只匹配第一条，不处理多条
```

**WEEK2_SUMMARY.md:48-51**（文档声称）:
```markdown
2. **consume_items** - 消耗食材
   - 支持按菜谱扣减  # ← 实际是删除整条记录，不是扣减数量
   - 支持手动指定食材
   - 自动查找库存匹配  # ← 实际是精确名称匹配，无模糊匹配
```

**实际能力限制**:
1. **无数量扣减**: 做菜消耗 100g 鸡蛋，会把整条"鸡蛋 500g"记录删掉
2. **无模糊匹配**: 菜谱写"番茄"，库存是"西红柿"，匹配不上
3. **无同义词**: "土豆" vs "马铃薯"无法匹配
4. **只匹配第一条**: 如果有多条相同食材记录，只会消耗第一条

**影响**:
- 用户买了 500g 鸡蛋，做了一次菜就"没了"，但实际应该还剩
- 同义词食材匹配失败会导致推荐不准
- 不符合"模糊库存管理"的设计目标

**严重度理由**:
影响核心功能准确性，但系统仍可运行，属于功能不完善。

---

### 4. 【中严重度】第二周核心链路缺少可复现的自动化验证

**问题描述**:
- 仓库只有解析器测试 `tests/test_parse_recipes.py`
- 没有针对 `backend/` 或 `cli_test.py` 的测试
- 当前只能证明"代码存在且能过语法检查"，不能证明"Agent 真的跑通"
- 文档自己也承认 Ollama Tool Calling "需要实际测试验证格式兼容性"

**定位到具体位置**:

**文件系统**:
```bash
tests/
└── test_parse_recipes.py  # 只有这一个测试文件
```

缺失的测试：
- `tests/test_tools.py` - 6 个工具函数的单元测试
- `tests/test_agent.py` - Agent 主循环和意图路由测试
- `tests/test_confidence.py` - 置信度衰减测试
- `tests/test_database.py` - 数据库操作测试
- `tests/test_integration.py` - 端到端集成测试

**WEEK2_SUMMARY.md:235-237**（文档承认）:
```markdown
### 当前限制

1. **工具调用格式**
   - Ollama 的 Tool Calling 支持可能与 OpenAI 有差异
   - 需要实际测试验证格式兼容性  # ← 承认未验证
```

**WEEK2_SUMMARY.md:282-287**（技术债务清单）:
```markdown
## 技术债务

- [ ] 添加工具函数的单元测试  # ← 未完成
- [ ] 完善错误处理和日志
- [ ] 优化 LLM Prompt
- [ ] 实现云端 API 降级方案
- [ ] 菜谱匹配优化（模糊匹配）
```

**影响**:
- 无法保证代码在真实环境中能正常运行
- Ollama Tool Calling 格式不兼容的风险未消除
- 修改代码时容易引入 regression
- 第三周开发可能遇到意外问题

**严重度理由**:
不影响现有代码的正确性，但影响可维护性和可信度。

---

## 其他观察（非严重问题）

### 1. 语法检查已通过

所有 Python 文件能通过 `python3 -m py_compile` 检查，不是空壳代码。

### 2. 依赖项已安装

requirements.txt 中的依赖已通过阿里云镜像安装成功。

### 3. 数据库已初始化

`data/kitchenmind.db` 存在，包含 356 道菜谱，数据完整性 95%。

### 4. 代码结构符合规范

所有模块按 PROJECT_SPEC.md 要求组织，文件结构清晰。

---

## 修复建议

根据您的要求："可以继续第三周，但前提是先补两件事"

### 前置任务 1: 修正文档或补全缺失功能

**方案 A（推荐）: 修正文档**

修改 `WEEK2_SUMMARY.md`，如实反映当前实现状态：

1. **第 68-71 行**: 修改 undo_last_action 描述
   ```markdown
   6. **undo_last_action** - 撤销操作
      - 查找最后一次操作
      - 对 add 操作执行反向删除
      - 对 consume 操作仅标记为已撤销（库存不恢复）
      - **限制**: consume 撤销未完整实现
   ```

2. **第 43-46 行**: 修改 add_items 描述
   ```markdown
   1. **add_items** - 添加食材
      - 支持模糊数量和精确数量
      - 分类通过 LLM 推断（如未提供则默认"其他"）
      - 记录操作日志
      - **限制**: 自动分类依赖 LLM，精度待验证
   ```

3. **第 48-51 行**: 修改 consume_items 描述
   ```markdown
   2. **consume_items** - 消耗食材
      - 按菜谱精确名称匹配食材
      - 删除整条库存记录（不支持数量扣减）
      - 支持手动指定食材列表
      - **限制**: 无模糊匹配、无同义词、无数量扣减
   ```

4. **新增"未完成功能"章节** 在 WEEK2_SUMMARY.md 末尾：
   ```markdown
   ## 未完成功能（技术债务）

   以下功能在设计中提及但未实现：

   1. **consume 操作的完整撤销** (backend/tools.py:375-378)
      - 现状: 只标记 action_log，不恢复库存
      - 原因: 需要记录删除的 item_id，当前 payload 未保存
      - 影响: 用户撤销后库存不恢复

   2. **add_items 的自动分类** (backend/tools.py:47)
      - 现状: 未提供分类时统一为"其他"
      - 原因: 需调用 LLM 或维护食材分类字典
      - 影响: 置信度衰减不准确

   3. **consume_items 的数量扣减** (backend/tools.py:107)
      - 现状: 删除整条记录
      - 原因: 当前库存模型不支持数量递减
      - 影响: 库存消耗过快

   4. **菜谱的模糊匹配** (backend/tools.py:105, 122)
      - 现状: 精确字符串匹配
      - 原因: 需要同义词词典或 embedding 相似度
      - 影响: "番茄" vs "西红柿"匹配失败
   ```

**方案 B（耗时）: 补全功能**

如果要真正实现这些功能：

1. **补全 consume 撤销** (约 1-2 小时):
   - 修改 `consume_items()` 的 payload 记录 `item_id`
   - 修改 `undo_last_action()` 的 consume 分支，调用 `restore_item(item_id)`
   - 在 database.py 中新增 `restore_item()` 方法

2. **实现自动分类** (约 2-3 小时):
   - 构建食材→分类的字典（100+ 常见食材）
   - 或调用 LLM 进行分类推断
   - 修改 `add_items()` 逻辑

3. **实现数量扣减** (约 3-4 小时):
   - 需要重新设计库存模型
   - 当前是"有/没有"二值，需改为支持数量递减
   - 涉及 database.py 和 tools.py 的多处修改

**推荐**: 先选**方案 A**（修正文档），在第三周或第四周视需求决定是否补全。

---

### 前置任务 2: 补充 Week 2 自动化测试

**最小测试集**（约 2-3 小时）:

**1. tests/test_tools_integration.py** - 端到端业务链路测试

```python
"""
集成测试: 验证 add -> query -> consume -> undo 完整链路
"""
import pytest
import asyncio
from backend import tools, database as db

@pytest.mark.asyncio
async def test_full_workflow():
    """测试完整业务流程"""
    # 1. 添加食材
    result = await tools.add_items([
        {"name": "鸡蛋", "quantity_desc": "一些", "category": "蛋奶"},
        {"name": "西红柿", "quantity_desc": "充足", "category": "蔬菜"}
    ])
    assert result["success"]
    assert result["added_count"] == 2

    # 2. 查询库存
    state = await tools.get_kitchen_state()
    assert state["total_items"] == 2
    assert len(state["high_confidence"]) == 2

    # 3. 消耗食材（做菜）
    consume_result = await tools.consume_items(
        reason="做了番茄炒蛋",
        recipe_name="番茄炒蛋"
    )
    assert consume_result["success"]

    # 4. 再次查询（应该减少）
    state_after = await tools.get_kitchen_state()
    assert state_after["total_items"] < state["total_items"]

    # 5. 撤销操作
    undo_result = await tools.undo_last_action()
    assert undo_result["success"]
    assert undo_result["action_type"] == "consume"

    # 注意：当前实现下，撤销后库存不会恢复（已知问题）
    # 这个测试验证的是"撤销功能不报错"，而不是"库存恢复"
```

**2. tests/test_agent_mock.py** - Agent 路由测试（无需真实 Ollama）

```python
"""
Agent 测试: 意图路由和工具调度（Mock LLM）
"""
import pytest
from backend.agent import classify_intent
from unittest.mock import AsyncMock, patch

def test_intent_classification():
    """测试意图分类规则"""
    # 添加意图
    assert classify_intent("买了鸡蛋")[0] == "add"
    assert classify_intent("带了西红柿")[0] == "add"

    # 消耗意图
    assert classify_intent("做了番茄炒蛋")[0] == "consume"
    assert classify_intent("吃了鸡蛋")[0] == "consume"

    # 推荐意图
    assert classify_intent("今晚吃什么")[0] == "suggest"
    assert classify_intent("推荐几道菜")[0] == "suggest"

    # 撤销意图
    assert classify_intent("撤销")[0] == "undo"
    assert classify_intent("刚才搞错了")[0] == "undo"

@pytest.mark.asyncio
@patch('backend.agent.chat_with_tools')
async def test_agent_process_with_mock_llm(mock_chat):
    """测试 Agent 主循环（Mock LLM 响应）"""
    # Mock LLM 返回工具调用
    mock_chat.return_value = {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "add_items",
                    "arguments": '{"items": [{"name": "鸡蛋"}]}'
                }
            }]
        }
    }

    from backend.agent import process_message
    result = await process_message("买了鸡蛋")

    assert "assistant_message" in result
    assert len(result["tool_results"]) > 0
    assert result["intent"] == "add"
```

**3. tests/test_confidence.py** - 置信度衰减单元测试

```python
"""
置信度衰减测试
"""
import pytest
from datetime import datetime, timedelta
from backend.confidence import calculate_current_confidence

def test_vegetable_decay():
    """测试蔬菜衰减（5天归零）"""
    item = {
        "name": "白菜",
        "category": "蔬菜",
        "confidence": 1.0,
        "last_mentioned_at": (datetime.now() - timedelta(days=5)).isoformat()
    }

    current = calculate_current_confidence(item)
    assert current < 0.5  # 5天后应显著降低

def test_seasoning_no_decay():
    """测试调味品几乎不衰减"""
    item = {
        "name": "盐",
        "category": "调味品",
        "confidence": 1.0,
        "last_mentioned_at": (datetime.now() - timedelta(days=30)).isoformat()
    }

    current = calculate_current_confidence(item)
    assert current > 0.7  # 30天后仍高置信度
```

**如何运行测试**:

```bash
# 安装 pytest（如果还没装）
./venv/bin/pip install pytest pytest-asyncio

# 运行所有测试
./venv/bin/pytest tests/ -v

# 只运行集成测试
./venv/bin/pytest tests/test_tools_integration.py -v
```

---

## 总结

### 当前状态

✅ **已完成**:
- 所有模块代码已编写（~1230 行）
- 文件结构符合规范
- 语法检查通过
- 数据库和依赖已就绪

❌ **未完成**:
- consume 操作的完整撤销
- add_items 的自动分类
- consume_items 的数量扣减和模糊匹配
- Week 2 的自动化测试

⚠️ **风险**:
- Ollama Tool Calling 格式未验证
- 文档与实现存在不一致
- 无回归测试保护

### 建议的行动顺序

**优先级 1（必须）**:
1. 修正 WEEK2_SUMMARY.md 文档，如实反映当前状态（30 分钟）
2. 补充最小测试集（2-3 小时）

**优先级 2（可选，在第三周空隙完成）**:
3. 实现 consume 操作的完整撤销（1-2 小时）
4. 用 CLI 手动测试一次完整流程，验证 Ollama Tool Calling（30 分钟）

**优先级 3（技术债务，可推迟）**:
5. 实现自动分类
6. 实现数量扣减
7. 实现模糊匹配

### 是否可以进入第三周？

**答案**: **可以，但需先完成优先级 1 的两项任务**

理由：
- 第三周是前端开发 + 联调，不会修改 backend 核心逻辑
- 当前的问题不会阻塞前端开发
- 修正文档可以避免误导
- 最小测试集可以保护现有代码

---

**审核完成时间**: 2024-03-23
**下一步**: 等待开发者确认修复方案
