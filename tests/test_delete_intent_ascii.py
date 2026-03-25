import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import agent


def run(coro):
    return asyncio.run(coro)


def test_delete_non_chinese_fallback():
    payload = agent._fallback_payload('delete', '删去冰箱中那些非中文的食材')
    assert payload == {'mode': 'predicate', 'keyword': None, 'predicate': 'contains_ascii'}
