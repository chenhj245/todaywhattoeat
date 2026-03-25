"""Agent 核心逻辑。

当前版本采用“规则判意图 + PydanticAI 结构化提取 + 显式 planner + 后端白名单执行”。
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import tools
from backend.llm import OLLAMA_LARGE_MODEL, OLLAMA_SMALL_MODEL, simple_chat
from backend.pydantic_agent import extract_structured_payload


DEFAULT_SESSION_STATE: Dict[str, Any] = {
    "last_suggestions": [],
    "last_main_dish": None,
    "last_meal_role": None,
    "last_servings": None,
    "last_recipe_discussed": None,
    "last_focus_ingredients": [],
    "last_tool_results": [],
}


def _new_session_state() -> Dict[str, Any]:
    return deepcopy(DEFAULT_SESSION_STATE)


def _ensure_session_state(session_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if session_state is None:
        return _new_session_state()
    for key, value in DEFAULT_SESSION_STATE.items():
        session_state.setdefault(key, deepcopy(value))
    return session_state


def _preview_text(text: str, limit: int = 200) -> str:
    text = (text or "").replace("\n", "\\n")
    return text[:limit] + ("..." if len(text) > limit else "")


def _wants_recipe_howto(text: str) -> bool:
    return bool(re.search(r"怎么做|做法|怎么弄|如何做|步骤|咋做", text))


def _wants_recipe_check(text: str) -> bool:
    return bool(re.search(r"能做吗|可以做吗|我能做吗|还有.+吗|没.+了吧|够不够|能不能做", text))


def _parse_nth_reference(text: str) -> Optional[int]:
    match = re.search(r"第([一二两三四五六七八九十\d])个", text)
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        idx = int(raw) - 1
    else:
        mapping = {"一": 0, "二": 1, "两": 1, "三": 2, "四": 3, "五": 4, "六": 5, "七": 6, "八": 7, "九": 8, "十": 9}
        idx = mapping.get(raw)
    return idx if idx is not None and idx >= 0 else None


async def _extract_recipe_for_howto(text: str) -> Optional[Dict[str, Any]]:
    candidates: List[str] = []
    patterns = [
        r"(?:买了|带了|拿了)([\u4e00-\u9fffA-Za-z0-9_]{2,12}).*?(?:怎么做|做法|怎么弄|如何做|咋做|知道)",  # "买了X，怎么做"
        r"(?:打算做|想做|做)([\u4e00-\u9fffA-Za-z0-9_]{2,12})",  # "想做X"
        r"([\u4e00-\u9fffA-Za-z0-9_]{2,12})(?:怎么做|做法|怎么弄|如何做|咋做)",  # "X怎么做"
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if match and match not in candidates and match not in ["你知道", "我知道", "知道"]:
                candidates.append(match)

    for candidate in candidates:
        recipe = await tools.resolve_recipe(candidate)
        if recipe:
            return recipe
    return None


def _format_recipe_howto(recipe: Dict[str, Any]) -> str:
    ingredients = recipe.get("ingredients", [])[:8]
    steps = recipe.get("steps", [])[:6]
    ingredient_text = "、".join([ing.get("name", "") for ing in ingredients if ing.get("name")]) or "见菜谱"
    lines = [f"{recipe['name']} 可以这样做：", f"食材：{ingredient_text}"]
    if steps:
        for idx, step in enumerate(steps, 1):
            if isinstance(step, dict):
                content = step.get("content") or step.get("text") or ""
            else:
                content = str(step)
            content = content.strip()
            if content:
                lines.append(f"{idx}. {content}")
    else:
        lines.append("这道菜目前没有完整步骤数据。")
    return "\n".join(lines)


def _format_recipe_check(result: Dict[str, Any]) -> str:
    recipe_name = result.get("recipe_name", "这道菜")
    hard_missing = result.get("hard_missing", [])
    pantry_missing = result.get("pantry_missing", [])
    optional_missing = result.get("optional_missing", [])
    focus = result.get("focus_ingredient_status", [])
    if not result.get("success"):
        return result.get("message", f"没有找到菜谱：{recipe_name}")

    lines = []
    if hard_missing:
        lines.append(f"{recipe_name} 现在还做不了。")
        lines.append(f"还缺关键食材：{'、'.join(hard_missing[:6])}")
    else:
        lines.append(f"{recipe_name} 基本可以做。")
        if pantry_missing:
            lines.append(f"主料基本够了，最好再确认基础调味：{'、'.join(pantry_missing[:6])}")
        if optional_missing:
            lines.append(f"这些可选配料没有也问题不大：{'、'.join(optional_missing[:6])}")

    for item in focus:
        if item.get("available"):
            qty = item.get("quantity_desc") or "有库存"
            lines.append(f"{item['name']} 目前有，状态是：{qty}。")
        else:
            lines.append(f"{item['name']} 目前没有。")

    if not focus and hard_missing:
        lines.append(f"缺的关键食材主要有：{'、'.join(hard_missing[:6])}")
    return "\n".join(lines)


def _collect_suggestion_names(result: Dict[str, Any], limit: int = 3) -> List[str]:
    names: List[str] = []
    for bucket in ("ready_now", "almost_ready", "shopping_needed", "suggestions"):
        for item in result.get(bucket, []) or []:
            name = item.get("name")
            if name and name not in names:
                names.append(name)
            if len(names) >= limit:
                return names
    return names


def _format_suggest_bucket(label: str, items: List[Dict[str, Any]]) -> List[str]:
    if not items:
        return []
    lines = [label]
    for item in items[:3]:
        match_rate = item.get('match_rate', 0)

        # 根据匹配度生成自然语言描述
        if match_rate >= 80:
            match_desc = "家里食材齐了，直接能做"
        elif match_rate >= 50:
            if item.get("hard_missing"):
                missing_str = "、".join(item['hard_missing'][:2])
                match_desc = f"大部分食材都有，只差{missing_str}"
            else:
                match_desc = "大部分食材都有"
        elif match_rate >= 20:
            if item.get("hard_missing"):
                missing_str = "、".join(item['hard_missing'][:3])
                match_desc = f"还差几样，需要买{missing_str}"
            else:
                match_desc = "还差几样食材"
        else:
            match_desc = "需要补充不少食材"

        lines.append(f"- {item['name']} —— {match_desc}")
    return lines


def _format_suggest_message(result: Dict[str, Any], servings: Optional[int], meal_role: Optional[str]) -> str:
    ready_now = result.get("ready_now", []) or []
    almost_ready = result.get("almost_ready", []) or []
    shopping_needed = result.get("shopping_needed", []) or []
    if not ready_now and not almost_ready and not shopping_needed:
        return result.get("message", "当前没有合适的推荐。")

    intro = "我先按库存和菜谱帮你筛了一轮"
    if servings:
        intro += f"，按 {servings} 个人吃饭来想"
    if meal_role == "side_dish":
        intro += "，偏搭配主菜的小菜"
    lines = [intro + "："]

    if ready_now:
        lines.extend(_format_suggest_bucket("现在就比较适合做的：", ready_now))
    elif almost_ready:
        lines.extend(_format_suggest_bucket("补 1-2 样关键食材就能做的：", almost_ready))
    else:
        lines.append("按当前库存，暂时没有特别稳的现成选择。")

    if almost_ready and ready_now:
        lines.extend(_format_suggest_bucket("如果愿意再补一点料，也可以考虑：", almost_ready[:2]))
    elif shopping_needed and not ready_now:
        lines.extend(_format_suggest_bucket("如果愿意采购一些，再考虑这些：", shopping_needed[:2]))

    return "\n".join(lines)


INTENT_PATTERNS = {
    "repair": [
        r"(并|似乎)?没(有)?(删|扣|更新)", r"没有从.*(删|扣)", r"不对劲", r"好像不对", r"似乎并没有"
    ],
    "delete": [
        r"删[掉除去]", r"清理", r"扔掉", r"移除", r"去掉", r"清除"
    ],
    "howto": [
        r"怎么做", r"做法", r"怎么弄", r"如何做", r"步骤", r"咋做"
    ],
    "recipe_check": [
        r"能做吗", r"可以做吗", r"我能做吗", r"还有.+吗", r"没.+了吧", r"够不够", r"能不能做"
    ],
    "query": [
        r"(冰箱|家)里(还)?有(什么|多少|哪些|几)", r"库存", r"查看", r"还剩", r"剩(什么|多少)"
    ],
    "add": [
        r"买了", r"带了", r"拿了", r"买回", r"带回", r"补了", r"囤了", r"(放|存)进(冰箱|家)"
    ],
    "consume": [
        r"做了", r"炒了", r"煮了", r"蒸了", r"烤了", r"吃了", r"吃掉", r"用了", r"用掉", r"坏了"
    ],
    "suggest": [
        r"吃什么", r"做什么", r"推荐", r"建议", r"今[天晚]", r"想吃", r"能做", r"有什么菜", r"帮我想",
        r"搭几个小菜", r"搭几个菜", r"配几个菜", r"小菜", r"几个人吃饭", r"不想吃"
    ],
    "shopping": [
        r"买什么", r"购物", r"采购", r"清单", r"缺什么", r"要买"
    ],
    "undo": [
        r"撤[回销]", r"取消", r"搞错"
    ]
}


def classify_intent(text: str) -> Tuple[str, str]:
    if any(re.search(pattern, text) for pattern in INTENT_PATTERNS["add"]) and _wants_recipe_howto(text):
        return "add", "small"

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                if intent in ("add", "consume", "delete", "undo", "query", "repair", "howto", "recipe_check"):
                    return intent, "small"
                return intent, "large"
    return "clarify", "small"


async def extract_preferences(text: str) -> Dict[str, Any]:
    result = {"disliked_ingredients": [], "dietary_goals": None}

    dislike_patterns = [
        r"不吃(\w+)",
        r"不喜欢(\w+)",
        r"不要(\w+)",
        r"讨厌(\w+)",
        r"过敏(\w+)"
    ]
    for pattern in dislike_patterns:
        matches = re.findall(pattern, text)
        for ingredient in matches:
            if ingredient and len(ingredient) <= 5:
                result["disliked_ingredients"].append(ingredient)

    if re.search(r"减肥|控重|瘦身", text):
        result["dietary_goals"] = "减肥"
    elif re.search(r"增肌|健身|练肌肉", text):
        result["dietary_goals"] = "增肌"
    elif re.search(r"控糖|少糖|降血糖", text):
        result["dietary_goals"] = "控糖"
    elif re.search(r"清淡|少油|低脂", text):
        result["dietary_goals"] = "清淡"

    return result


def _extract_names_fallback(text: str) -> List[str]:
    stop_words = {
        "我", "一些", "一点", "这个", "那个", "这些", "那些", "库存", "冰箱", "家里", "食材", "食物",
        "都", "给我", "帮我", "一下", "今天", "今晚", "晚餐", "早餐", "午餐", "什么", "还有", "买", "做",
        "除了", "总共", "几个", "小菜"
    }
    names = re.findall(r"[\u4e00-\u9fffA-Za-z_][\u4e00-\u9fffA-Za-z0-9_]{0,12}", text)
    cleaned = []
    for name in names:
        if name not in stop_words and not name.startswith("请") and len(name) >= 2:
            cleaned.append(name)
    return cleaned[:8]


def _extract_servings(text: str) -> Optional[int]:
    match = re.search(r"([一二两三四五六七八九十\d]+)个?人吃饭", text)
    if not match:
        return None
    raw = match.group(1)
    chinese_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if raw.isdigit():
        return int(raw)
    return chinese_map.get(raw)


def _fallback_payload(intent: str, user_message: str) -> Dict[str, Any]:
    if intent == "add":
        return {
            "items": [
                {"name": name, "quantity_num": None, "quantity_desc": "一些", "unit": None, "category": None}
                for name in _extract_names_fallback(user_message)
            ]
        }
    if intent == "consume":
        recipe_names = re.findall(r"做了([\u4e00-\u9fffA-Za-z0-9_、，,]{2,30})", user_message)
        extracted_recipe_names: List[str] = []
        if recipe_names:
            raw = recipe_names[0]
            extracted_recipe_names = [part.strip() for part in re.split(r"[、，,和]\s*", raw) if part.strip()]
        return {
            "reason": user_message,
            "recipe_names": extracted_recipe_names,
            "items": [{"name": name, "amount": None} for name in _extract_names_fallback(user_message)],
        }
    if intent == "delete":
        english_matches = re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)", user_message)
        if english_matches:
            keyword = sorted(set(english_matches), key=len)[0]
            return {"mode": "contains", "keyword": keyword, "predicate": None}
        if any(token in user_message for token in ["英文", "字母", "ASCII", "ascii", "非中文"]):
            return {"mode": "predicate", "keyword": None, "predicate": "contains_ascii"}
        if any(token in user_message for token in ["数字", "编号", "序号"]):
            return {"mode": "predicate", "keyword": None, "predicate": "contains_digit"}
        names = _extract_names_fallback(user_message)
        if names:
            return {"mode": "contains", "keyword": names[0], "predicate": None}
        return {"mode": None, "keyword": None, "predicate": None}
    if intent == "shopping":
        return {"planned_meals": _extract_names_fallback(user_message)}
    if intent == "query":
        return {"min_confidence": 0.1}
    if intent == "suggest":
        exclude_recipes = []
        if "除了" in user_message:
            matches = re.findall(r"除了([\u4e00-\u9fffA-Za-z0-9_]{2,12})", user_message)
            exclude_recipes = matches[:2]
        meal_role = "side_dish" if "小菜" in user_message else None
        return {
            "constraints": user_message,
            "max_results": 3,
            "exclude_recipes": exclude_recipes,
            "servings": _extract_servings(user_message),
            "meal_role": meal_role,
        }
    if intent == "howto":
        recipe_names = re.findall(r"([\u4e00-\u9fffA-Za-z0-9_]{2,12})(?:怎么做|做法|怎么弄|如何做|咋做)", user_message)
        if not recipe_names:
            recipe_names = re.findall(r"(?:做|想做)([\u4e00-\u9fffA-Za-z0-9_]{2,12})", user_message)
        return {"recipe_name": recipe_names[0] if recipe_names else ""}
    if intent == "recipe_check":
        recipe_names = re.findall(r"([\u4e00-\u9fffA-Za-z0-9_]{2,12})(?:能做吗|可以做吗|我能做吗|能不能做)", user_message)
        focus = re.findall(r"还有([\u4e00-\u9fffA-Za-z0-9_]{1,8})吗", user_message)
        return {"recipe_name": recipe_names[0] if recipe_names else (_extract_names_fallback(user_message)[0] if _extract_names_fallback(user_message) else ""), "focus_ingredients": focus}
    return {"message": "请补充更明确的操作目标。"}


async def extract_intent_payload(intent: str, user_message: str, model_tier: str) -> Dict[str, Any]:
    fallback_payload = _fallback_payload(intent, user_message)
    try:
        payload_model = await extract_structured_payload(intent, user_message, model_tier=model_tier)
        payload = payload_model.model_dump()
    except Exception as exc:
        print(f"[Agent] PydanticAI 提取失败 intent={intent} error={repr(exc)}", flush=True)
        payload = fallback_payload
    print(f"[Agent] 提取参数 intent={intent} payload={_preview_text(json.dumps(payload, ensure_ascii=False))}", flush=True)
    return payload


def _build_plan(intent: str, payload: Dict[str, Any], user_message: str, session_state: Dict[str, Any]) -> Dict[str, Any]:
    tool_plan: List[Dict[str, Any]] = []
    if intent == "suggest":
        tool_plan.append({"tool_name": "suggest_meals", "args": payload, "purpose": "按库存和约束推荐菜"})
    elif intent == "howto":
        tool_plan.append({"tool_name": "recipe_howto", "args": {"recipe_name": payload.get("recipe_name")}, "purpose": "查询菜谱步骤"})
        if _wants_recipe_check(user_message):
            tool_plan.append({"tool_name": "check_recipe_feasibility", "args": {"recipe_name": payload.get("recipe_name")}, "purpose": "顺带判断能不能做"})
    elif intent == "recipe_check":
        tool_plan.append({"tool_name": "check_recipe_feasibility", "args": payload, "purpose": "判断当前可行性"})
    elif intent == "query":
        tool_plan.append({"tool_name": "get_kitchen_state", "args": payload, "purpose": "查看库存"})
    elif intent == "delete":
        tool_plan.append({"tool_name": "delete_items", "args": payload, "purpose": "按条件删除库存"})
    elif intent == "add":
        tool_plan.append({"tool_name": "add_items", "args": payload, "purpose": "记录购买/添加的食材"})
        if _wants_recipe_howto(user_message):
            tool_plan.append({"tool_name": "recipe_howto", "args": {"recipe_name": None}, "purpose": "补充菜谱做法"})
    print(f"[Agent] planner intent={intent} tool_plan={_preview_text(json.dumps(tool_plan, ensure_ascii=False))}", flush=True)
    return {"intent": intent, "tool_plan": tool_plan}


def _merge_suggest_context(user_message: str, payload: Dict[str, Any], session_state: Dict[str, Any]) -> Dict[str, Any]:
    state = _ensure_session_state(session_state)
    merged = dict(payload)
    excludes = list(merged.get("exclude_recipes") or [])

    if re.search(r"这三[个道]|这几个|都不想吃|都不要", user_message):
        excludes.extend(state.get("last_suggestions", [])[:3])
    nth = _parse_nth_reference(user_message)
    if nth is not None:
        last_suggestions = state.get("last_suggestions", [])
        if nth < len(last_suggestions):
            excludes.append(last_suggestions[nth])

    if not merged.get("meal_role") and state.get("last_meal_role") and re.search(r"这三[个道]|都不想吃|第二个|第[一二两三四五六七八九十\d]个", user_message):
        merged["meal_role"] = state.get("last_meal_role")
    if not merged.get("servings") and state.get("last_servings") and re.search(r"这三[个道]|都不想吃|第二个|第[一二两三四五六七八九十\d]个", user_message):
        merged["servings"] = state.get("last_servings")
    if merged.get("meal_role") == "side_dish" and state.get("last_main_dish"):
        excludes.append(state["last_main_dish"])

    deduped = []
    for name in excludes:
        if name and name not in deduped:
            deduped.append(name)
    merged["exclude_recipes"] = deduped
    return merged


def _update_session_state(session_state: Dict[str, Any], intent: str, payload: Dict[str, Any], result: Dict[str, Any], user_message: str) -> None:
    state = _ensure_session_state(session_state)
    tool_results = result.get("tool_results", []) or []
    state["last_tool_results"] = tool_results[:3]

    if intent == "suggest":
        suggest_result = tool_results[0]["result"] if tool_results else {}
        state["last_suggestions"] = _collect_suggestion_names(suggest_result, limit=3)
        state["last_meal_role"] = payload.get("meal_role")
        state["last_servings"] = payload.get("servings")
        if payload.get("meal_role") == "side_dish":
            excludes = payload.get("exclude_recipes") or []
            if excludes:
                state["last_main_dish"] = excludes[0]
    elif intent in ("howto", "recipe_check"):
        recipe_name = payload.get("recipe_name")
        if tool_results:
            tool_recipe = tool_results[0].get("result", {}).get("recipe_name")
            recipe_name = tool_recipe or recipe_name
        if recipe_name:
            state["last_recipe_discussed"] = recipe_name
        if intent == "recipe_check":
            state["last_focus_ingredients"] = payload.get("focus_ingredients") or []
    elif intent == "add" and _wants_recipe_howto(user_message):
        for tool_result in tool_results:
            recipe_name = tool_result.get("result", {}).get("recipe_name")
            if recipe_name:
                state["last_recipe_discussed"] = recipe_name
                state["last_main_dish"] = recipe_name
                break


async def _handle_add(user_message: str, model: str, model_tier: str, session_state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = await extract_intent_payload("add", user_message, model_tier)
    _build_plan("add", payload, user_message, session_state)
    items = payload.get("items") or []
    safe_items = []
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        safe_items.append({
            "name": item.get("name"),
            "quantity_num": item.get("quantity_num"),
            "quantity_desc": item.get("quantity_desc") or "一些",
            "unit": item.get("unit"),
            "category": item.get("category"),
        })

    if not safe_items:
        return {"assistant_message": "我没提取到要添加的食材名称。", "tool_results": [], "intent": "add", "model_used": model}, payload

    result = await tools.add_items(safe_items)
    names = [x["name"] for x in result.get("items", [])]
    msg = f"好的，已记录 {', '.join(names[:5])}" if names else result.get("message", "已添加食材。")
    tool_results = [{"tool": "add_items", "result": result}]

    if _wants_recipe_howto(user_message):
        recipe = await _extract_recipe_for_howto(user_message)
        if recipe:
            msg = f"{msg}\n\n{_format_recipe_howto(recipe)}"
            tool_results.append({"tool": "recipe_howto", "result": {"recipe_name": recipe["name"]}})
            print(f"[Agent] 复合请求: add + howto recipe={recipe['name']}", flush=True)

    return {"assistant_message": msg, "tool_results": tool_results, "intent": "add", "model_used": model}, payload


async def _handle_consume(user_message: str, model: str, model_tier: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = await extract_intent_payload("consume", user_message, model_tier)
    reason = payload.get("reason") or user_message
    recipe_names = [x for x in (payload.get("recipe_names") or []) if isinstance(x, str) and x.strip()]
    items = payload.get("items") or []

    safe_items = []
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        safe_items.append({"name": item.get("name"), "amount": item.get("amount")})

    if not recipe_names and not safe_items:
        return {
            "assistant_message": "我没听清你做了哪些菜，或者用了哪些食材。",
            "tool_results": [],
            "intent": "consume",
            "model_used": model,
        }, payload

    result = await tools.consume_items(reason=reason, recipe_names=recipe_names or None, items=safe_items or None)
    return {"assistant_message": result.get("message", "已更新库存。"), "tool_results": [{"tool": "consume_items", "result": result}], "intent": "consume", "model_used": model}, payload


async def _handle_delete(user_message: str, model: str, model_tier: str, session_state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = await extract_intent_payload("delete", user_message, model_tier)
    _build_plan("delete", payload, user_message, session_state)
    mode = payload.get("mode")
    keyword = payload.get("keyword")
    predicate = payload.get("predicate")

    kitchen_state = await tools.get_kitchen_state(min_confidence=0.0)
    all_items: List[Dict[str, Any]] = []
    for group in ("high_confidence", "medium_confidence", "low_confidence"):
        all_items.extend(kitchen_state.get(group, []))

    matched = []
    for item in all_items:
        name = item.get("name", "")
        lowered = name.lower()
        if mode == "prefix" and keyword and lowered.startswith(str(keyword).lower()):
            matched.append(item)
        elif mode == "exact" and keyword and name == keyword:
            matched.append(item)
        elif mode == "contains" and keyword and str(keyword).lower() in lowered:
            matched.append(item)
        elif mode == "predicate" and predicate == "contains_ascii" and re.search(r"[A-Za-z]", name):
            matched.append(item)
        elif mode == "predicate" and predicate == "contains_digit" and re.search(r"\d", name):
            matched.append(item)

    if not mode:
        return {"assistant_message": "你想删除哪些食材呢？可以说名字、前缀，或者说带英文/带数字的。", "tool_results": [], "intent": "delete", "model_used": model}, payload
    if not matched:
        hint = keyword or ("带英文的" if predicate == "contains_ascii" else "带数字的" if predicate == "contains_digit" else "指定条件")
        return {"assistant_message": f"没有找到符合条件的食材：{hint}。", "tool_results": [], "intent": "delete", "model_used": model}, payload

    from backend import database as db_delete

    deleted_items = []
    for item in matched:
        full_item = await db_delete.get_item_by_id(item["id"])
        if not full_item:
            continue
        snapshot = {
            "id": full_item["id"],
            "name": full_item["name"],
            "quantity_num": full_item.get("quantity_num"),
            "quantity_desc": full_item.get("quantity_desc"),
            "confidence": full_item.get("confidence"),
            "is_active": full_item.get("is_active", 1),
            "last_mentioned_at": full_item.get("last_mentioned_at"),
        }
        await db_delete.remove_item(full_item["id"])
        deleted_items.append({"id": full_item["id"], "name": full_item["name"], "snapshot": snapshot, "action": "deleted"})

    await db_delete.log_action(
        action_type="consume",
        payload={"reason": f"用户请求删除: {user_message[:50]}", "recipe_names": [], "items": deleted_items},
        user_input=user_message,
    )
    deleted_names = [x["name"] for x in deleted_items]
    msg = f"好的，已经删除了 {len(deleted_names)} 个食材：{', '.join(deleted_names[:5])}"
    if len(deleted_names) > 5:
        msg += f" 等共 {len(deleted_names)} 个"
    result = {"success": True, "consumed_count": len(deleted_items), "items": deleted_items, "message": f"已删除 {len(deleted_items)} 种食材"}
    return {"assistant_message": msg, "tool_results": [{"tool": "delete_items", "result": result}], "intent": "delete", "model_used": model}, payload


async def _handle_query(user_message: str, model: str, model_tier: str, session_state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = await extract_intent_payload("query", user_message, model_tier)
    _build_plan("query", payload, user_message, session_state)
    min_confidence = payload.get("min_confidence", 0.1)
    try:
        min_confidence = float(min_confidence)
    except Exception:
        min_confidence = 0.1
    result = await tools.get_kitchen_state(min_confidence=min_confidence)
    msg = result.get("message", "这是当前库存。")
    return {"assistant_message": msg, "tool_results": [{"tool": "get_kitchen_state", "result": result}], "intent": "query", "model_used": model}, payload


async def _handle_shopping(user_message: str, model: str, model_tier: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = await extract_intent_payload("shopping", user_message, model_tier)
    planned_meals = [x for x in (payload.get("planned_meals") or []) if isinstance(x, str) and x]
    result = await tools.generate_shopping_list(planned_meals=planned_meals or None)
    fallback = result.get("message", "已生成购物清单。")
    if result.get("shopping_list"):
        names = [x["name"] for x in result["shopping_list"][:8]]
        fallback = f"我整理了一份购物清单：{', '.join(names)}"
    assistant_message = await simple_chat(
        f"用户问: {user_message}\n工具结果: {json.dumps(result, ensure_ascii=False)}\n请简洁口语化总结。",
        model=model,
        fallback_message=fallback,
    )
    return {"assistant_message": assistant_message, "tool_results": [{"tool": "generate_shopping_list", "result": result}], "intent": "shopping", "model_used": model}, payload


async def _handle_suggest(user_message: str, model: str, model_tier: str, session_state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    from backend import database as db

    payload = await extract_intent_payload("suggest", user_message, model_tier)
    payload = _merge_suggest_context(user_message, payload, session_state)
    _build_plan("suggest", payload, user_message, session_state)
    constraints = payload.get("constraints") or user_message
    max_results = payload.get("max_results", 3)
    exclude_recipes = [x for x in (payload.get("exclude_recipes") or []) if isinstance(x, str) and x]
    servings = payload.get("servings")
    meal_role = payload.get("meal_role")

    try:
        max_results = int(max_results)
    except Exception:
        max_results = 3

    disliked_pref = await db.get_preference("disliked_ingredients")
    dietary_pref = await db.get_preference("dietary_goals")
    disliked_ingredients = disliked_pref.get("value", []) if disliked_pref else []
    dietary_goals = dietary_pref.get("value") if dietary_pref else None
    result = await tools.suggest_meals(
        constraints=constraints,
        max_results=max_results,
        disliked_ingredients=disliked_ingredients,
        dietary_goals=dietary_goals,
        exclude_recipes=exclude_recipes or None,
        meal_role=meal_role,
    )
    assistant_message = _format_suggest_message(result, servings=servings, meal_role=meal_role)
    return {"assistant_message": assistant_message, "tool_results": [{"tool": "suggest_meals", "result": result}], "intent": "suggest", "model_used": model}, payload


async def _handle_howto(user_message: str, model: str, model_tier: str, session_state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = await extract_intent_payload("howto", user_message, model_tier)
    _build_plan("howto", payload, user_message, session_state)
    recipe_name = payload.get("recipe_name") or session_state.get("last_recipe_discussed") or ""
    recipe = await _extract_recipe_for_howto(user_message)
    if not recipe and recipe_name:
        recipe = await tools.resolve_recipe(recipe_name)
    if not recipe:
        return {"assistant_message": "我还没识别出你想问哪道菜的做法。", "tool_results": [], "intent": "howto", "model_used": model}, payload

    message = _format_recipe_howto(recipe)
    tool_results = [{"tool": "recipe_howto", "result": {"recipe_name": recipe["name"]}}]

    if _wants_recipe_check(user_message):
        check_result = await tools.check_recipe_feasibility(recipe["name"])
        message = f"{message}\n\n{_format_recipe_check(check_result)}"
        tool_results.append({"tool": "check_recipe_feasibility", "result": check_result})

    return {"assistant_message": message, "tool_results": tool_results, "intent": "howto", "model_used": model}, {"recipe_name": recipe["name"]}


async def _handle_recipe_check(user_message: str, model: str, model_tier: str, session_state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    payload = await extract_intent_payload("recipe_check", user_message, model_tier)
    recipe_name = payload.get("recipe_name") or session_state.get("last_recipe_discussed") or ""
    focus_ingredients = [x for x in (payload.get("focus_ingredients") or []) if isinstance(x, str) and x]
    if not recipe_name:
        recipe = await _extract_recipe_for_howto(user_message)
        recipe_name = recipe["name"] if recipe else ""
    if not recipe_name:
        return {"assistant_message": "我还没识别出你想确认哪道菜能不能做。", "tool_results": [], "intent": "recipe_check", "model_used": model}, payload

    plan_payload = {"recipe_name": recipe_name, "focus_ingredients": focus_ingredients}
    _build_plan("recipe_check", plan_payload, user_message, session_state)
    result = await tools.check_recipe_feasibility(recipe_name, focus_ingredients=focus_ingredients or None)
    return {
        "assistant_message": _format_recipe_check(result),
        "tool_results": [{"tool": "check_recipe_feasibility", "result": result}],
        "intent": "recipe_check",
        "model_used": model,
    }, plan_payload


async def _handle_repair(user_message: str, model: str, session_state: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    last_recipe = session_state.get("last_recipe_discussed")
    if last_recipe:
        message = f"我理解你是在指出上一步结果不对。刚才我们主要在聊 {last_recipe}。你可以直接说“重新检查这道菜能不能做”或“把这道菜扣库存”。"
    else:
        message = "我理解你是在指出上一步结果不对。请直接说具体要修正的动作，比如“把啤酒鸭和手撕包菜扣库存”或“撤销刚才的删除”。"
    return {"assistant_message": message, "tool_results": [], "intent": "repair", "model_used": model}, {}


async def _handle_clarify(model: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    message = "请直接告诉我要做什么，例如：买了什么、做了哪道菜、想查库存、想推荐菜、想问做法，或者想确认某道菜能不能做。"
    return {"assistant_message": message, "tool_results": [], "intent": "clarify", "model_used": model}, {}


async def process_message(
    user_message: str,
    conversation_history: Optional[list] = None,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    state = _ensure_session_state(session_state)
    intent, model_tier = classify_intent(user_message)
    model = OLLAMA_SMALL_MODEL if model_tier == "small" else OLLAMA_LARGE_MODEL
    print(f"[Agent] 意图: {intent}, 模型: {model}", flush=True)

    from backend import database as db_pref
    preferences = await extract_preferences(user_message)
    if preferences["disliked_ingredients"]:
        existing_pref = await db_pref.get_preference("disliked_ingredients")
        existing_list = existing_pref.get("value", []) if existing_pref else []
        merged_list = list(set(existing_list + preferences["disliked_ingredients"]))
        await db_pref.set_preference("disliked_ingredients", {"value": merged_list})
        print(f"[Agent] 更新不喜欢的食材: {merged_list}", flush=True)
    if preferences["dietary_goals"]:
        await db_pref.set_preference("dietary_goals", {"value": preferences["dietary_goals"]})
        print(f"[Agent] 更新饮食目标: {preferences['dietary_goals']}", flush=True)

    if intent == "add":
        result, payload = await _handle_add(user_message, model, model_tier, state)
    elif intent == "consume":
        result, payload = await _handle_consume(user_message, model, model_tier)
    elif intent == "delete":
        result, payload = await _handle_delete(user_message, model, model_tier, state)
    elif intent == "query":
        result, payload = await _handle_query(user_message, model, model_tier, state)
    elif intent == "shopping":
        result, payload = await _handle_shopping(user_message, model, model_tier)
    elif intent == "suggest":
        result, payload = await _handle_suggest(user_message, model, model_tier, state)
    elif intent == "howto":
        result, payload = await _handle_howto(user_message, model, model_tier, state)
    elif intent == "recipe_check":
        result, payload = await _handle_recipe_check(user_message, model, model_tier, state)
    elif intent == "undo":
        tool_result = await tools.undo_last_action()
        result = {"assistant_message": tool_result.get("message", "已撤销。"), "tool_results": [{"tool": "undo_last_action", "result": tool_result}], "intent": "undo", "model_used": model}
        payload = {}
    elif intent == "repair":
        result, payload = await _handle_repair(user_message, model, state)
    else:
        result, payload = await _handle_clarify(model)

    _update_session_state(state, intent, payload, result, user_message)
    result["session_state"] = deepcopy(state)

    if result.get("assistant_message"):
        print(f"[Agent] 最终回复: {_preview_text(result['assistant_message'])}", flush=True)
    return result


class KitchenMindAgent:
    def __init__(self):
        self.conversation_history: List[Dict[str, str]] = []
        self.session_state: Dict[str, Any] = _new_session_state()

    async def process(self, user_message: str) -> Dict[str, Any]:
        result = await process_message(
            user_message,
            conversation_history=self.conversation_history,
            session_state=self.session_state,
        )
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append({"role": "assistant", "content": result["assistant_message"]})
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
        if result.get("session_state"):
            self.session_state = result["session_state"]
        return result

    async def chat(self, user_message: str) -> str:
        result = await self.process(user_message)
        return result["assistant_message"]

    def clear_history(self):
        self.conversation_history = []
        self.session_state = _new_session_state()
