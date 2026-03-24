# KitchenMind - 厨房状态代理

对话驱动的智能厨房助手，帮你解决"今晚吃什么"的问题。

## 快速开始

### 1. 安装依赖

```bash
# 手动安装依赖到虚拟环境
./venv/bin/pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
# 创建数据库表结构
./venv/bin/python scripts/init_db.py
```

### 3. 导入菜谱

```bash
# 解析 HowToCook 菜谱并导入数据库
./venv/bin/python scripts/parse_recipes.py
```

### 4. 启动后端（待实现）

```bash
cd backend
../venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 项目结构

```
kitchenmind/
├── CLAUDE.md              # Claude Code 项目上下文
├── PROJECT_SPEC.md        # 完整技术规范
├── config.py              # 配置文件
├── requirements.txt       # Python 依赖
│
├── data/
│   ├── kitchenmind.db     # SQLite 数据库
│   └── howtocook/         # HowToCook 菜谱仓库
│
├── scripts/
│   ├── init_db.py         # 初始化数据库
│   └── parse_recipes.py   # 解析菜谱
│
├── backend/               # FastAPI 后端（待实现）
├── frontend/              # 前端界面（待实现）
└── tests/                 # 测试（待实现）
```

## 开发进度

### ✅ 第一周：数据层
- [x] 创建项目结构
- [x] 克隆 HowToCook 菜谱仓库
- [x] 编写数据库初始化脚本
- [x] 编写菜谱解析脚本
- [x] 创建配置文件
- [ ] 运行脚本导入菜谱（需先安装依赖）

### ⏳ 第二周：Agent 核心
- [ ] 实现意图路由层
- [ ] 实现 6 个工具函数
- [ ] 编写 agent 主循环
- [ ] 实现置信度衰减逻辑
- [ ] 命令行交互测试

### ⏳ 第三周：前端 + 联调
- [ ] 实现聊天界面
- [ ] 实现厨房概览页
- [ ] 实现购物清单页

### ⏳ 第四周：真实使用
- [ ] 连续使用一周
- [ ] 优化 prompt 和工具逻辑

## 配置说明

编辑 `config.py` 修改：

- Ollama 服务地址（默认 `http://localhost:11434`）
- 使用的模型（默认 qwen2.5:7b 和 qwen2.5:32b）
- 置信度衰减率
- 其他参数

## 注意事项

- 确保 Ollama 已安装并运行
- 首次运行需要下载模型（qwen2.5:7b 约 4.7GB）
- SQLite 数据库文件会自动创建在 `data/` 目录

## 许可证

本项目使用的 HowToCook 菜谱数据采用 Unlicense 协议。
