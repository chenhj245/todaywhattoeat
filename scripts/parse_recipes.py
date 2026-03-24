#!/usr/bin/env python3
"""
解析 HowToCook 菜谱并导入数据库

分两步：
1. 规则解析：从 Markdown 提取结构化信息
2. 数据入库：将解析结果写入 SQLite
"""
import asyncio
import aiosqlite
import re
import json
from pathlib import Path
from typing import Dict, List, Optional

# 路径配置
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "kitchenmind.db"
RECIPES_PATH = PROJECT_ROOT / "data" / "howtocook" / "dishes"

# 分类映射
CATEGORY_MAP = {
    "vegetable_dish": "素菜",
    "meat_dish": "荤菜",
    "aquatic": "水产",
    "breakfast": "早餐",
    "staple": "主食",
    "soup": "汤粥",
    "dessert": "甜品",
    "drink": "饮料",
    "condiment": "调味品",
    "semi-finished": "半成品",
}


def parse_recipe_markdown(md_path: Path, category: str) -> Optional[Dict]:
    """
    解析单个菜谱 Markdown 文件

    返回结构:
    {
        "name": "番茄炒蛋",
        "category": "荤菜",
        "difficulty": 2,
        "time_minutes": 15,
        "flavor_tags": ["家常", "酸甜"],
        "ingredients": [
            {"name": "西红柿", "amount": "2", "unit": "个", "required": true},
            ...
        ],
        "steps": ["步骤1", "步骤2", ...],
        "raw_markdown": "原始内容..."
    }
    """
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"⚠ 无法读取 {md_path}: {e}")
        return None

    # 提取菜名（第一个 # 标题）
    name_match = re.search(r'^#\s+(.+?)的做法', content, re.MULTILINE)
    if not name_match:
        name_match = re.search(r'^#\s+(.+)', content, re.MULTILINE)

    if not name_match:
        print(f"⚠ 无法提取菜名: {md_path.name}")
        return None

    name = name_match.group(1).strip()

    # 提取难度
    difficulty = 2  # 默认
    difficulty_match = re.search(r'预估烹饪难度[：:]\s*(★+)', content)
    if difficulty_match:
        difficulty = len(difficulty_match.group(1))

    # 提取预估时间（简单推测，可以后续优化）
    time_minutes = 30  # 默认
    if difficulty <= 2:
        time_minutes = 20
    elif difficulty >= 4:
        time_minutes = 60

    # 提取食材（从"必备原料和工具"部分）
    # 注意：使用 (?=^##[^#]|\Z) 确保只匹配二级标题，不匹配 ### 三级标题
    ingredients = []
    ingredients_section = re.search(
        r'##\s*必备原料和工具\s*\n(.*?)(?=^##[^#]|\Z)',
        content,
        re.DOTALL | re.MULTILINE
    )

    if ingredients_section:
        lines = ingredients_section.group(1).strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('*') or line.startswith('-'):
                # 清理 Markdown 标记
                item = line.lstrip('*-').strip()
                # 简单解析 "食材名 数量单位"
                # 例如: "西红柿 2 个", "盐 适量", "鸡蛋"
                parts = item.split()
                if parts:
                    ing = {
                        "name": parts[0],
                        "amount": "",
                        "unit": "",
                        "required": True
                    }

                    # 尝试提取数量和单位
                    if len(parts) >= 2:
                        ing["amount"] = parts[1] if parts[1] not in ["适量", "少许"] else "适量"
                    if len(parts) >= 3:
                        ing["unit"] = parts[2]

                    ingredients.append(ing)

    # 如果没提取到食材，尝试从"计算"部分提取
    if not ingredients:
        calc_section = re.search(
            r'##\s*计算\s*\n(.*?)(?=^##[^#]|\Z)',
            content,
            re.DOTALL | re.MULTILINE
        )
        if calc_section:
            lines = calc_section.group(1).strip().split('\n')
            for line in lines:
                # 匹配 "食材 = 数量 单位 * 份数" 格式
                match = re.match(r'\*\s*(.+?)\s*=\s*([0-9.]+)\s*(\S+)', line)
                if match:
                    ingredients.append({
                        "name": match.group(1).strip(),
                        "amount": match.group(2),
                        "unit": match.group(3).replace('*', '').strip(),
                        "required": True
                    })

    # 提取步骤（从"操作"部分）
    steps = []
    steps_section = re.search(
        r'##\s*操作\s*\n(.*?)(?=^##[^#]|\Z)',
        content,
        re.DOTALL | re.MULTILINE
    )

    if steps_section:
        lines = steps_section.group(1).strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('*') or line.startswith('-'):
                step = line.lstrip('*-').strip()
                if step:
                    steps.append(step)

    # 简单推测风味标签（可以用 LLM 优化）
    flavor_tags = []
    if '辣' in content or '麻辣' in content:
        flavor_tags.append('辣')
    if '甜' in content or '糖' in content:
        flavor_tags.append('甜')
    if '酸' in content:
        flavor_tags.append('酸')
    if '家常' in content or category == '荤菜':
        flavor_tags.append('家常')

    return {
        "name": name,
        "category": category,
        "difficulty": difficulty,
        "time_minutes": time_minutes,
        "flavor_tags": flavor_tags,
        "ingredients": ingredients,
        "steps": steps,
        "raw_markdown": content
    }


