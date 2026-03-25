import asyncio
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import agent, tools, database as db


def unique_name(base: str) -> str:
    return f"{base}_{uuid.uuid4().hex[:6]}"


def run(coro):
    return asyncio.run(coro)


def test_delete_prefix_items(monkeypatch):
    prefix = unique_name('testbulk')
    keep_name = unique_name('keepitem')
    target1 = f'{prefix}_egg'
    target2 = f'{prefix}_potato'

    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent == 'delete':
            return {'mode': 'contains', 'keyword': prefix, 'predicate': None}
        return {}

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)

    run(tools.add_items([
        {'name': target1, 'quantity_num': 3},
        {'name': target2, 'quantity_desc': '一些'},
        {'name': keep_name, 'quantity_num': 2},
    ]))

    result = run(agent.process_message(f'库存里有一些{prefix}前缀的食物都给我删去'))

    assert result['intent'] == 'delete'
    assert '已经删除了 2 个食材' in result['assistant_message']

    active_items = run(db.get_active_items(min_confidence=0))
    active_names = {item['name'] for item in active_items}
    assert target1 not in active_names
    assert target2 not in active_names
    assert keep_name in active_names


def test_delete_no_match(monkeypatch):
    keyword = unique_name('nomatch')

    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent == 'delete':
            return {'mode': 'contains', 'keyword': keyword, 'predicate': None}
        return {}

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)

    result = run(agent.process_message(f'把{keyword}都删掉'))
    assert result['intent'] == 'delete'
    assert '没有找到' in result['assistant_message']


def test_delete_without_keyword(monkeypatch):
    async def fake_extract_intent_payload(intent, user_message, model_tier):
        if intent == 'delete':
            return {'mode': None, 'keyword': None, 'predicate': None}
        return {}

    monkeypatch.setattr(agent, 'extract_intent_payload', fake_extract_intent_payload)

    result = run(agent.process_message('请帮我删除'))
    assert result['intent'] == 'delete'
    assert '你想删除哪些食材呢' in result['assistant_message']
