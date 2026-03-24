"""
食材分类器测试

测试自动分类和同义词匹配功能
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.ingredient_classifier import (
    classify_ingredient,
    normalize_ingredient_name,
    find_similar_ingredients
)


def test_classify_vegetable():
    """测试蔬菜分类"""
    assert classify_ingredient("白菜") == "蔬菜"
    assert classify_ingredient("西红柿") == "蔬菜"
    assert classify_ingredient("土豆") == "蔬菜"
    assert classify_ingredient("青椒") == "蔬菜"


def test_classify_meat():
    """测试肉类分类"""
    assert classify_ingredient("猪肉") == "肉类"
    assert classify_ingredient("牛肉") == "肉类"
    assert classify_ingredient("鸡肉") == "肉类"
    assert classify_ingredient("排骨") == "肉类"


def test_classify_egg_dairy():
    """测试蛋奶分类"""
    assert classify_ingredient("鸡蛋") == "蛋奶"
    assert classify_ingredient("牛奶") == "蛋奶"
    assert classify_ingredient("豆腐") == "蛋奶"
    assert classify_ingredient("酸奶") == "蛋奶"


def test_classify_seafood():
    """测试水产分类"""
    assert classify_ingredient("鱼") == "水产"
    assert classify_ingredient("虾") == "水产"
    assert classify_ingredient("螃蟹") == "水产"
    assert classify_ingredient("鲈鱼") == "水产"


def test_classify_staple():
    """测试主食分类"""
    assert classify_ingredient("米") == "主食"
    assert classify_ingredient("面") == "主食"
    assert classify_ingredient("面粉") == "主食"
    assert classify_ingredient("面条") == "主食"


def test_classify_seasoning():
    """测试调味品分类"""
    assert classify_ingredient("盐") == "调味品"
    assert classify_ingredient("酱油") == "调味品"
    assert classify_ingredient("醋") == "调味品"
    assert classify_ingredient("油") == "调味品"


def test_classify_fruit():
    """测试水果分类"""
    assert classify_ingredient("苹果") == "水果"
    assert classify_ingredient("香蕉") == "水果"
    assert classify_ingredient("橙子") == "水果"
    assert classify_ingredient("草莓") == "水果"


def test_classify_frozen():
    """测试冷冻分类"""
    assert classify_ingredient("冻虾") == "冷冻"
    assert classify_ingredient("冰淇淋") == "冷冻"
    assert classify_ingredient("速冻饺子") == "冷冻"


def test_classify_partial_match():
    """测试部分匹配（包含关系）"""
    # "小白菜" 包含 "白菜"
    assert classify_ingredient("小白菜") == "蔬菜"

    # "五花肉" 包含 "肉"
    assert classify_ingredient("五花肉") == "肉类"

    # "鲜虾仁" 包含 "虾"
    assert classify_ingredient("鲜虾仁") == "水产"


def test_classify_keyword_match():
    """测试关键词匹配"""
    # 新的蔬菜品种，但包含"菜"字
    assert classify_ingredient("新鲜的某某菜") == "蔬菜"

    # 新的肉类，但包含"肉"字
    assert classify_ingredient("某某肉") == "肉类"


def test_classify_unknown():
    """测试无法识别的食材"""
    # 完全不在词典中，且无关键词
    result = classify_ingredient("未知食材XYZ")
    assert result == "其他"


def test_normalize_synonyms():
    """测试同义词标准化"""
    assert normalize_ingredient_name("西红柿") == "番茄"
    assert normalize_ingredient_name("洋芋") == "土豆"
    assert normalize_ingredient_name("马铃薯") == "土豆"
    assert normalize_ingredient_name("地瓜") == "红薯"
    assert normalize_ingredient_name("芫荽") == "香菜"


def test_normalize_no_synonym():
    """测试没有同义词的食材"""
    # 没有同义词的应该返回原名
    assert normalize_ingredient_name("鸡蛋") == "鸡蛋"
    assert normalize_ingredient_name("白菜") == "白菜"


def test_find_similar_exact_match():
    """测试精确匹配"""
    inventory = [
        {"name": "鸡蛋", "id": 1},
        {"name": "西红柿", "id": 2},
        {"name": "白菜", "id": 3}
    ]

    results = find_similar_ingredients("鸡蛋", inventory)
    assert len(results) == 1
    assert results[0]["name"] == "鸡蛋"


def test_find_similar_synonym_match():
    """测试同义词匹配"""
    inventory = [
        {"name": "西红柿", "id": 1},
        {"name": "鸡蛋", "id": 2}
    ]

    # 用"番茄"（同义词）查找"西红柿"
    results = find_similar_ingredients("番茄", inventory)
    assert len(results) == 1
    assert results[0]["name"] == "西红柿"


def test_find_similar_partial_match():
    """测试部分匹配"""
    inventory = [
        {"name": "小白菜", "id": 1},
        {"name": "大白菜", "id": 2},
        {"name": "鸡蛋", "id": 3}
    ]

    # 用"白菜"应该能匹配到"小白菜"和"大白菜"
    results = find_similar_ingredients("白菜", inventory)
    assert len(results) == 2


def test_find_similar_no_match():
    """测试没有匹配"""
    inventory = [
        {"name": "鸡蛋", "id": 1},
        {"name": "西红柿", "id": 2}
    ]

    results = find_similar_ingredients("猪肉", inventory)
    assert len(results) == 0


def test_find_similar_empty_inventory():
    """测试空库存"""
    results = find_similar_ingredients("鸡蛋", [])
    assert len(results) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
