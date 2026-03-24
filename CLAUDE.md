# CLAUDE.md — KitchenMind 项目上下文

## 这是什么项目

KitchenMind 是一个"对话驱动的厨房状态代理"。用户通过自然语言告诉系统买了什么、做了什么菜，系统自动维护一个模糊库存，然后围绕"今晚吃什么""缺什么要买""哪些食材快坏了"给出建议。

核心定位：**用户不是来管理冰箱的，是来解决"吃什么"的。** 所有库存管理都是隐性的后台行为。

## 项目阶段

当前是 MVP 阶段，仅开发者个人使用，验证核心体验是否成立。

## 完整技术规范

**请先阅读 `PROJECT_SPEC.md`**，里面包含：

- 完整的技术架构和选型理由
- 数据库表结构（SQLite）
- Agent 工具定义（6 个工具的完整 JSON Schema）
- 意图路由层实现
- 置信度衰减模型
- LLM system prompt
- HowToCook 菜谱解析策略
- 前端设计要求
- 项目目录结构
- 分周开发节奏

## 技术栈

- **语言**：Python 3.11+
- **后端**：FastAPI + aiosqlite
- **数据库**：SQLite（单文件，`data/kitchenmind.db`）
- **本地推理**：Ollama（qwen3.5:9b 做简单意图，大模型做复杂推荐）
- **云端备用**：Qwen 3.5 High API
- **前端**：纯 HTML/CSS/JS，移动端优先，不用框架
- **菜谱来源**：HowToCook GitHub 仓库（Unlicense）

## 开发环境

- 操作系统：Ubuntu（Precision 3660 工作站）
- GPU：消费级显卡（3090/4090 级别）
- Ollama 运行在本地，API 地址默认 `http://localhost:11434`
- 开发者熟悉 Python，不太熟悉前端框架

## 关键设计决策（已确认，请遵守）

1. **数据库用 SQLite**，不用 PostgreSQL/Supabase（单用户场景）
2. **库存模型是模糊的**，不追求精确到克。用 `充足/一些/快没了/不确定` 这种描述
3. **置信度随时间衰减**：蔬菜每天 -15%，调味品每天 -1%，具体见 PROJECT_SPEC.md
4. **意图路由先用规则（正则匹配），再交给模型**：不要每次请求都走 LLM
5. **所有 agent 写库操作必须写 action_log**：用于撤销和调试
6. **菜谱扣减要透明**：回复里要告诉用户"我把XX标记为用掉了"
7. **前端极简**：只需要对话界面 + 厨房概览 + 购物清单三个视图
8. **LLM 回复语气像朋友**，不像系统。"我可能记错了" 而不是 "数据有误请更新"

## 菜谱数据

菜谱来自 HowToCook 仓库（`data/howtocook/`），需要写解析脚本把 Markdown 转成结构化 JSON 入库。

菜谱 Markdown 的典型结构：

```markdown
# 菜名的做法
简介...
预估烹饪难度：★★
## 必备原料和工具
* 食材1
* 食材2
## 计算
* 食材1 = X 个 * 份数
* 食材2 = Y 克 * 份数
## 操作
* 步骤1
* 步骤2
## 附加内容
变体和备注...
```

目录结构映射：

- `dishes/vegetable_dish/` → 素菜
- `dishes/meat_dish/` → 荤菜
- `dishes/aquatic/` → 水产
- `dishes/breakfast/` → 早餐
- `dishes/staple/` → 主食
- `dishes/soup/` → 汤粥
- `dishes/dessert/` → 甜品
- `dishes/drink/` → 饮料

## 常用命令

```bash
# 启动 Ollama（如果未运行）
ollama serve

# 启动后端
cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 初始化数据库
python scripts/init_db.py

# 解析菜谱
python scripts/parse_recipes.py

# 运行测试
pytest tests/
```

## 编码规范

- 所有中文注释和文档用中文
- 变量名和函数名用英文
- 数据库字段名用英文下划线命名
- API 响应中面向用户的文本用中文
- 用 type hints
- 异步优先（FastAPI 路由和数据库操作都用 async）

## 不要做的事

- 不要引入 ORM（SQLite + 原生 SQL + aiosqlite 足够）
- 不要加用户认证（单用户）
- 不要做原生 App（Web 优先）
- 不要做 OCR / 条码扫描（MVP 不做）
- 不要让用户填表单录入食材（对话是唯一入口）
- 不要追求食材精确到克（模糊是设计决策）
