#!/usr/bin/env python3
"""
查看数据库内容的辅助脚本
"""
import asyncio
import aiosqlite
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "kitchenmind.db"


async def show_sample_recipes():
    """显示几道菜谱样例"""
    async with aiosqlite.connect(DB_PATH) as db:
        print("=== 菜谱样例 ===\n")

        # 随机取几道不同分类的菜
        categories = ["素菜", "荤菜", "主食"]
        for category in categories:
            print(f"【{category}】")
            cursor = await db.execute(
                """
                SELECT name, difficulty, time_minutes, ingredients
                FROM recipes
                WHERE category = ?
                LIMIT 2
                """,
                (category,)
            )
            rows = await cursor.fetchall()

            for name, difficulty, time_minutes, ingredients_json in rows:
                ingredients = json.loads(ingredients_json)
                print(f"\n菜名: {name}")
                print(f"难度: {'★' * difficulty}")
                print(f"时间: {time_minutes} 分钟")
                print(f"食材: {len(ingredients)} 种")
                for ing in ingredients[:3]:  # 只显示前3个
                    print(f"  - {ing['name']} {ing.get('amount', '')} {ing.get('unit', '')}")
                if len(ingredients) > 3:
                    print(f"  - ... 等 {len(ingredients)} 种食材")

            print()


async def show_preferences():
    """显示用户偏好设置"""
    async with aiosqlite.connect(DB_PATH) as db:
        print("\n=== 用户偏好 ===\n")
        cursor = await db.execute("SELECT key, value FROM preferences")
        rows = await cursor.fetchall()

        for key, value in rows:
            print(f"{key}: {value}")


if __name__ == "__main__":
    asyncio.run(show_sample_recipes())
    asyncio.run(show_preferences())
