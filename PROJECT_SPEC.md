# KitchenMind — 厨房状态代理 项目规范

## 项目定位

KitchenMind 不是冰箱记账软件，而是一个**围绕厨房状态运转的 AI agent**。

核心理念：用户不是来管理冰箱的，是来解决"今晚吃什么"的。

产品的前台只有一件事——用户问"吃什么"，系统给建议。
所有其他能力（库存管理、食材录入、临期提醒、购物清单）都是这个核心体验的后台支撑层。

## 核心设计原则

1. **能自动的自动**：小票识别、菜谱扣减、购物清单生成
2. **高风险的确认**：模型不确定的扣减、低置信度推断
3. **没必要精确的就不要精确**：葱姜蒜、调味料、半颗洋葱

## 当前阶段

MVP — 仅个人使用，验证两个核心假设：

- 假设1：用户是否愿意在买菜、做饭等节点持续跟系统说话
- 假设2：基于模糊库存的推荐质量是否足够好

---

## 技术架构

```
用户（浏览器）
    ↓ HTTP
FastAPI 后端
    ↓
意图路由层（规则 + 关键词初筛）
    ↓
┌──────────────────────────────┐
│  简单意图 → Ollama 小模型     │  "我买了鸡蛋" → 意图识别+参数提取
│  复杂意图 → Ollama 大模型     │  "今晚吃什么" → 综合推理+推荐
│  备用/对照 → Qwen 3.5 API    │  本地不够好时 fallback
└──────────────────────────────┘
    ↓ Tool Calling
Agent 工具层（add_items / consume_items / suggest_meals / ...）
    ↓
┌──────────────────────────────┐
│  SQLite 数据库                │
│  ├── kitchen_items（厨房状态） │
│  ├── recipes（菜谱知识库）     │
│  ├── action_log（操作日志）    │
│  └── preferences（用户偏好）   │
└──────────────────────────────┘
```

### 关键技术选型


| 组件     | 选型                 | 理由                                        |
| -------- | -------------------- | ------------------------------------------- |
| 语言     | Python 3.11+         | 用户最熟悉                                  |
| Web框架  | FastAPI              | 异步、轻量、自带 OpenAPI 文档               |
| 数据库   | SQLite               | 单用户、零配置、备份=复制文件               |
| 本地推理 | Ollama               | 简单部署、OpenAI 兼容 API、多模型管理       |
| 小模型   | qwen3.5:9b           | 意图识别、参数提取，速度快                  |
| 大模型   | qwen3.5:35b (或同级) | 复杂推荐、多约束推理                        |
| 云端备用 | Qwen 3.5 High API    | fallback + 质量对比基准                     |
| 前端     | 纯 HTML/CSS/JS       | MVP 不需要框架，一个聊天界面即可            |
| 菜谱数据 | HowToCook (GitHub)   | Unlicense 开源、结构化、社区维护、200+ 菜谱 |

---

## 数据库设计

### kitchen_items — 厨房食材状态

```sql
CREATE TABLE kitchen_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,               -- 食材名称（标准化后）
    category TEXT,                    -- 蔬菜/肉类/蛋奶/调味品/主食/冷冻/水果
    quantity_desc TEXT DEFAULT '一些', -- 模糊数量：充足/一些/快没了/不确定
    quantity_num REAL,                -- 精确数量（可选，如 3 个鸡蛋）
    unit TEXT,                        -- 单位：个/克/毫升/袋/盒/瓶
    added_at TEXT NOT NULL,           -- ISO 格式入库时间
    last_mentioned_at TEXT NOT NULL,  -- 最后一次被提及的时间
    confidence REAL DEFAULT 1.0,      -- 置信度 0.0-1.0
    source TEXT DEFAULT 'user_input', -- user_input / recipe_deduction / system_guess
    is_active INTEGER DEFAULT 1,      -- 软删除标记
    meta TEXT DEFAULT '{}'            -- JSON 扩展字段
);
```

### recipes — 菜谱知识库

```sql
CREATE TABLE recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT,                    -- 素菜/荤菜/水产/早餐/主食/汤粥/甜品/饮料
    difficulty INTEGER,               -- 1-5 星
    time_minutes INTEGER,             -- 预估烹饪时间
    flavor_tags TEXT DEFAULT '[]',    -- JSON: ["酸甜", "家常", "辣"]
    ingredients TEXT NOT NULL,        -- JSON: [{"name":"西红柿","amount":1,"unit":"个","weight_g":180}, ...]
    steps TEXT DEFAULT '[]',          -- JSON: ["步骤1", "步骤2", ...]
    raw_markdown TEXT,                -- 原始 Markdown 内容（保留以备查）
    source TEXT DEFAULT 'HowToCook'
);
```

