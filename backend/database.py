"""
数据库操作封装

异步 SQLite 操作的辅助函数
"""
import aiosqlite
import json
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

# 导入配置
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH


def get_db():
    """获取数据库连接（返回可 await 的连接对象）"""
    return aiosqlite.connect(DB_PATH)


# ========== Kitchen Items 操作 ==========

async def add_kitchen_item(
    name: str,
    category: str = "其他",
    quantity_desc: str = "一些",
    quantity_num: Optional[float] = None,
    unit: Optional[str] = None,
    confidence: float = 1.0,
    source: str = "user_input"
) -> int:
    """
    添加食材到厨房库存

    Returns:
        新插入记录的 ID
    """
    now = datetime.now().isoformat()

    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO kitchen_items
            (name, category, quantity_desc, quantity_num, unit, added_at, last_mentioned_at, confidence, source, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (name, category, quantity_desc, quantity_num, unit, now, now, confidence, source)
        )
        await db.commit()
        return cursor.lastrowid


async def get_active_items(min_confidence: float = 0.1) -> List[Dict]:
    """
    获取所有活跃的食材

    Args:
        min_confidence: 最低基础置信度（不考虑时间衰减）

    Returns:
        食材列表
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, name, category, quantity_desc, quantity_num, unit,
                   added_at, last_mentioned_at, confidence, source, meta
            FROM kitchen_items
            WHERE is_active = 1 AND confidence >= ?
            ORDER BY last_mentioned_at DESC
            """,
            (min_confidence,)
        )
        rows = await cursor.fetchall()

    items = []
    for row in rows:
        items.append({
            "id": row[0],
            "name": row[1],
            "category": row[2],
            "quantity_desc": row[3],
            "quantity_num": row[4],
            "unit": row[5],
            "added_at": row[6],
            "last_mentioned_at": row[7],
            "confidence": row[8],
            "source": row[9],
            "meta": json.loads(row[10]) if row[10] else {}
        })

    return items


async def update_item_mentioned(item_id: int):
    """更新食材的最后提及时间"""
    now = datetime.now().isoformat()

    async with get_db() as db:
        await db.execute(
            "UPDATE kitchen_items SET last_mentioned_at = ? WHERE id = ?",
            (now, item_id)
        )
        await db.commit()


async def remove_item(item_id: int):
    """软删除食材（标记为不活跃）"""
    async with get_db() as db:
        await db.execute(
            "UPDATE kitchen_items SET is_active = 0 WHERE id = ?",
            (item_id,)
        )
        await db.commit()


async def restore_item(item_id: int):
    """恢复已删除的食材（撤销软删除）"""
    async with get_db() as db:
        await db.execute(
            "UPDATE kitchen_items SET is_active = 1 WHERE id = ?",
            (item_id,)
        )
        await db.commit()


async def get_item_by_id(item_id: int) -> Optional[Dict]:
    """根据 ID 获取食材（包括非活跃的）"""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, name, category, quantity_desc, quantity_num, unit,
                   added_at, last_mentioned_at, confidence, source, is_active, meta
            FROM kitchen_items
            WHERE id = ?
            """,
            (item_id,)
        )
        row = await cursor.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "category": row[2],
        "quantity_desc": row[3],
        "quantity_num": row[4],
        "unit": row[5],
        "added_at": row[6],
        "last_mentioned_at": row[7],
        "confidence": row[8],
        "source": row[9],
        "is_active": row[10],
        "meta": json.loads(row[11]) if row[11] else {}
    }


async def update_item_quantity(
    item_id: int,
    quantity_num: Optional[float] = None,
    quantity_desc: Optional[str] = None
):
    """更新食材数量"""
    now = datetime.now().isoformat()

    async with get_db() as db:
        if quantity_num is not None and quantity_desc is not None:
            await db.execute(
                """UPDATE kitchen_items
                   SET quantity_num = ?, quantity_desc = ?, last_mentioned_at = ?
                   WHERE id = ?""",
                (quantity_num, quantity_desc, now, item_id)
            )
        elif quantity_num is not None:
            await db.execute(
                """UPDATE kitchen_items
                   SET quantity_num = ?, last_mentioned_at = ?
                   WHERE id = ?""",
                (quantity_num, now, item_id)
            )
        elif quantity_desc is not None:
            await db.execute(
                """UPDATE kitchen_items
                   SET quantity_desc = ?, last_mentioned_at = ?
                   WHERE id = ?""",
                (quantity_desc, now, item_id)
            )
        await db.commit()


async def restore_item_from_snapshot(item_id: int, snapshot: Dict):
    """从快照恢复食材完整状态"""
    async with get_db() as db:
        await db.execute(
            """
            UPDATE kitchen_items
            SET quantity_num = ?,
                quantity_desc = ?,
                confidence = ?,
                is_active = ?,
                last_mentioned_at = ?
            WHERE id = ?
            """,
            (
                snapshot.get("quantity_num"),
                snapshot.get("quantity_desc"),
                snapshot.get("confidence"),
                snapshot.get("is_active", 1),
                snapshot.get("last_mentioned_at"),
                item_id
            )
        )
        await db.commit()


# ========== Recipes 操作 ==========

async def get_recipe_by_name(name: str) -> Optional[Dict]:
    """根据菜名查找菜谱"""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, name, category, difficulty, time_minutes, flavor_tags, ingredients, steps
            FROM recipes
            WHERE name = ?
            """,
            (name,)
        )
        row = await cursor.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "category": row[2],
        "difficulty": row[3],
        "time_minutes": row[4],
        "flavor_tags": json.loads(row[5]) if row[5] else [],
        "ingredients": json.loads(row[6]) if row[6] else [],
        "steps": json.loads(row[7]) if row[7] else []
    }