async def import_recipe(db: aiosqlite.Connection, recipe: Dict) -> bool:
    """将单个菜谱导入数据库"""
    try:
        await db.execute(
            """
            INSERT OR REPLACE INTO recipes
            (name, category, difficulty, time_minutes, flavor_tags, ingredients, steps, raw_markdown, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recipe["name"],
                recipe["category"],
                recipe["difficulty"],
                recipe["time_minutes"],
                json.dumps(recipe["flavor_tags"], ensure_ascii=False),
                json.dumps(recipe["ingredients"], ensure_ascii=False),
                json.dumps(recipe["steps"], ensure_ascii=False),
                recipe["raw_markdown"],
                "HowToCook"
            )
        )
        return True
    except Exception as e:
        print(f"⚠ 导入失败 {recipe['name']}: {e}")
        return False


async def parse_and_import_all():
    """解析所有菜谱并导入数据库"""
    if not RECIPES_PATH.exists():
        print(f"❌ 菜谱目录不存在: {RECIPES_PATH}")
        print("请先克隆 HowToCook 仓库到 data/howtocook/")
        return

    print(f"开始解析菜谱...")
    print(f"菜谱目录: {RECIPES_PATH}")

    all_recipes = []
    seen_names = {}  # 记录已见过的菜名，用于检测重复

    # 遍历所有分类目录
    for dir_name, cn_category in CATEGORY_MAP.items():
        category_path = RECIPES_PATH / dir_name
        if not category_path.exists():
            continue

        # 查找所有 .md 文件
        md_files = list(category_path.glob("**/*.md"))
        print(f"\n{cn_category} ({dir_name}): 找到 {len(md_files)} 个菜谱")

        for md_file in md_files:
            recipe = parse_recipe_markdown(md_file, cn_category)
            if recipe:
                # 处理重名菜谱
                original_name = recipe['name']
                if original_name in seen_names:
                    # 添加后缀区分
                    counter = 2
                    new_name = f"{original_name} (版本{counter})"
                    while new_name in seen_names:
                        counter += 1
                        new_name = f"{original_name} (版本{counter})"

                    print(f"  ⚠ 发现重名菜谱: {original_name}")
                    print(f"    第一个: {seen_names[original_name]}")
                    print(f"    当前: {md_file}")
                    print(f"    重命名为: {new_name}")
                    recipe['name'] = new_name

                seen_names[recipe['name']] = str(md_file)
                all_recipes.append(recipe)
                print(f"  ✓ {recipe['name']}")
            else:
                print(f"  ✗ {md_file.name}")

    print(f"\n解析完成，共 {len(all_recipes)} 道菜谱")

    # 导入数据库
    print(f"\n开始导入数据库...")
    async with aiosqlite.connect(DB_PATH) as db:
        success_count = 0
        for recipe in all_recipes:
            if await import_recipe(db, recipe):
                success_count += 1

        await db.commit()
        print(f"✓ 成功导入 {success_count}/{len(all_recipes)} 道菜谱")

    # 显示统计和数据完整性验证
    print("\n=== 导入统计 ===")
    async with aiosqlite.connect(DB_PATH) as db:
        for cn_category in set(CATEGORY_MAP.values()):
            cursor = await db.execute(
                "SELECT COUNT(*) FROM recipes WHERE category = ?",
                (cn_category,)
            )
            count = (await cursor.fetchone())[0]
            if count > 0:
                print(f"{cn_category}: {count} 道")

        # 数据完整性验证
        print("\n=== 数据完整性验证 ===")

        # 检查总数
        cursor = await db.execute("SELECT COUNT(*) FROM recipes")
        total_count = (await cursor.fetchone())[0]
        print(f"数据库总记录数: {total_count}")
        print(f"解析到的菜谱数: {len(all_recipes)}")
        if total_count != len(all_recipes):
            print(f"⚠ 警告: 数据库记录数与解析数不一致！")

        # 检查缺失食材的菜谱
        cursor = await db.execute(
            "SELECT name FROM recipes WHERE ingredients = '[]'"
        )
        no_ingredients = await cursor.fetchall()
        if no_ingredients:
            print(f"⚠ {len(no_ingredients)} 道菜谱缺少食材信息:")
            for (name,) in no_ingredients[:5]:  # 只显示前5个
                print(f"  - {name}")
            if len(no_ingredients) > 5:
                print(f"  ... 等 {len(no_ingredients)} 道")
        else:
            print(f"✓ 所有菜谱都有食材信息")

        # 检查缺失步骤的菜谱
        cursor = await db.execute(
            "SELECT name FROM recipes WHERE steps = '[]'"
        )
        no_steps = await cursor.fetchall()
        if no_steps:
            print(f"⚠ {len(no_steps)} 道菜谱缺少步骤信息:")
            for (name,) in no_steps[:5]:
                print(f"  - {name}")
            if len(no_steps) > 5:
                print(f"  ... 等 {len(no_steps)} 道")
        else:
            print(f"✓ 所有菜谱都有步骤信息")

    print("\n菜谱导入完成！")


if __name__ == "__main__":
    asyncio.run(parse_and_import_all())