### action_log — 操作日志

```sql
CREATE TABLE action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,        -- add / consume / remove / modify / undo
    payload TEXT NOT NULL,            -- JSON: 操作的具体内容
    model_used TEXT,                  -- 执行此操作时用的模型
    user_input TEXT,                  -- 触发此操作的原始用户输入
    created_at TEXT NOT NULL,
    undone INTEGER DEFAULT 0          -- 是否已被撤销
);
```

### preferences — 用户偏好

```sql
CREATE TABLE preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,              -- JSON
    updated_at TEXT NOT NULL
);
```

预设偏好 key：

- `disliked_ingredients` — 不喜欢的食材 `["香菜", "南瓜"]`
- `dietary_goals` — 饮食目标 `{"type": "减脂", "notes": "晚餐偏高蛋白"}`
- `cooking_time_preference` — `{"weekday": 20, "weekend": 60}` (分钟)
- `spice_tolerance` — `"中等"`
- `household_size` — `1`

---

## 置信度衰减模型

```python
from datetime import datetime

DECAY_RATES = {
    "蔬菜": 0.15,     # 每天衰减 15%，~5天后基本归零
    "水果": 0.18,     # 衰减更快
    "肉类": 0.10,     # 冷藏肉 ~7天
    "蛋奶": 0.08,     # 鸡蛋牛奶 ~10天
    "主食": 0.05,     # 米面等
    "调味品": 0.01,   # 几乎不衰减
    "冷冻": 0.02,     # 冷冻食品非常慢
    "其他": 0.10,
}

def calculate_current_confidence(item: dict) -> float:
    """计算食材当前的实际置信度"""
    last_mentioned = datetime.fromisoformat(item["last_mentioned_at"])
    days_elapsed = (datetime.now() - last_mentioned).total_seconds() / 86400
    rate = DECAY_RATES.get(item["category"], 0.10)
    return max(0.0, item["confidence"] * (1 - rate) ** days_elapsed)
```

置信度影响推荐逻辑：

- confidence >= 0.7：直接用于推荐，不需确认
- 0.3 <= confidence < 0.7：推荐时附带"如果你家还有XX的话"
- confidence < 0.3：不参与推荐，标记为"不确定"

---

## Agent 工具定义