async def search_recipes(
    categories: Optional[List[str]] = None,
    max_difficulty: Optional[int] = None,
    max_time: Optional[int] = None,
    limit: int = 10
) -> List[Dict]:
    """
    搜索菜谱

    Args:
        categories: 分类列表（如 ["素菜", "荤菜"]）
        max_difficulty: 最大难度
        max_time: 最大时间（分钟）
        limit: 最多返回数量

    Returns:
        菜谱列表
    """
    query = "SELECT id, name, category, difficulty, time_minutes, flavor_tags, ingredients FROM recipes WHERE 1=1"
    params = []

    if categories:
        placeholders = ','.join('?' * len(categories))
        query += f" AND category IN ({placeholders})"
        params.extend(categories)

    if max_difficulty is not None:
        query += " AND difficulty <= ?"
        params.append(max_difficulty)

    if max_time is not None:
        query += " AND time_minutes <= ?"
        params.append(max_time)

    query += f" LIMIT {limit}"

    async with get_db() as db:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    recipes = []
    for row in rows:
        recipes.append({
            "id": row[0],
            "name": row[1],
            "category": row[2],
            "difficulty": row[3],
            "time_minutes": row[4],
            "flavor_tags": json.loads(row[5]) if row[5] else [],
            "ingredients": json.loads(row[6]) if row[6] else []
        })

    return recipes


# ========== Action Log 操作 ==========

async def log_action(
    action_type: str,
    payload: Dict,
    model_used: Optional[str] = None,
    user_input: Optional[str] = None
) -> int:
    """
    记录操作日志

    Returns:
        日志 ID
    """
    now = datetime.now().isoformat()

    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO action_log (action_type, payload, model_used, user_input, created_at, undone)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (action_type, json.dumps(payload, ensure_ascii=False), model_used, user_input, now)
        )
        await db.commit()
        return cursor.lastrowid


async def get_last_action() -> Optional[Dict]:
    """获取最后一次操作"""
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, action_type, payload, created_at, undone
            FROM action_log
            WHERE undone = 0
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "action_type": row[1],
        "payload": json.loads(row[2]),
        "created_at": row[3],
        "undone": row[4]
    }


async def mark_action_undone(action_id: int):
    """标记操作为已撤销"""
    async with get_db() as db:
        await db.execute(
            "UPDATE action_log SET undone = 1 WHERE id = ?",
            (action_id,)
        )
        await db.commit()


# ========== Preferences 操作 ==========

async def get_preference(key: str) -> Optional[Dict]:
    """获取用户偏好"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT value FROM preferences WHERE key = ?",
            (key,)
        )
        row = await cursor.fetchone()

    if not row:
        return None

    return json.loads(row[0])


async def set_preference(key: str, value: Dict):
    """设置用户偏好"""
    now = datetime.now().isoformat()
    value_json = json.dumps(value, ensure_ascii=False)

    async with get_db() as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO preferences (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (key, value_json, now)
        )
        await db.commit()
