"""
Agent 测试: 意图路由和工具调度（Mock LLM）

测试 Agent 的意图分类和调度逻辑，无需真实 Ollama
"""
import pytest
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.agent import classify_intent, process_message


def test_intent_classification_add():
    """测试添加意图的分类"""
    test_cases = [
        ("买了鸡蛋", "add"),
        ("带了西红柿", "add"),
        ("冰箱里有白菜", "add"),
        ("囤了一些肉", "add"),
        ("补了点菜", "add"),
    ]

    for user_input, expected_intent in test_cases:
        intent, model_tier = classify_intent(user_input)
        assert intent == expected_intent, f"'{user_input}' 应该识别为 {expected_intent}"
        assert model_tier == "small"  # 添加是简单意图


def test_intent_classification_consume():
    """测试消耗意图的分类"""
    test_cases = [
        ("做了番茄炒蛋", "consume"),
        ("炒了个菜", "consume"),
        ("煮了面", "consume"),
        ("吃了鸡蛋", "consume"),
        ("用掉了西红柿", "consume"),
        ("扔了坏掉的白菜", "consume"),
    ]

    for user_input, expected_intent in test_cases:
        intent, model_tier = classify_intent(user_input)
        assert intent == expected_intent, f"'{user_input}' 应该识别为 {expected_intent}"
        assert model_tier == "small"  # 消耗是简单意图


def test_intent_classification_suggest():
    """测试推荐意图的分类"""
    test_cases = [
        ("今晚吃什么", "suggest"),
        ("今天做什么", "suggest"),
        ("推荐几道菜", "suggest"),
        ("想吃点清淡的", "suggest"),
        ("有什么菜可以做", "suggest"),
    ]

    for user_input, expected_intent in test_cases:
        intent, model_tier = classify_intent(user_input)
        assert intent == expected_intent, f"'{user_input}' 应该识别为 {expected_intent}"
        assert model_tier == "large"  # 推荐是复杂意图


def test_intent_classification_undo():
    """测试撤销意图的分类"""
    test_cases = [
        ("撤销", "undo"),
        ("撤回", "undo"),
        ("刚才搞错了", "undo"),
        ("取消上一步", "undo"),
    ]

    for user_input, expected_intent in test_cases:
        intent, model_tier = classify_intent(user_input)
        assert intent == expected_intent, f"'{user_input}' 应该识别为 {expected_intent}"
        assert model_tier == "small"


def test_intent_classification_query():
    """测试查询意图的分类"""
    test_cases = [
        ("冰箱里还有什么", "query"),
        ("家里还有多少菜", "query"),
        ("查看库存", "query"),
    ]

    for user_input, expected_intent in test_cases:
        intent, model_tier = classify_intent(user_input)
        assert intent == expected_intent, f"'{user_input}' 应该识别为 {expected_intent}"
        assert model_tier == "small"


def test_intent_classification_shopping():
    """测试购物意图的分类"""
    test_cases = [
        ("买什么", "shopping"),
        ("购物清单", "shopping"),
        ("需要采购什么", "shopping"),
        ("缺什么", "shopping"),
    ]

    for user_input, expected_intent in test_cases:
        intent, model_tier = classify_intent(user_input)
        assert intent == expected_intent, f"'{user_input}' 应该识别为 {expected_intent}"
        assert model_tier == "large"


def test_intent_classification_unknown():
    """测试无法识别的意图"""
    user_input = "这是一个完全无关的问题"
    intent, model_tier = classify_intent(user_input)
    assert intent == "unknown"
    assert model_tier == "large"  # 无法识别交给大模型


@pytest.mark.asyncio
@patch('backend.agent.chat_with_tools')
async def test_agent_process_with_mock_llm_add(mock_chat):
    """测试 Agent 处理添加意图（Mock LLM 响应）"""

    # Mock LLM 返回工具调用
    mock_chat.return_value = {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "add_items",
                    "arguments": '{"items": [{"name": "鸡蛋", "quantity_desc": "一些"}]}'
                }
            }]
        }
    }

    result = await process_message("买了鸡蛋")

    # 验证意图识别正确
    assert result["intent"] == "add"

    # 验证工具被调用
    assert len(result["tool_results"]) > 0
    assert result["tool_results"][0]["tool"] == "add_items"

    # 验证有回复消息
    assert "assistant_message" in result


@pytest.mark.asyncio
@patch('backend.agent.chat_with_tools')
async def test_agent_process_with_mock_llm_query(mock_chat):
    """测试 Agent 处理查询意图（Mock LLM 响应）"""

    # Mock LLM 返回工具调用
    mock_chat.return_value = {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "get_kitchen_state",
                    "arguments": '{}'
                }
            }]
        }
    }

    result = await process_message("冰箱里还有什么")

    assert result["intent"] == "query"
    assert len(result["tool_results"]) > 0
    assert result["tool_results"][0]["tool"] == "get_kitchen_state"


@pytest.mark.asyncio
@patch('backend.agent.chat_with_tools')
async def test_agent_process_without_tools(mock_chat):
    """测试 Agent 处理不需要工具的对话"""

    # Mock LLM 返回纯文本回复（无工具调用）
    mock_chat.return_value = {
        "message": {
            "content": "好的，我明白了"
        }
    }

    result = await process_message("你好")

    assert "assistant_message" in result
    assert result["assistant_message"] == "好的，我明白了"
    assert len(result["tool_results"]) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
