#!/bin/bash
# KitchenMind 后端服务启动脚本

cd "$(dirname "$0")/.."

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 虚拟环境不存在，请先运行: python3 -m venv venv"
    exit 1
fi

# 检查端口是否被占用
if lsof -Pi :8888 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  端口 8888 已被占用"
    echo ""
    read -p "是否杀掉现有进程并重启? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pkill -f "uvicorn backend.main:app"
        sleep 2
        echo "✅ 已杀掉现有进程"
    else
        echo "❌ 取消启动"
        exit 1
    fi
fi

# 创建日志目录
mkdir -p logs

# 启动服务
LOG_FILE="logs/backend_$(date +%Y%m%d_%H%M%S).log"
echo "🚀 正在启动 KitchenMind 后端服务..."
echo "📋 日志文件: $LOG_FILE"
echo "🌐 服务地址: http://127.0.0.1:8888"
echo ""

./venv/bin/uvicorn backend.main:app \
    --host 127.0.0.1 \
    --port 8888 \
    --log-level info \
    > "$LOG_FILE" 2>&1 &

SERVER_PID=$!
echo "✅ 后端服务已启动 (PID: $SERVER_PID)"
echo ""
echo "查看实时日志:"
echo "  tail -f $LOG_FILE"
echo ""
echo "停止服务:"
echo "  kill $SERVER_PID"
echo "  或: pkill -f 'uvicorn backend.main:app'"
