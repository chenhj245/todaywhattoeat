"""
Agent 工具函数实现

6 个核心工具：add_items, consume_items, get_kitchen_state,
suggest_meals, generate_shopping_list, undo_last_action
"""
from typing import List, Dict, Optional
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import database as db
from backend.confidence import (
    calculate_current_confidence,
    get_confidence_description,
    should_recommend,
    get_recommendation_note
)
from backend.ingredient_classifier import classify_ingredient, find_similar_ingredients


async def add_items(items: List[Dict]) -> Dict:
    """
    添加食材到厨房库存

    Args:
        items: 食材列表，每项包含:
            - name: 食材名称 (必需)
            - category: 分类 (可选，未提供时自动推断)
            - quantity_desc: 模糊数量 (可选)
            - quantity_num: 精确数量 (可选)
            - unit: 单位 (可选)

    Returns:
        操作结果
    """
    added = []

    for item in items:
        name = item.get("name")
        if not name:
            continue

        # 自动推断分类（如果未提供）
        category = item.get("category")
        if not category:
            category = classify_ingredient(name)

        item_id = await db.add_kitchen_item(
            name=name,
            category=category,
            quantity_desc=item.get("quantity_desc", "一些"),
            quantity_num=item.get("quantity_num"),
            unit=item.get("unit"),
            confidence=1.0,  # 新添加的食材置信度为1
            source="user_input"
        )

        added.append({
            "id": item_id,
            "name": name,
            "category": category,
            "quantity": item.get("quantity_desc", "一些")
        })

    # 记录操作日志
    await db.log_action(
        action_type="add",
        payload={"items": added},
        user_input=None  # 由调用方设置
    )

    return {
        "success": True,
        "added_count": len(added),
        "items": added,
        "message": f"已添加 {len(added)} 种食材"
    }


async def consume_items(
    reason: str,
    recipe_name: Optional[str] = None,
    items: Optional[List[Dict]] = None
) -> Dict:
    """
    标记食材被消耗

    Args:
        reason: 消耗原因
        recipe_name: 菜谱名称（如果是做菜）
        items: 手动指定的食材列表

    Returns:
        操作结果
    """
    consumed = []

    # 如果指定了菜谱，从数据库查找并扣减
    if recipe_name:
        recipe = await db.get_recipe_by_name(recipe_name)
        if recipe:
            # 遍历菜谱中的食材，标记为消耗
            for ingredient in recipe.get("ingredients", []):
                ing_name = ingredient.get("name")
                if ing_name:
                    # 查找厨房中是否有这个食材（支持模糊匹配和同义词）
                    kitchen_items = await db.get_active_items()
                    matched_items = find_similar_ingredients(ing_name, kitchen_items)

                    if matched_items:
                        # 使用第一个匹配项
                        kit_item = matched_items[0]
                        await db.remove_item(kit_item["id"])
                        consumed.append({
                            "id": kit_item["id"],  # 保存 ID 用于撤销
                            "name": kit_item["name"],
                            "amount": ingredient.get("amount", "")
                        })

    # 如果手动指定了食材
    elif items:
        for item in items:
            name = item.get("name")
            if name:
                # 查找并移除（支持模糊匹配）
                kitchen_items = await db.get_active_items()
                matched_items = find_similar_ingredients(name, kitchen_items)

                if matched_items:
                    # 使用第一个匹配项
                    kit_item = matched_items[0]
                    await db.remove_item(kit_item["id"])
                    consumed.append({
                        "id": kit_item["id"],  # 保存 ID 用于撤销
                        "name": kit_item["name"],
                        "amount": item.get("amount", "")
                    })

    # 记录操作日志
    await db.log_action(
        action_type="consume",
        payload={
            "reason": reason,
            "recipe_name": recipe_name,
            "items": consumed
        }
    )

    return {
        "success": True,
        "consumed_count": len(consumed),
        "items": consumed,
        "message": f"{reason}，消耗了 {len(consumed)} 种食材"
    }


