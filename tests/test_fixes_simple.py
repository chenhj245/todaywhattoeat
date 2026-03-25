"""
简化测试：只测试核心功能，避免数据库污染问题
"""
import pytest
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import tools, database as db


def unique_name(base: str) -> str:
    return f"{base}_{uuid.uuid4().hex[:6]}"


@pytest.mark.asyncio
async def test_consume_deduction():
    """测试consume扣减而非删除"""
    name = unique_name("test_egg")
    
    # 添加10个
    r = await tools.add_items([{"name": name, "quantity_num": 10}])
    item_id = r["items"][0]["id"]
    
    # 消耗2个
    await tools.consume_items(reason="test", items=[{"name": name, "amount": 2}])
    
    # 验证剩8个
    item = await db.get_item_by_id(item_id)
    assert item["quantity_num"] == 8
    assert item["is_active"] == 1
    print("✓ Consume扣减成功")


@pytest.mark.asyncio
async def test_add_merge():
    """测试重复添加会合并"""
    name = unique_name("test_potato")
    
    # 第一次添加
    r1 = await tools.add_items([{"name": name, "quantity_num": 3}])
    id1 = r1["items"][0]["id"]
    
    # 第二次添加
    r2 = await tools.add_items([{"name": name, "quantity_num": 2}])
    id2 = r2["items"][0]["id"]
    
    # 应该是同一个ID且数量是5
    assert id1 == id2
    item = await db.get_item_by_id(id1)
    assert item["quantity_num"] == 5
    print("✓ Add合并成功")


@pytest.mark.asyncio  
async def test_undo_consume():
    """测试撤销consume能恢复"""
    name = unique_name("test_apple")
    
    # 添加5个
    r = await tools.add_items([{"name": name, "quantity_num": 5}])
    item_id = r["items"][0]["id"]
    
    # 消耗2个
    await tools.consume_items(reason="test", items=[{"name": name, "amount": 2}])
    
    # 撤销
    await tools.undo_last_action()
    
    # 验证恢复到5个
    item = await db.get_item_by_id(item_id)
    assert item["quantity_num"] == 5
    print("✓ Undo成功")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
