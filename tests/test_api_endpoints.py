"""
Week 3 API 端点测试

测试 FastAPI 后端的所有 REST API 端点
"""
import pytest
import httpx
import asyncio

# API 基础地址
API_BASE = "http://127.0.0.1:8888"


@pytest.mark.asyncio
async def test_health_check():
    """测试健康检查端点"""
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(f"{API_BASE}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_root_endpoint():
    """测试根路径端点"""
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(f"{API_BASE}/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "KitchenMind API"
        assert "endpoints" in data


@pytest.mark.asyncio
async def test_kitchen_state():
    """测试厨房状态端点"""
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(f"{API_BASE}/api/kitchen/state")
        assert response.status_code == 200
        data = response.json()

        # 验证数据结构
        assert data["success"] is True
        assert "total_items" in data
        assert isinstance(data["high_confidence"], list)
        assert isinstance(data["medium_confidence"], list)
        assert isinstance(data["low_confidence"], list)

        # 验证数据字段完整性
        if data["high_confidence"]:
            item = data["high_confidence"][0]
            assert "id" in item
            assert "name" in item
            assert "category" in item
            assert "quantity_desc" in item
            assert "effective_confidence" in item
            assert "last_mentioned_at" in item
            assert "source" in item
            assert "recommendation" in item


@pytest.mark.asyncio
async def test_shopping_list():
    """测试购物清单端点"""
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(f"{API_BASE}/api/shopping")
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert isinstance(data["shopping_list"], list)


@pytest.mark.asyncio
async def test_suggest_meals():
    """测试菜品推荐端点"""
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(f"{API_BASE}/api/suggest?max_results=5")
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert isinstance(data["suggestions"], list)

        # 验证推荐项的数据结构
        if data["suggestions"]:
            suggestion = data["suggestions"][0]
            assert "name" in suggestion
            assert "match_rate" in suggestion
            assert "missing_ingredients" in suggestion

            # 验证 match_rate 是百分比（0-100）
            assert 0 <= suggestion["match_rate"] <= 100


@pytest.mark.asyncio
async def test_chat_non_streaming():
    """测试非流式聊天端点"""
    async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
        response = await client.post(
            f"{API_BASE}/api/chat",
            json={
                "message": "冰箱里有什么",
                "stream": False
            }
        )
        assert response.status_code == 200
        data = response.json()

        assert "assistant_message" in data
        assert "intent" in data
        assert isinstance(data["assistant_message"], str)


@pytest.mark.asyncio
async def test_undo_no_action():
    """测试撤销（无操作时）"""
    async with httpx.AsyncClient(trust_env=False) as client:
        # 先清空所有 action_log（仅测试环境）
        response = await client.post(f"{API_BASE}/api/kitchen/undo")
        # 应该返回成功或者"没有可撤销的操作"
        assert response.status_code == 200
        data = response.json()
        assert "success" in data


@pytest.mark.asyncio
async def test_diet_constraint_suggest():
    """测试减肥约束的菜品推荐"""
    async with httpx.AsyncClient(trust_env=False, timeout=60.0) as client:
        response = await client.post(
            f"{API_BASE}/api/chat",
            json={
                "message": "今晚我可以吃点什么？我要减肥",
                "stream": False
            }
        )
        assert response.status_code == 200
        data = response.json()

        # 验证意图分类为 suggest
        assert data["intent"] == "suggest"

        # 验证有工具调用结果
        assert "tool_results" in data
        assert len(data["tool_results"]) > 0

        # 验证调用了 suggest_meals 工具
        tool_result = data["tool_results"][0]
        assert tool_result["tool"] == "suggest_meals"

        # 验证返回了推荐结果
        result = tool_result["result"]
        assert result["success"] is True
        assert isinstance(result["suggestions"], list)

        # 验证返回的是自然语言总结，而不是原始 JSON
        assistant_message = data["assistant_message"]
        assert isinstance(assistant_message, str)
        assert len(assistant_message) > 0
        # 不应该包含 JSON 结构的标志性字符串
        assert "\"success\"" not in assistant_message
        assert "\"suggestions\"" not in assistant_message

        print(f"\n✅ 意图分类: {data['intent']}")
        print(f"✅ 工具调用: {tool_result['tool']}")
        print(f"✅ 推荐菜品数: {len(result['suggestions'])}")
        print(f"✅ 自然语言回复: {assistant_message[:100]}...")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
