"""
置信度衰减计算模块

食材的置信度会随时间自然衰减，不同类别的衰减速率不同。
"""
from datetime import datetime
from typing import Dict

# 从 config 导入衰减率配置
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DECAY_RATES, CONFIDENCE_HIGH, CONFIDENCE_MED


def calculate_current_confidence(item: Dict) -> float:
    """
    计算食材当前的实际置信度

    Args:
        item: 食材字典，必须包含:
            - last_mentioned_at: ISO 格式时间字符串
            - confidence: 基础置信度
            - category: 食材分类

    Returns:
        当前实际置信度 (0.0-1.0)

    公式: current = base * (1 - rate) ^ days
    """
    try:
        last_mentioned = datetime.fromisoformat(item["last_mentioned_at"])
    except (KeyError, ValueError) as e:
        # 如果时间字段缺失或格式错误，返回0
        return 0.0

    # 计算经过的天数
    days_elapsed = (datetime.now() - last_mentioned).total_seconds() / 86400

    # 获取衰减率（默认为"其他"类别）
    rate = DECAY_RATES.get(item.get("category"), DECAY_RATES["其他"])

    # 计算当前置信度
    base_confidence = item.get("confidence", 1.0)
    current = base_confidence * ((1 - rate) ** days_elapsed)

    return max(0.0, min(1.0, current))  # 限制在 [0, 1] 范围


def get_confidence_level(confidence: float) -> str:
    """
    将置信度转换为语义描述

    Args:
        confidence: 0.0-1.0 的置信度值

    Returns:
        "high" / "medium" / "low"
    """
    if confidence >= CONFIDENCE_HIGH:
        return "high"
    elif confidence >= CONFIDENCE_MED:
        return "medium"
    else:
        return "low"


def get_confidence_description(confidence: float) -> str:
    """
    获取置信度的中文描述

    Args:
        confidence: 0.0-1.0 的置信度值

    Returns:
        中文描述字符串
    """
    if confidence >= CONFIDENCE_HIGH:
        return "确定有"
    elif confidence >= CONFIDENCE_MED:
        return "可能有"
    else:
        return "不确定"


def should_recommend(confidence: float) -> bool:
    """
    判断是否应该在推荐中使用此食材

    Args:
        confidence: 0.0-1.0 的置信度值

    Returns:
        True 如果可以用于推荐（即使需要加提示）
    """
    return confidence >= CONFIDENCE_MED


def get_recommendation_note(confidence: float, item_name: str) -> str:
    """
    获取推荐时的备注文本

    Args:
        confidence: 0.0-1.0 的置信度值
        item_name: 食材名称

    Returns:
        备注文本，高置信度返回空字符串
    """
    if confidence >= CONFIDENCE_HIGH:
        return ""
    elif confidence >= CONFIDENCE_MED:
        return f"（如果你家还有{item_name}的话）"
    else:
        return ""