### 工具列表

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_items",
            "description": "添加食材到厨房库存。当用户说'买了XXX'、'带了XXX'、'冰箱里有XXX'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "食材名称"},
                                "quantity_desc": {"type": "string", "enum": ["充足", "一些", "少量"], "description": "模糊数量"},
                                "quantity_num": {"type": "number", "description": "精确数量，如果用户提到了的话"},
                                "unit": {"type": "string", "description": "单位"},
                                "category": {"type": "string", "enum": ["蔬菜", "肉类", "蛋奶", "调味品", "主食", "冷冻", "水果", "其他"]}
                            },
                            "required": ["name"]
                        }
                    }
                },
                "required": ["items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consume_items",
            "description": "标记食材被消耗。当用户说'做了XXX菜'、'吃了XXX'、'用掉了XXX'、'坏了扔了'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "消耗原因，如'做了番茄炒蛋'"},
                    "recipe_name": {"type": "string", "description": "如果是做了某道菜，菜名是什么（用于从菜谱库查找配料）"},
                    "items": {
                        "type": "array",
                        "description": "手动指定消耗的食材（如果不是按菜谱消耗）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "amount": {"type": "string", "description": "消耗量描述"}
                            },
                            "required": ["name"]
                        }
                    }
                },
                "required": ["reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_kitchen_state",
            "description": "获取当前厨房所有食材的状态，包含名称、数量、置信度。用于推荐菜品前了解库存。",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_confidence": {"type": "number", "description": "最低置信度过滤，默认0.1"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_meals",
            "description": "根据当前库存、用户偏好和约束条件推荐菜品。",
            "parameters": {
                "type": "object",
                "properties": {
                    "constraints": {"type": "string", "description": "用户的自然语言约束，如'快手菜''不要辣''清淡'"},
                    "max_results": {"type": "integer", "description": "最多推荐几道菜，默认3"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_shopping_list",
            "description": "生成购物清单。可以基于计划做的菜，也可以基于常用食材消耗。",
            "parameters": {
                "type": "object",
                "properties": {
                    "planned_meals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "计划要做的菜名列表"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "undo_last_action",
            "description": "撤销上一次库存操作。当用户说'撤回''撤销''刚才搞错了'时调用。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]
```

---

## 意图路由层

在调用模型之前，先用规则做粗分类（零延迟），然后分发给对应模型。

```python
import re

INTENT_PATTERNS = {
    "add": [
        r"买了", r"带了", r"拿了", r"买回", r"带回",
        r"冰箱里有", r"家里有", r"还有", r"补了", r"囤了"
    ],
    "consume": [
        r"做了", r"炒了", r"煮了", r"蒸了", r"烤了",
        r"吃了", r"吃掉", r"用了", r"用掉", r"扔了", r"坏了"
    ],
    "suggest": [
        r"吃什么", r"做什么", r"推荐", r"建议", r"今[天晚]",
        r"想吃", r"能做", r"有什么菜", r"帮我想"
    ],
    "shopping": [
        r"买什么", r"购物", r"采购", r"清单", r"缺什么", r"要买"
    ],
    "undo": [
        r"撤[回销]", r"取消", r"搞错", r"不对", r"删[掉除]"
    ],
    "query": [
        r"还有(什么|多少|几)", r"库存", r"冰箱里", r"家里(还)?有什么"
    ]
}

def classify_intent(text: str) -> tuple[str, str]:
    """
    返回 (intent, model_tier)
    model_tier: "small" = 8B, "large" = 30B
    """
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                if intent in ("add", "consume", "undo", "query"):
                    return intent, "small"
                else:
                    return intent, "large"
    # 无法识别 → 交给大模型判断
    return "unknown", "large"
```

---

## HowToCook 菜谱解析

### 数据来源

- 仓库：https://github.com/Anduin2017/HowToCook
- 协议：Unlicense（完全自由使用）
- 菜谱位置：`dishes/` 目录下，按分类存放
- 格式：Markdown，结构为 `## 必备原料和工具` → `## 计算` → `## 操作` → `## 附加内容`

### 解析策略

**第一步：规则解析**

- 按 `##` 切分 section
- 提取"必备原料和工具"下的列表项作为 ingredients
- 提取"计算"部分的数量公式（如 `鸡蛋 = 1.5 个 * 份数`）
- 从文件路径提取 category（vegetable_dish → 素菜, meat_dish → 荤菜 ...）
- 从 `预估烹饪难度：★★` 提取 difficulty

**第二步：LLM 补全**
对规则解析不完整的菜谱，用本地 30B 模型做批量结构化提取。

Prompt 模板：

```
你是一个菜谱数据结构化助手。给你一个中文菜谱的 Markdown 原文，请提取以下信息并以 JSON 格式返回：

{
  "name": "菜名",
  "category": "素菜/荤菜/水产/早餐/主食/汤粥/甜品/饮料",
  "difficulty": 1-5,
  "time_minutes": 预估总时间（分钟），
  "flavor_tags": ["标签1", "标签2"],
  "ingredients": [
    {"name": "食材名", "amount_per_serving": 数量, "unit": "单位", "required": true/false}
  ]
}

注意：
- amount_per_serving 是每 1 人份的量
- required=false 表示可选食材
- 如果原文没有明确数量，根据常识估算
- 只返回 JSON，不要其他内容

菜谱原文：
{markdown_content}
```

### 目录映射

```python
CATEGORY_MAP = {
    "vegetable_dish": "素菜",
    "meat_dish": "荤菜",
    "aquatic": "水产",
    "breakfast": "早餐",
    "staple": "主食",
    "soup": "汤粥",
    "dessert": "甜品",
    "drink": "饮料",
    "condiment": "调味品",
    "semi-finished": "半成品",
}
```

---

## Agent System Prompt

以下是给厨房 agent 的核心 system prompt：

```
你是 KitchenMind，一个家庭厨房助手。你的目标是帮用户解决"今晚吃什么"的问题。

## 你的核心能力
- 记住用户家里有什么食材（通过工具管理库存）
- 推荐适合当前库存和用户偏好的菜品
- 在用户买菜、做饭时自动更新库存状态
- 生成购物清单

## 你的行为准则

### 关于库存更新
- 用户说"买了XXX"时，直接调用 add_items，不需要确认
- 用户说"做了XXX菜"时，调用 consume_items 按菜谱扣减，在回复中顺带提一句扣了什么
- 如果不确定用量（比如"做了个面"），给出你的最佳猜测，在回复中说明你的假设
- 永远不要要求用户填写精确克数

### 关于推荐
- 推荐前先调用 get_kitchen_state 了解当前库存
- 优先推荐：高置信度食材能做的菜 > 临期食材优先消耗 > 用户口味偏好
- 每次推荐 1-3 道菜，给出预估时间和难度
- 如果某道菜缺少 1-2 样食材，直接说明缺什么，而不是不推荐
- 用"如果你家还有XX的话"这种措辞处理低置信度食材

### 关于语气
- 像一个了解你厨房的朋友，不是一个系统
- 出错时说"我可能记错了"，不说"数据有误"
- 保持简洁，不要长篇大论
- 可以偶尔表达对食物的热情

### 关于偏好
- 从对话中自然积累用户偏好，不要主动问问卷
- 用户说"不想吃辣"就记住，下次少推辣菜
- 但不要过度僵化——偏好是倾向，不是禁忌

### 关于纠错
- 用户说"搞错了""撤回"时，立即调用 undo_last_action
- 纠错后态度轻松："好的，已经撤回了"
```

---

## 前端设计

MVP 只需要 3 个视图，用纯 HTML/CSS/JS 实现，移动端优先。

### 1. 主视图：对话界面

- 全屏聊天界面，底部输入框
- 用户 90% 的时间在这里
- 系统回复支持 Markdown 渲染（菜谱步骤等）

### 2. 厨房概览（侧边抽屉或二级页面）

- 不是传统库存列表
- 分三层展示：
  - 🟢 确定有的（confidence >= 0.7）
  - 🟡 可能有的（0.3-0.7）
  - 🔴 不确定了（< 0.3）
- 每项显示：食材名、模糊数量、多久前提到的
- 点击可手动修改/删除

### 3. 购物清单

- 独立页面（用户会在超市里看）
- 支持勾选已购买项
- 勾选后可一键将已购项加入库存

---

## 项目目录结构

```
kitchenmind/
├── CLAUDE.md              # Claude Code 项目上下文
├── PROJECT_SPEC.md        # 本文档
├── requirements.txt
├── config.py              # 配置（模型地址、数据库路径等）
│
├── data/
│   ├── kitchenmind.db     # SQLite 数据库
│   └── howtocook/         # 克隆的 HowToCook 仓库
│
├── scripts/
│   ├── parse_recipes.py   # 解析 HowToCook → JSON → SQLite
│   └── init_db.py         # 初始化数据库表结构
│
├── backend/
│   ├── main.py            # FastAPI 入口
│   ├── models.py          # Pydantic 数据模型
│   ├── database.py        # SQLite 操作封装
│   ├── agent.py           # Agent 核心逻辑（意图路由 + 工具调用）
│   ├── tools.py           # 工具函数实现（add_items, consume_items 等）
│   ├── llm.py             # LLM 调用封装（Ollama / Qwen API）
│   └── confidence.py      # 置信度衰减计算
│
├── frontend/
│   ├── index.html         # 主页面（对话界面）
│   ├── kitchen.html       # 厨房概览
│   ├── shopping.html      # 购物清单
│   ├── style.css
│   └── app.js
│
└── tests/
    ├── test_agent.py
    ├── test_tools.py
    └── test_parse.py
```

---

## 开发节奏

### 第一周：数据层

1. 克隆 HowToCook 仓库
2. 编写 `parse_recipes.py` 脚本（规则解析 + LLM 补全）
3. 编写 `init_db.py` 创建表结构
4. 导入 100+ 道结构化菜谱
5. 搭好 Ollama，确认 qwen3:8b 和大模型都能正常推理

### 第二周：Agent 核心

1. 实现意图路由层（规则 + 关键词）
2. 实现 6 个工具函数
3. 编写 agent 主循环（接收输入 → 路由 → 调模型 → 执行工具 → 返回）
4. 命令行交互测试，重点调 prompt 到意图准确率 90%+
5. 实现置信度衰减逻辑

### 第三周：前端 + 联调

1. 实现聊天界面（WebSocket 或 SSE 流式输出）
2. 实现厨房概览页
3. 实现购物清单页
4. 手机浏览器测试

### 第四周：真实使用

1. 自己连续使用一周
2. 记录所有出问题的场景
3. 根据使用数据优化 prompt 和工具逻辑

---

## 关键依赖

```
# requirements.txt
fastapi>=0.110.0
uvicorn>=0.27.0
httpx>=0.27.0        # 调用 Ollama API
pydantic>=2.0
aiosqlite>=0.20.0    # 异步 SQLite
python-multipart     # 文件上传（未来 OCR 用）
```

---

## 风险与应对


| 风险                       | 应对策略                                                   |
| -------------------------- | ---------------------------------------------------------- |
| 小模型意图识别不准         | 规则层先过滤明确意图，只把模糊的给模型；不行就全走大模型   |
| 菜谱扣减跟实际不符         | 所有扣减写日志，支持一键撤销；回复里透露扣了什么让用户校验 |
| 置信度衰减太快/太慢        | 衰减率做成配置，根据使用体验调整                           |
| 推荐质量不够好             | 用 Qwen API 做 A/B 对照，确认是模型问题还是 prompt 问题    |
| 状态漂移严重               | 定期主动校准："好像有阵子没更新了，你家现在大概还有什么？" |
| 显卡显存不够同时跑两个模型 | 默认只加载小模型，需要时再加载大模型（Ollama 会自动管理）  |