async def get_kitchen_state(min_confidence: float = 0.1) -> Dict:
    """
    获取当前厨房状态

    Args:
        min_confidence: 最低基础置信度

    Returns:
        厨房状态信息
    """
    items = await db.get_active_items(min_confidence=min_confidence)

    # 计算当前实际置信度
    items_with_confidence = []
    for item in items:
        current_conf = calculate_current_confidence(item)
        conf_desc = get_confidence_description(current_conf)

        # 生成推荐备注
        recommend_note = get_recommendation_note(current_conf, item["name"])

        items_with_confidence.append({
            "id": item["id"],
            "name": item["name"],
            "category": item["category"],
            "quantity_desc": item["quantity_desc"],
            "effective_confidence": round(current_conf, 2),
            "confidence_desc": conf_desc,
            "last_mentioned_at": item["last_mentioned_at"],
            "source": item.get("source", "user_input"),
            "recommendation": recommend_note
        })

    # 按置信度分组
    high = [i for i in items_with_confidence if i["effective_confidence"] >= 0.7]
    medium = [i for i in items_with_confidence if 0.3 <= i["effective_confidence"] < 0.7]
    low = [i for i in items_with_confidence if i["effective_confidence"] < 0.3]

    return {
        "success": True,
        "total_items": len(items_with_confidence),
        "high_confidence": high,
        "medium_confidence": medium,
        "low_confidence": low,
        "message": f"厨房共有 {len(high)} 种确定有的食材，{len(medium)} 种可能有的"
    }


async def suggest_meals(
    constraints: Optional[str] = None,
    max_results: int = 3
) -> Dict:
    """
    根据库存和约束推荐菜品

    Args:
        constraints: 自然语言约束（如"快手菜"、"不要辣"）
        max_results: 最多推荐数量

    Returns:
        推荐结果
    """
    # 获取当前库存
    kitchen_state = await get_kitchen_state(min_confidence=0.3)
    available_items = {
        item["name"]: item["effective_confidence"]
        for item in (
            kitchen_state["high_confidence"] +
            kitchen_state["medium_confidence"]
        )
    }

    # 解析约束
    max_time = None
    max_difficulty = None
    prefer_lowfat = False  # 低脂偏好
    prefer_light = False   # 清淡偏好

    if constraints:
        if "快手" in constraints or "简单" in constraints:
            max_time = 20
            max_difficulty = 2
        elif "复杂" not in constraints:
            max_difficulty = 3

        # 解析健康/减肥约束
        if "减肥" in constraints or "低脂" in constraints or "低卡" in constraints:
            prefer_lowfat = True
        if "清淡" in constraints or "少油" in constraints:
            prefer_light = True

    # 搜索菜谱
    recipes = await db.search_recipes(
        max_difficulty=max_difficulty,
        max_time=max_time,
        limit=max_results * 5  # 多取一些候选，后面会过滤
    )

    # 高油脂食材列表（用于减肥约束）
    high_fat_ingredients = ["猪肉", "五花肉", "牛肉", "羊肉", "培根", "香肠", "腊肉", "黄油", "奶油"]
    heavy_flavor = ["辣椒", "花椒", "麻辣", "重口"]

    # 评分并排序
    scored_recipes = []
    for recipe in recipes:
        # 计算可用食材匹配度
        recipe_ingredients = recipe.get("ingredients", [])
        if not recipe_ingredients:
            continue

        available_count = sum(
            1 for ing in recipe_ingredients
            if ing.get("name") in available_items
        )

        match_rate = available_count / len(recipe_ingredients) if recipe_ingredients else 0

        # 计算约束惩罚分
        penalty = 0.0

        # 减肥/低脂约束：惩罚含高油脂食材的菜
        if prefer_lowfat:
            has_high_fat = any(
                any(fat in ing.get("name", "") for fat in high_fat_ingredients)
                for ing in recipe_ingredients
            )
            if has_high_fat:
                penalty += 0.3  # 降低30%匹配度

        # 清淡约束：惩罚重口味菜
        if prefer_light:
            recipe_name = recipe.get("name", "")
            is_heavy = any(flavor in recipe_name for flavor in heavy_flavor)
            if is_heavy:
                penalty += 0.2  # 降低20%匹配度

        # 应用惩罚
        final_score = max(0, match_rate - penalty)

        scored_recipes.append({
            "recipe": recipe,
            "match_rate": match_rate,
            "final_score": final_score,
            "available_count": available_count,
            "total_ingredients": len(recipe_ingredients)
        })

    # 按最终得分排序
    scored_recipes.sort(key=lambda x: x["final_score"], reverse=True)

    # 构建推荐结果
    suggestions = []
    for scored in scored_recipes[:max_results]:
        recipe = scored["recipe"]
        missing = []

        for ing in recipe.get("ingredients", []):
            ing_name = ing.get("name")
            if ing_name not in available_items:
                missing.append(ing_name)

        suggestions.append({
            "name": recipe["name"],
            "category": recipe["category"],
            "difficulty": recipe["difficulty"],
            "time_minutes": recipe["time_minutes"],
            "match_rate": round(scored["match_rate"] * 100, 1),
            "missing_ingredients": missing
        })

    return {
        "success": True,
        "suggestions": suggestions,
        "message": f"根据你的厨房状态，推荐 {len(suggestions)} 道菜"
    }


