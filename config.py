"""
KitchenMind 配置文件
"""
from pathlib import Path
import os

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# 数据库配置
DB_PATH = PROJECT_ROOT / "data" / "kitchenmind.db"

# Ollama 配置
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_SMALL_MODEL = "qwen3.5:9b"  # 意图识别、参数提取
OLLAMA_LARGE_MODEL = "qwen3.5:9b"  # 临时降级为 9b 以提升推荐响应速度和排障效率

# LLM 提供方选择
# auto: 优先 Ollama，失败后回退 Qwen
# ollama: 仅使用本地 Ollama
# qwen: 仅使用在线 Qwen
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "qwen")

# 云端备用 API（可选）
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_API_BASE = os.getenv("QWEN_API_BASE", "https://coding.dashscope.aliyuncs.com/v1")

# 置信度衰减率（每天）
DECAY_RATES = {
    "蔬菜": 0.15,
    "水果": 0.18,
    "肉类": 0.10,
    "蛋奶": 0.08,
    "主食": 0.05,
    "调味品": 0.01,
    "冷冻": 0.02,
    "其他": 0.10,
}

# 置信度阈值
CONFIDENCE_HIGH = 0.7  # 高置信度，直接使用
CONFIDENCE_MED = 0.3   # 中置信度，需要提示
# < 0.3 低置信度，不参与推荐

# Agent 配置
MAX_SUGGESTIONS = 3  # 最多推荐菜品数
DEFAULT_SERVING = 1  # 默认份数
