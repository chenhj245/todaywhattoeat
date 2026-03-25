import asyncio
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import agent, database as db


def unique_name(base: str) -> str:
    return f"{base}_{uuid.uuid4().hex[:6]}"


def run(coro):
    return asyncio.run(coro)


def test_structured_add_query_delete_flow(monkeypatch):
    base = unique_name('flow')

    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent == 'add':
            return {
                'items': [
                    {'name': f'{base}_egg', 'quantity_num': None, 'quantity_desc': '一些', 'unit': None, 'category': None},
                    {'name': f'{base}_milk', 'quantity_num': None, 'quantity_desc': '一些', 'unit': None, 'category': None},
                ]
            }
        if intent == 'query':
            return {'min_confidence': 0.1}
        if intent == 'delete':
            return {'mode': 'contains', 'keyword': base, 'predicate': None}
        return {}

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)

    add_result = run(agent.process_message(f'我买了{base}_egg和{base}_milk'))
    assert add_result['intent'] == 'add'

    query_result = run(agent.process_message('冰箱里还有什么'))
    assert query_result['intent'] == 'query'

    delete_result = run(agent.process_message(f'把{base}都删掉'))
    assert delete_result['intent'] == 'delete'
    assert '已经删除了 2 个食材' in delete_result['assistant_message']

    active_items = run(db.get_active_items(min_confidence=0))
    active_names = {item['name'] for item in active_items}
    assert f'{base}_egg' not in active_names
    assert f'{base}_milk' not in active_names


def test_structured_consume(monkeypatch):
    base = unique_name('consume')

    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent == 'add':
            return {'items': [{'name': f'{base}_egg', 'quantity_num': 3, 'quantity_desc': None, 'unit': '个', 'category': None}]}
        if intent == 'consume':
            return {'reason': f'用了{base}_egg', 'recipe_names': [], 'items': [{'name': f'{base}_egg', 'amount': 1}]}
        return {}

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)

    add_result = run(agent.process_message(f'我买了{base}_egg'))
    item_id = add_result['tool_results'][0]['result']['items'][0]['id']
    result = run(agent.process_message(f'我用了{base}_egg'))
    assert result['intent'] == 'consume'
    item = run(db.get_item_by_id(item_id))
    assert item['quantity_num'] == 2


def test_structured_shopping(monkeypatch):
    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent == 'shopping':
            return {'planned_meals': ['番茄炒蛋']}
        return {}

    async def fake_simple_chat(user_message, system_prompt=None, model=None, fallback_message=None):
        return fallback_message or 'ok'

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)
    monkeypatch.setattr(agent, 'simple_chat', fake_simple_chat)

    result = run(agent.process_message('帮我列一个番茄炒蛋的购物清单'))
    assert result['intent'] == 'shopping'
    assert result['tool_results']


def test_add_with_recipe_howto(monkeypatch):
    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent == 'add':
            return {
                'items': [
                    {'name': '鸭子', 'quantity_num': 1, 'quantity_desc': None, 'unit': '只', 'category': '肉类'},
                    {'name': '啤酒', 'quantity_num': None, 'quantity_desc': '一些', 'unit': None, 'category': '其他'},
                ]
            }
        return {}

    async def fake_extract_recipe_for_howto(text):
        return {
            'name': '啤酒鸭',
            'ingredients': [{'name': '鸭子'}, {'name': '啤酒'}, {'name': '姜'}],
            'steps': ['鸭子焯水', '下锅翻炒', '倒入啤酒焖煮']
        }

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)
    monkeypatch.setattr(agent, '_extract_recipe_for_howto', fake_extract_recipe_for_howto)

    result = run(agent.process_message('今天晚上想吃好一些，我买了一只鸭子，买了啤酒，打算做啤酒鸭，你知道怎么做吗？'))
    assert result['intent'] == 'add'
    assert '好的，已记录 鸭子, 啤酒' in result['assistant_message']
    assert '啤酒鸭 可以这样做' in result['assistant_message']
    assert '1. 鸭子焯水' in result['assistant_message']


def test_howto_with_recipe_check(monkeypatch):
    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent == 'howto':
            return {'recipe_name': '蒲烧茄子'}
        return {}

    async def fake_extract_recipe_for_howto(text):
        return {
            'name': '蒲烧茄子',
            'ingredients': [{'name': '茄子'}, {'name': '酱油'}],
            'steps': ['茄子切片', '煎软后调味']
        }

    async def fake_check_recipe_feasibility(recipe_name, focus_ingredients=None):
        return {
            'success': True,
            'recipe_name': recipe_name,
            'can_cook': False,
            'hard_missing': ['茄子'],
            'pantry_missing': [],
            'optional_missing': [],
            'missing_ingredients': ['茄子'],
            'focus_ingredient_status': []
        }

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)
    monkeypatch.setattr(agent, '_extract_recipe_for_howto', fake_extract_recipe_for_howto)
    monkeypatch.setattr(agent.tools, 'check_recipe_feasibility', fake_check_recipe_feasibility)

    result = run(agent.process_message('蒲烧茄子怎么做？家里冰箱没茄子了吧？'))
    assert result['intent'] == 'howto'
    assert '蒲烧茄子 可以这样做' in result['assistant_message']
    assert '现在还做不了' in result['assistant_message']



