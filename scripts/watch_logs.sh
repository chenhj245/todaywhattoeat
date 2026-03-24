#!/bin/bash
# KitchenMind 后端日志实时查看脚本

LOG_FILE="/tmp/kitchenmind_$(date +%Y%m%d).log"

# 如果指定了日志文件参数，使用指定的文件
if [ "$1" != "" ]; then
    LOG_FILE="$1"
fi

echo "📋 查看 KitchenMind 后端日志: $LOG_FILE"
echo "按 Ctrl+C 退出"
echo "---"

# 如果文件不存在，提示用户
if [ ! -f "$LOG_FILE" ]; then
    echo "⚠️  日志文件不存在: $LOG_FILE"
    echo ""
    echo "提示：请先启动后端服务："
    echo "  cd /mnt/newdisk/kitchenmind"
    echo "  ./scripts/start_backend.sh"
    exit 1
fi

# 实时查看日志
tail -f "$LOG_FILE"