async def generate_shopping_list(
    planned_meals: Optional[List[str]] = None
) -> Dict:
    """
    生成购物清单

    Args:
        planned_meals: 计划要做的菜名列表

    Returns:
        购物清单
    """
    shopping_list = []

    if planned_meals:
        # 基于计划菜品生成
        for meal_name in planned_meals:
            recipe = await db.get_recipe_by_name(meal_name)
            if not recipe:
                continue

            # 检查每种食材是否缺少
            for ing in recipe.get("ingredients", []):
                ing_name = ing.get("name")
                # 查看厨房是否有
                kitchen_items = await db.get_active_items()
                has_item = any(
                    item["name"] == ing_name
                    for item in kitchen_items
                )

                if not has_item:
                    shopping_list.append({
                        "name": ing_name,
                        "amount": ing.get("amount", "适量"),
                        "unit": ing.get("unit", ""),
                        "for_recipe": meal_name
                    })
    else:
        # 基于常用食材（简化版，后续可以优化）
        shopping_list.append({
            "name": "根据计划菜品生成购物清单",
            "amount": "",
            "unit": "",
            "for_recipe": None
        })

    # 去重
    unique_list = {}
    for item in shopping_list:
        name = item["name"]
        if name not in unique_list:
            unique_list[name] = item
        else:
            # 合并同名食材
            existing = unique_list[name]
            if item.get("for_recipe"):
                existing.setdefault("for_recipes", []).append(item["for_recipe"])

    return {
        "success": True,
        "shopping_list": list(unique_list.values()),
        "message": f"购物清单包含 {len(unique_list)} 种食材"
    }


async def undo_last_action() -> Dict:
    """
    撤销上一次操作

    Returns:
        撤销结果
    """
    last_action = await db.get_last_action()

    if not last_action:
        return {
            "success": False,
            "message": "没有可撤销的操作"
        }

    action_type = last_action["action_type"]
    payload = last_action["payload"]

    # 根据操作类型执行反向操作
    if action_type == "add":
        # 撤销添加 = 移除食材
        for item in payload.get("items", []):
            item_id = item.get("id")
            if item_id:
                await db.remove_item(item_id)

    elif action_type == "consume":
        # 撤销消耗 = 恢复被删除的食材
        for item in payload.get("items", []):
            item_id = item.get("id")
            if item_id:
                await db.restore_item(item_id)

    # 标记为已撤销
    await db.mark_action_undone(last_action["id"])

    return {
        "success": True,
        "action_type": action_type,
        "message": f"已撤销 {action_type} 操作，库存已恢复"
    }


# 工具定义（OpenAI 格式）
TOOLS_DEFINITION = [
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
                                "quantity_desc": {
                                    "type": "string",
                                    "enum": ["充足", "一些", "少量"],
                                    "description": "模糊数量"
                                },
                                "quantity_num": {"type": "number", "description": "精确数量，如果用户提到了的话"},
                                "unit": {"type": "string", "description": "单位"},
                                "category": {
                                    "type": "string",
                                    "enum": ["蔬菜", "肉类", "蛋奶", "调味品", "主食", "冷冻", "水果", "其他"]
                                }
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
            "description": "标记食材被消耗。当用户说'做了XXX菜'、'吃了XXX'、'用掉了XXX'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "消耗原因，如'做了番茄炒蛋'"},
                    "recipe_name": {"type": "string", "description": "如果是做了某道菜，菜名是什么"},
                    "items": {
                        "type": "array",
                        "description": "手动指定消耗的食材（如果不是按菜谱消耗）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "amount": {"type": "string"}
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
            "description": "获取当前厨房所有食材的状态。用于推荐菜品前了解库存。",
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
            "description": "生成购物清单。可以基于计划做的菜。",
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
