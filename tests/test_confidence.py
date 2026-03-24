"""
置信度衰减测试

测试置信度计算和衰减模型
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.confidence import (
    calculate_current_confidence,
    get_confidence_description,
    should_recommend,
    get_recommendation_note,
    DECAY_RATES
)


def test_vegetable_decay_fast():
    """测试蔬菜快速衰减（5天左右归零）"""
    item = {
        "name": "白菜",
        "category": "蔬菜",
        "confidence": 1.0,
        "last_mentioned_at": (datetime.now() - timedelta(days=5)).isoformat()
    }

    current = calculate_current_confidence(item)

    # 5天后应该显著降低
    # 计算公式: 1.0 * (1 - 0.15) ^ 5 = 1.0 * 0.85 ^ 5 ≈ 0.44
    assert current < 0.5
    assert current > 0.4


def test_vegetable_decay_1day():
    """测试蔬菜 1 天衰减"""
    item = {
        "name": "青菜",
        "category": "蔬菜",
        "confidence": 1.0,
        "last_mentioned_at": (datetime.now() - timedelta(days=1)).isoformat()
    }

    current = calculate_current_confidence(item)

    # 1天后: 1.0 * 0.85 ^ 1 = 0.85
    assert 0.84 < current < 0.86


def test_fruit_decay():
    """测试水果衰减（比蔬菜更快）"""
    item = {
        "name": "草莓",
        "category": "水果",
        "confidence": 1.0,
        "last_mentioned_at": (datetime.now() - timedelta(days=3)).isoformat()
    }

    current = calculate_current_confidence(item)

    # 水果衰减率 0.18，3天后应该明显降低
    # 1.0 * (1 - 0.18) ^ 3 = 0.82 ^ 3 ≈ 0.55
    assert current < 0.6


def test_meat_decay():
    """测试肉类衰减（约7天）"""
    item = {
        "name": "猪肉",
        "category": "肉类",
        "confidence": 1.0,
        "last_mentioned_at": (datetime.now() - timedelta(days=5)).isoformat()
    }

    current = calculate_current_confidence(item)

    # 肉类衰减率 0.10，5天后
    # 1.0 * (1 - 0.10) ^ 5 = 0.9 ^ 5 ≈ 0.59
    assert 0.55 < current < 0.65


def test_seasoning_no_decay():
    """测试调味品几乎不衰减"""
    item = {
        "name": "盐",
        "category": "调味品",
        "confidence": 1.0,
        "last_mentioned_at": (datetime.now() - timedelta(days=30)).isoformat()
    }

    current = calculate_current_confidence(item)

    # 调味品衰减率 0.01，30天后
    # 1.0 * (1 - 0.01) ^ 30 = 0.99 ^ 30 ≈ 0.74
    assert current > 0.7


def test_frozen_slow_decay():
    """测试冷冻食品缓慢衰减"""
    item = {
        "name": "冻虾",
        "category": "冷冻",
        "confidence": 1.0,
        "last_mentioned_at": (datetime.now() - timedelta(days=20)).isoformat()
    }

    current = calculate_current_confidence(item)

    # 冷冻衰减率 0.02，20天后
    # 1.0 * (1 - 0.02) ^ 20 = 0.98 ^ 20 ≈ 0.67
    assert current > 0.6


def test_confidence_never_negative():
    """测试置信度不会变成负数"""
    item = {
        "name": "过期蔬菜",
        "category": "蔬菜",
        "confidence": 1.0,
        "last_mentioned_at": (datetime.now() - timedelta(days=100)).isoformat()
    }

    current = calculate_current_confidence(item)

    # 无论多久，置信度都应该 >= 0
    assert current >= 0.0


def test_confidence_never_exceeds_base():
    """测试置信度不会超过初始值"""
    item = {
        "name": "新鲜蔬菜",
        "category": "蔬菜",
        "confidence": 0.8,
        "last_mentioned_at": datetime.now().isoformat()
    }

    current = calculate_current_confidence(item)

    # 不会超过初始置信度
    assert current <= 0.8


def test_confidence_description_high():
    """测试高置信度描述"""
    desc = get_confidence_description(0.9)
    assert desc == "确定有"

    desc = get_confidence_description(0.7)
    assert desc == "确定有"


def test_confidence_description_medium():
    """测试中等置信度描述"""
    desc = get_confidence_description(0.5)
    assert desc == "可能有"

    desc = get_confidence_description(0.4)
    assert desc == "可能有"


def test_confidence_description_low():
    """测试低置信度描述"""
    desc = get_confidence_description(0.2)
    assert desc == "不确定"

    desc = get_confidence_description(0.05)
    assert desc == "不确定"


def test_should_recommend_high():
    """测试高置信度应该推荐"""
    assert should_recommend(0.8) is True
    assert should_recommend(0.7) is True


def test_should_recommend_medium():
    """测试中等置信度应该附带说明"""
    assert should_recommend(0.5) is True
    assert should_recommend(0.3) is True


def test_should_not_recommend_low():
    """测试低置信度不推荐"""
    assert should_recommend(0.2) is False
    assert should_recommend(0.1) is False


def test_recommendation_note():
    """测试推荐备注生成"""
    # 高置信度不需要备注
    note = get_recommendation_note(0.9, "鸡蛋")
    assert note == ""

    # 中等置信度需要提示
    note = get_recommendation_note(0.5, "西红柿")
    assert "如果你家还有西红柿的话" in note


def test_decay_rates_coverage():
    """测试所有分类都有衰减率"""
    categories = ["蔬菜", "水果", "肉类", "蛋奶", "主食", "调味品", "冷冻", "其他"]

    for category in categories:
        assert category in DECAY_RATES, f"{category} 缺少衰减率配置"
        assert 0 <= DECAY_RATES[category] <= 1, f"{category} 衰减率超出范围"


def test_zero_days_no_decay():
    """测试刚添加的食材（0天）不衰减"""
    item = {
        "name": "新买的白菜",
        "category": "蔬菜",
        "confidence": 1.0,
        "last_mentioned_at": datetime.now().isoformat()
    }

    current = calculate_current_confidence(item)

    # 刚添加的应该非常接近原始置信度（允许微小浮点误差）
    assert abs(current - 1.0) < 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
