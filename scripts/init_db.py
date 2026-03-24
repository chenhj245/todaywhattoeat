#!/usr/bin/env python3
"""
初始化 KitchenMind 数据库表结构
"""
import asyncio
import aiosqlite
from pathlib import Path

# 数据库路径
DB_PATH = Path(__file__).parent.parent / "data" / "kitchenmind.db"

# 表结构 SQL
CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS kitchen_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT,
        quantity_desc TEXT DEFAULT '一些',
        quantity_num REAL,
        unit TEXT,
        added_at TEXT NOT NULL,
        last_mentioned_at TEXT NOT NULL,
        confidence REAL DEFAULT 1.0,
        source TEXT DEFAULT 'user_input',
        is_active INTEGER DEFAULT 1,
        meta TEXT DEFAULT '{}'
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS recipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        category TEXT,
        difficulty INTEGER,
        time_minutes INTEGER,
        flavor_tags TEXT DEFAULT '[]',
        ingredients TEXT NOT NULL,
        steps TEXT DEFAULT '[]',
        raw_markdown TEXT,
        source TEXT DEFAULT 'HowToCook'
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS action_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        payload TEXT NOT NULL,
        model_used TEXT,
        user_input TEXT,
        created_at TEXT NOT NULL,
        undone INTEGER DEFAULT 0
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """
]

# 索引
CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_kitchen_items_name ON kitchen_items(name)",
    "CREATE INDEX IF NOT EXISTS idx_kitchen_items_category ON kitchen_items(category)",
    "CREATE INDEX IF NOT EXISTS idx_kitchen_items_is_active ON kitchen_items(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_recipes_name ON recipes(name)",
    "CREATE INDEX IF NOT EXISTS idx_recipes_category ON recipes(category)",
    "CREATE INDEX IF NOT EXISTS idx_action_log_created_at ON action_log(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_action_log_action_type ON action_log(action_type)",
]

# 默认偏好数据
DEFAULT_PREFERENCES = [
    ("disliked_ingredients", "[]"),
    ("dietary_goals", '{"type": "", "notes": ""}'),
    ("cooking_time_preference", '{"weekday": 20, "weekend": 60}'),
    ("spice_tolerance", '"中等"'),
    ("household_size", "1"),
]


async def init_database():
    """初始化数据库"""
    # 确保 data 目录存在
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"初始化数据库: {DB_PATH}")

    async with aiosqlite.connect(DB_PATH) as db:
        # 创建表
        for sql in CREATE_TABLES_SQL:
            await db.execute(sql)
            print(f"✓ 创建表")

        # 创建索引
        for sql in CREATE_INDEXES_SQL:
            await db.execute(sql)
        print(f"✓ 创建索引 ({len(CREATE_INDEXES_SQL)} 个)")

        # 插入默认偏好（如果不存在）
        from datetime import datetime
        now = datetime.now().isoformat()

        for key, value in DEFAULT_PREFERENCES:
            await db.execute(
                """
                INSERT OR IGNORE INTO preferences (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, now)
            )

        await db.commit()
        print(f"✓ 插入默认偏好 ({len(DEFAULT_PREFERENCES)} 条)")

    print("\n数据库初始化完成！")
    print(f"数据库文件: {DB_PATH.absolute()}")


async def show_stats():
    """显示数据库统计信息"""
    async with aiosqlite.connect(DB_PATH) as db:
        print("\n=== 数据库统计 ===")

        # 统计各表记录数
        tables = ["kitchen_items", "recipes", "action_log", "preferences"]
        for table in tables:
            cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
            count = (await cursor.fetchone())[0]
            print(f"{table}: {count} 条记录")


if __name__ == "__main__":
    asyncio.run(init_database())
    asyncio.run(show_stats())