def test_recipe_check_handler(monkeypatch):
    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent == 'recipe_check':
            return {'recipe_name': '西红柿炒蛋', 'focus_ingredients': ['鸡蛋']}
        return {}

    async def fake_check_recipe_feasibility(recipe_name, focus_ingredients=None):
        return {
            'success': True,
            'recipe_name': recipe_name,
            'can_cook': True,
            'hard_missing': [],
            'pantry_missing': ['食用油', '盐'],
            'optional_missing': ['葱花'],
            'missing_ingredients': ['食用油', '盐', '葱花（可选）'],
            'focus_ingredient_status': [
                {'name': '鸡蛋', 'available': True, 'quantity_desc': '一些'}
            ]
        }

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)
    monkeypatch.setattr(agent.tools, 'check_recipe_feasibility', fake_check_recipe_feasibility)

    result = run(agent.process_message('西红柿炒蛋我能做吗？家里还有鸡蛋吗？'))
    assert result['intent'] == 'recipe_check'
    assert '西红柿炒蛋 基本可以做' in result['assistant_message']
    assert '鸡蛋 目前有' in result['assistant_message']
    assert '现在还做不了' not in result['assistant_message']


def test_followup_suggest(monkeypatch):
    session_state = agent._new_session_state()

    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent != 'suggest':
            return {}
        if '都不想吃' in user_message:
            return {
                'constraints': user_message,
                'max_results': 3,
                'exclude_recipes': [],
                'servings': None,
                'meal_role': None,
            }
        return {
            'constraints': user_message,
            'max_results': 3,
            'exclude_recipes': ['啤酒鸭'],
            'servings': 3,
            'meal_role': 'side_dish',
        }

    async def fake_suggest_meals(constraints=None, max_results=3, disliked_ingredients=None, dietary_goals=None, exclude_recipes=None, meal_role=None):
        exclude_set = set(exclude_recipes or [])
        if {'手撕包菜', '西红柿炒鸡蛋', '凉拌黄瓜'}.issubset(exclude_set):
            return {
                'success': True,
                'ready_now': [
                    {'name': '醋溜土豆丝', 'match_rate': 80, 'hard_missing': [], 'pantry_missing': ['醋'], 'optional_missing': []},
                ],
                'almost_ready': [],
                'shopping_needed': [],
                'suggestions': [
                    {'name': '醋溜土豆丝', 'match_rate': 80, 'hard_missing': [], 'pantry_missing': ['醋'], 'optional_missing': []},
                ],
                'message': '重新推荐 1 道菜'
            }
        return {
            'success': True,
            'ready_now': [
                {'name': '手撕包菜', 'match_rate': 80, 'hard_missing': [], 'pantry_missing': [], 'optional_missing': []},
                {'name': '西红柿炒鸡蛋', 'match_rate': 70, 'hard_missing': [], 'pantry_missing': [], 'optional_missing': []},
                {'name': '凉拌黄瓜', 'match_rate': 65, 'hard_missing': [], 'pantry_missing': [], 'optional_missing': []},
            ],
            'almost_ready': [],
            'shopping_needed': [],
            'suggestions': [
                {'name': '手撕包菜', 'match_rate': 80, 'hard_missing': [], 'pantry_missing': [], 'optional_missing': []},
                {'name': '西红柿炒鸡蛋', 'match_rate': 70, 'hard_missing': [], 'pantry_missing': [], 'optional_missing': []},
                {'name': '凉拌黄瓜', 'match_rate': 65, 'hard_missing': [], 'pantry_missing': [], 'optional_missing': []},
            ],
            'message': '首轮推荐 3 道菜'
        }

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)
    monkeypatch.setattr(agent.tools, 'suggest_meals', fake_suggest_meals)

    first = run(agent.process_message('除了啤酒鸭，再给我搭几个小菜吧，总共三个人吃饭', session_state=session_state))
    assert first['intent'] == 'suggest'
    assert '手撕包菜' in first['assistant_message']
    session_state = first['session_state']

    second = run(agent.process_message('这三个我都不想吃', session_state=session_state))
    assert second['intent'] == 'suggest'
    assert '醋溜土豆丝' in second['assistant_message']
    assert '手撕包菜' not in second['assistant_message']
