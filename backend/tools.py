"""
Agent 工具函数实现

6 个核心工具：add_items, consume_items, get_kitchen_state,
suggest_meals, generate_shopping_list, undo_last_action
"""
from typing import List, Dict, Optional
import json
import re
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
from backend.ingredient_classifier import classify_ingredient, find_similar_ingredients, normalize_ingredient_name, SYNONYMS


RECIPE_NAME_REPLACEMENTS = {
    '炒蛋': '炒鸡蛋',
    '蛋花汤': '鸡蛋汤',
}


def normalize_recipe_name(name: str) -> str:
    normalized = (name or '').strip()
    if not normalized:
        return normalized

    inverse_synonyms = {value: key for key, value in SYNONYMS.items()}
    replacements = list(SYNONYMS.items()) + list(inverse_synonyms.items()) + list(RECIPE_NAME_REPLACEMENTS.items())
    for src, target in sorted(replacements, key=lambda x: len(x[0]), reverse=True):
        if src in normalized:
            normalized = normalized.replace(src, target)
    return normalized


async def resolve_recipe(recipe_name: str) -> Optional[Dict]:
    if not recipe_name:
        return None

    exact = await db.get_recipe_by_name(recipe_name)
    if exact:
        return exact

    normalized_target = normalize_recipe_name(recipe_name)
    recipes = await db.search_recipes(limit=500)

    best_name = None
    best_score = 0
    for recipe in recipes:
        current_name = recipe.get('name', '')
        normalized_name = normalize_recipe_name(current_name)
        if normalized_name == normalized_target:
            return await db.get_recipe_by_name(current_name)
        score = 0
        if normalized_target in normalized_name or normalized_name in normalized_target:
            score += 10
        common_chars = set(normalized_target) & set(normalized_name)
        score += len(common_chars)
        if score > best_score:
            best_score = score
            best_name = current_name

    if best_name and best_score >= max(4, len(set(normalized_target)) // 2):
        return await db.get_recipe_by_name(best_name)
    return None


PANTRY_INGREDIENTS = {
    "食用油", "油", "盐", "糖", "白糖", "冰糖", "酱油", "生抽", "老抽", "醋", "料酒",
    "蚝油", "淀粉", "胡椒粉", "白胡椒", "黑胡椒", "鸡精", "味精", "豆瓣酱"
}
OPTIONAL_INGREDIENTS = {"葱花", "白芝麻", "芝麻", "香菜", "熟芝麻"}


def classify_missing_ingredient(name: str) -> str:
    cleaned = (name or '').strip()
    if not cleaned:
        return 'hard'

    normalized = cleaned.replace('（', '(').replace('）', ')')
    if '可选' in normalized:
        return 'optional'

    base = re.sub(r'\(.*?\)', '', normalized).strip()
    if base in OPTIONAL_INGREDIENTS:
        return 'optional'
    if base in PANTRY_INGREDIENTS:
        return 'pantry'

    pantry_keywords = ['油', '盐', '糖', '酱油', '生抽', '老抽', '醋', '料酒', '胡椒', '淀粉', '蚝油', '鸡精', '味精']
    optional_keywords = ['葱花', '芝麻', '香菜']
    if any(keyword in base for keyword in optional_keywords):
        return 'optional'
    if any(keyword in base for keyword in pantry_keywords):
        return 'pantry'
    return 'hard'


def split_missing_ingredients(names: List[str]) -> Dict[str, List[str]]:
    buckets = {'hard': [], 'pantry': [], 'optional': []}
    for name in names:
        kind = classify_missing_ingredient(name)
        buckets[kind].append(name)
    return buckets


async def add_items(items: List[Dict]) -> Dict:
    """
    添加食材到厨房库存（支持去重和合并）

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

        # 查找是否已有同名或相似的活跃食材
        kitchen_items = await db.get_active_items()
        matched_items = find_similar_ingredients(name, kitchen_items)

        if matched_items:
            # 找到已有食材，更新而非新增
            existing_item = matched_items[0]
            item_id = existing_item["id"]

            # 更新 last_mentioned_at 和 confidence
            await db.update_item_mentioned(item_id)

            # 处理数量合并
            new_quantity_num = item.get("quantity_num")
            new_quantity_desc = item.get("quantity_desc", "一些")

            if new_quantity_num is not None:
                # 新输入有精确数量
                if existing_item["quantity_num"] is not None:
                    # 已有也是精确数量，累加
                    merged_quantity = existing_item["quantity_num"] + new_quantity_num
                    await db.update_item_quantity(item_id, quantity_num=merged_quantity)
                else:
                    # 已有是模糊描述，用精确数量替换
                    await db.update_item_quantity(item_id, quantity_num=new_quantity_num)
            else:
                # 新输入只有模糊描述
                if existing_item["quantity_num"] is None:
                    # 都是模糊描述，取更充足的那个
                    desc_priority = {"充足": 3, "一些": 2, "快没了": 1, "少量": 1}
                    existing_priority = desc_priority.get(existing_item["quantity_desc"], 2)
                    new_priority = desc_priority.get(new_quantity_desc, 2)

                    if new_priority > existing_priority:
                        await db.update_item_quantity(item_id, quantity_desc=new_quantity_desc)
                # 如果已有精确数量，不降级为模糊描述

            # 恢复 confidence 到高值（显式添加/购买行为）
            async with db.get_db() as database:
                await database.execute(
                    "UPDATE kitchen_items SET confidence = 1.0 WHERE id = ?",
                    (item_id,)
                )
                await database.commit()

            added.append({
                "id": item_id,
                "name": existing_item["name"],
                "category": existing_item["category"],
                "quantity": new_quantity_desc,
                "merged": True
            })

        else:
            # 没有找到相似食材，新增
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
                "quantity": item.get("quantity_desc", "一些"),
                "merged": False
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


async def _deduct_item_quantity(kit_item: Dict, requested_amount: Optional[float] = None) -> Dict:
    """
    扣减食材数量的内部辅助函数

    Args:
        kit_item: 库存食材
        requested_amount: 请求扣减的数量（可选）

    Returns:
        操作结果字典，包含 snapshot 和 action
    """
    item_id = kit_item["id"]

    # 保存修改前的完整快照
    snapshot = {
        "id": item_id,
        "name": kit_item["name"],
        "quantity_num": kit_item["quantity_num"],
        "quantity_desc": kit_item["quantity_desc"],
        "confidence": kit_item["confidence"],
        "is_active": kit_item.get("is_active", 1),
        "last_mentioned_at": kit_item["last_mentioned_at"]
    }

    # 如果有精确数量，优先扣减数量
    if kit_item["quantity_num"] is not None:
        old_quantity = kit_item["quantity_num"]
        deduct_amount = requested_amount if requested_amount else 1  # 默认扣减 1
        new_quantity = old_quantity - deduct_amount

        if new_quantity <= 0:
            # 数量耗尽，标记为不活跃
            await db.remove_item(item_id)
            action = "depleted"
            new_quantity = 0
        else:
            # 更新数量
            await db.update_item_quantity(item_id, quantity_num=new_quantity)
            action = "deducted"

        return {
            "snapshot": snapshot,
            "action": action,
            "old_quantity": old_quantity,
            "new_quantity": new_quantity
        }

    # 如果只有模糊描述，降级处理
    else:
        old_desc = kit_item["quantity_desc"]
        desc_hierarchy = ["充足", "一些", "快没了"]

        if old_desc in desc_hierarchy:
            current_index = desc_hierarchy.index(old_desc)
            if current_index < len(desc_hierarchy) - 1:
                # 降一级
                new_desc = desc_hierarchy[current_index + 1]
                await db.update_item_quantity(item_id, quantity_desc=new_desc)
                action = "downgraded"
            else:
                # 已经是"快没了"，标记为不活跃
                await db.remove_item(item_id)
                action = "depleted"
        else:
            # 未知描述，降为"快没了"
            await db.update_item_quantity(item_id, quantity_desc="快没了")
            action = "downgraded"
            old_desc = kit_item["quantity_desc"]
            new_desc = "快没了"

        return {
            "snapshot": snapshot,
            "action": action,
            "old_desc": old_desc,
            "new_desc": new_desc if action == "downgraded" else old_desc
        }


async def consume_items(
    reason: str,
    recipe_name: Optional[str] = None,
    recipe_names: Optional[List[str]] = None,
    items: Optional[List[Dict]] = None
) -> Dict:
    """
    标记食材被消耗（扣减数量而非直接删除）

    Args:
        reason: 消耗原因
        recipe_name: 兼容旧调用的单个菜谱名称
        recipe_names: 菜谱名称列表（如果一次做了多道菜）
        items: 手动指定的食材列表，可包含 amount 字段

    Returns:
        操作结果
    """
    consumed = []

    effective_recipe_names = [name for name in (recipe_names or []) if name]
    if recipe_name:
        effective_recipe_names.append(recipe_name)

    if effective_recipe_names:
        for current_recipe_name in effective_recipe_names:
            recipe = await resolve_recipe(current_recipe_name)
            if not recipe:
                continue

            for ingredient in recipe.get("ingredients", []):
                ing_name = ingredient.get("name")
                if not ing_name:
                    continue

                kitchen_items = await db.get_active_items()
                matched_items = find_similar_ingredients(ing_name, kitchen_items)
                if not matched_items:
                    continue

                kit_item = matched_items[0]
                requested_amount = ingredient.get("amount")
                if requested_amount and isinstance(requested_amount, (int, float)):
                    amount_num = float(requested_amount)
                else:
                    amount_num = None

                deduct_result = await _deduct_item_quantity(kit_item, amount_num)
                consumed.append({
                    "snapshot": deduct_result["snapshot"],
                    "name": kit_item["name"],
                    "amount": ingredient.get("amount", ""),
                    "action": deduct_result["action"],
                    "recipe_name": current_recipe_name
                })

    elif items:
        for item in items:
            name = item.get("name")
            if not name:
                continue

            kitchen_items = await db.get_active_items()
            matched_items = find_similar_ingredients(name, kitchen_items)
            if not matched_items:
                continue

            kit_item = matched_items[0]
            requested_amount = item.get("amount")
            if requested_amount and isinstance(requested_amount, (int, float)):
                amount_num = float(requested_amount)
            else:
                amount_num = None

            deduct_result = await _deduct_item_quantity(kit_item, amount_num)
            consumed.append({
                "snapshot": deduct_result["snapshot"],
                "name": kit_item["name"],
                "amount": item.get("amount", ""),
                "action": deduct_result["action"]
            })

    await db.log_action(
        action_type="consume",
        payload={
            "reason": reason,
            "recipe_name": recipe_name,
            "recipe_names": effective_recipe_names,
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
    max_results: int = 3,
    disliked_ingredients: Optional[List[str]] = None,
    dietary_goals: Optional[str] = None,
    exclude_recipes: Optional[List[str]] = None,
    meal_role: Optional[str] = None
) -> Dict:
    """根据库存和约束推荐菜品，优先返回当前可做或少量补货可做的菜。"""
    kitchen_state = await get_kitchen_state(min_confidence=0.3)
    available_items_list = kitchen_state["high_confidence"] + kitchen_state["medium_confidence"]

    normalized_inventory = {}
    for item in available_items_list:
        normalized_name = normalize_ingredient_name(item["name"])
        normalized_inventory[normalized_name] = (item["name"], item["effective_confidence"])

    max_time = None
    max_difficulty = None
    prefer_lowfat = False
    prefer_light = False

    if constraints:
        if "快手" in constraints or "简单" in constraints:
            max_time = 20
            max_difficulty = 2
        elif "复杂" not in constraints:
            max_difficulty = 3
        if any(token in constraints for token in ["减肥", "低脂", "低卡"]):
            prefer_lowfat = True
        if any(token in constraints for token in ["清淡", "少油", "解腻"]):
            prefer_light = True

    if dietary_goals:
        if any(token in dietary_goals for token in ["减肥", "低脂"]):
            prefer_lowfat = True
        if "清淡" in dietary_goals:
            prefer_light = True

    excluded = set(exclude_recipes or [])
    recipes = await db.search_recipes(max_difficulty=max_difficulty, max_time=max_time, limit=max_results * 8)

    high_fat_ingredients = ["猪肉", "五花肉", "牛肉", "羊肉", "培根", "香肠", "腊肉", "黄油", "奶油"]
    heavy_name_tokens = ["辣", "麻", "红烧", "炸", "酥", "啤酒"]
    light_name_tokens = ["清炒", "凉拌", "清蒸", "醋溜", "白灼"]
    side_dish_allowed = {"素菜", "荤菜", "水产"}

    scored_recipes = []
    for recipe in recipes:
        if recipe.get("name") in excluded:
            continue
        if meal_role == "side_dish" and recipe.get("category") not in side_dish_allowed:
            continue
        recipe_ingredients = recipe.get("ingredients", [])
        if not recipe_ingredients:
            continue

        # 过滤调味品，只保留核心食材用于匹配度计算
        core_ingredients = []
        for ing in recipe_ingredients:
            ing_name = ing.get("name", "")
            if not ing_name:
                continue
            # 使用 classify_ingredient 判断是否为调味品
            category = classify_ingredient(ing_name)
            if category != "调味品":
                core_ingredients.append(ing)

        # 如果菜谱没有核心食材（全是调味品），跳过
        if not core_ingredients:
            continue

        # 只用核心食材计算匹配度
        available_count = 0
        missing_ingredients = []
        for ing in core_ingredients:
            ing_name = ing.get("name", "")
            normalized_ing = normalize_ingredient_name(ing_name)
            matched = False
            for norm_inv_name, _inv in normalized_inventory.items():
                if normalized_ing == norm_inv_name or normalized_ing in norm_inv_name or norm_inv_name in normalized_ing:
                    matched = True
                    break
            if matched:
                available_count += 1
            else:
                missing_ingredients.append(ing_name)

        buckets = split_missing_ingredients(missing_ingredients)
        hard_missing = buckets['hard']
        pantry_missing = buckets['pantry']
        optional_missing = buckets['optional']
        # 匹配度分母改为核心食材数量
        match_rate = available_count / len(core_ingredients) if core_ingredients else 0
        score = match_rate

        if disliked_ingredients:
            has_disliked = any(any(disliked in ing.get("name", "") for disliked in disliked_ingredients) for ing in recipe_ingredients)
            if has_disliked:
                continue

        if not hard_missing:
            score += 0.45
        elif len(hard_missing) <= 2:
            score += 0.12
        else:
            score -= min(0.35, 0.08 * len(hard_missing))

        if prefer_lowfat:
            has_high_fat = any(any(fat in ing.get("name", "") for fat in high_fat_ingredients) for ing in recipe_ingredients)
            if has_high_fat:
                score -= 0.25
        if prefer_light and any(token in recipe.get("name", "") for token in heavy_name_tokens):
            score -= 0.18

        if meal_role == 'side_dish':
            if recipe.get('category') == '素菜':
                score += 0.18
            elif recipe.get('category') in {'水产', '荤菜'}:
                score += 0.06
            if any(token in recipe.get('name', '') for token in light_name_tokens):
                score += 0.12
            if any(token in recipe.get('name', '') for token in heavy_name_tokens):
                score -= 0.15

        payload = {
            'name': recipe['name'],
            'category': recipe['category'],
            'difficulty': recipe['difficulty'],
            'time_minutes': recipe['time_minutes'],
            'match_rate': round(match_rate * 100, 1),
            'missing_ingredients': missing_ingredients,
            'hard_missing': hard_missing,
            'pantry_missing': pantry_missing,
            'optional_missing': optional_missing,
            'score': round(score, 3),
        }
        scored_recipes.append(payload)

    scored_recipes.sort(key=lambda x: (x['score'], x['match_rate']), reverse=True)

    # 应用最低匹配度阈值过滤
    from config import MIN_MATCH_RATE
    min_threshold = MIN_MATCH_RATE * 100  # 转换为百分比
    filtered_recipes = [x for x in scored_recipes if x['match_rate'] >= min_threshold]

    # 如果过滤后没有任何菜，降级策略：返回最接近阈值的几道菜（只差 1-2 样关键食材）
    if not filtered_recipes:
        # 找出缺料最少的几道菜
        sorted_by_missing = sorted(scored_recipes, key=lambda x: len(x['hard_missing']))
        filtered_recipes = sorted_by_missing[:max_results]

    ready_now = [x for x in filtered_recipes if not x['hard_missing']]
    almost_ready = [x for x in filtered_recipes if x['hard_missing'] and len(x['hard_missing']) <= 2]
    shopping_needed = [x for x in filtered_recipes if len(x['hard_missing']) > 2]

    ready_now = ready_now[:max_results]
    remaining = max_results
    display = []
    for bucket in (ready_now, almost_ready, shopping_needed):
        for item in bucket:
            if len(display) >= max_results:
                break
            if item not in display:
                display.append(item)
        if len(display) >= max_results:
            break

    if ready_now:
        message = f"按当前库存，先给你 {len(ready_now)} 道基本能直接做的菜。"
    elif almost_ready:
        message = "按当前库存，暂时没有特别稳的现成菜；不过补 1-2 样关键食材就能做这些。"
    elif shopping_needed:
        if meal_role == 'side_dish':
            message = "按当前库存，适合搭配主菜的小菜暂时没有现成能做的，我给你列了几道补货后更合适的备选。"
        else:
            message = "按当前库存，暂时没有特别合适的现成菜，我给你列了几道补货后可做的备选。"
    else:
        message = "当前库存下没有明显合适的菜品推荐。"

    return {
        'success': True,
        'suggestions': display,
        'ready_now': ready_now,
        'almost_ready': [x for x in almost_ready if x not in ready_now][:max_results],
        'shopping_needed': [x for x in shopping_needed if x not in ready_now and x not in almost_ready][:max_results],
        'message': message,
    }


async def check_recipe_feasibility(
    recipe_name: str,
    focus_ingredients: Optional[List[str]] = None
) -> Dict:
    """检查某道菜当前是否可做，并区分关键缺料、基础调味和可选配料。"""
    recipe = await resolve_recipe(recipe_name)
    if not recipe:
        return {
            "success": False,
            "recipe_name": recipe_name,
            "message": f"没有找到菜谱：{recipe_name}"
        }

    kitchen_state = await get_kitchen_state(min_confidence=0.3)
    available_items_list = kitchen_state["high_confidence"] + kitchen_state["medium_confidence"]
    normalized_inventory = {}
    for item in available_items_list:
        normalized_inventory[normalize_ingredient_name(item["name"])] = item

    available_ingredients = []
    missing_ingredients = []
    for ing in recipe.get("ingredients", []):
        ing_name = ing.get("name", "")
        if not ing_name:
            continue
        normalized_ing = normalize_ingredient_name(ing_name)
        matched = None
        for inv_name, item in normalized_inventory.items():
            if normalized_ing == inv_name or normalized_ing in inv_name or inv_name in normalized_ing:
                matched = item
                break
        if matched:
            available_ingredients.append({
                "name": ing_name,
                "matched_item": matched["name"],
                "quantity_desc": matched.get("quantity_desc"),
            })
        else:
            missing_ingredients.append(ing_name)

    buckets = split_missing_ingredients(missing_ingredients)
    hard_missing = buckets['hard']
    pantry_missing = buckets['pantry']
    optional_missing = buckets['optional']

    focus_status = []
    for focus in (focus_ingredients or []):
        normalized_focus = normalize_ingredient_name(focus)
        matched = None
        for inv_name, item in normalized_inventory.items():
            if normalized_focus == inv_name or normalized_focus in inv_name or inv_name in normalized_focus:
                matched = item
                break
        focus_status.append({
            "name": focus,
            "available": bool(matched),
            "matched_item": matched["name"] if matched else None,
            "quantity_desc": matched.get("quantity_desc") if matched else None,
        })

    return {
        "success": True,
        "recipe_name": recipe.get('name', recipe_name),
        "can_cook": len(hard_missing) == 0,
        "can_cook_core_only": len(hard_missing) == 0,
        "available_ingredients": available_ingredients,
        "missing_ingredients": missing_ingredients,
        "hard_missing": hard_missing,
        "pantry_missing": pantry_missing,
        "optional_missing": optional_missing,
        "focus_ingredient_status": focus_status,
        "message": f"已检查 {recipe.get('name', recipe_name)} 的可行性"
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
            recipe = await resolve_recipe(meal_name)
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
        # 撤销消耗 = 从快照恢复食材状态
        for item in payload.get("items", []):
            snapshot = item.get("snapshot")
            if snapshot and snapshot.get("id"):
                # 使用快照完整恢复
                await db.restore_item_from_snapshot(snapshot["id"], snapshot)

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
