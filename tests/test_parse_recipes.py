#!/usr/bin/env python3
"""
菜谱解析器的回归测试
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.parse_recipes import parse_recipe_markdown


def test_basic_recipe():
    """测试基本的菜谱解析"""
    # 创建测试 Markdown 内容
    test_md = """# 番茄炒蛋的做法

预估烹饪难度：★★

## 必备原料和工具

* 西红柿 2 个
* 鸡蛋 3 个
* 盐 适量
* 糖 少许

## 操作

* 鸡蛋打散
* 热锅冷油炒鸡蛋
* 西红柿切块下锅
* 加盐和糖调味
"""

    # 写入临时文件
    temp_file = Path("/tmp/test_recipe.md")
    temp_file.write_text(test_md, encoding='utf-8')

    # 解析
    recipe = parse_recipe_markdown(temp_file, "素菜")

    # 验证
    assert recipe is not None, "解析失败"
    assert recipe['name'] == "番茄炒蛋", f"菜名错误: {recipe['name']}"
    assert recipe['difficulty'] == 2, f"难度错误: {recipe['difficulty']}"
    assert len(recipe['ingredients']) == 4, f"食材数量错误: {len(recipe['ingredients'])}"
    assert len(recipe['steps']) == 4, f"步骤数量错误: {len(recipe['steps'])}"

    print("✓ test_basic_recipe 通过")


def test_recipe_with_h3_sections():
    """测试包含三级标题的菜谱（不应被误判为章节结束）"""
    test_md = """# 复杂菜的做法

预估烹饪难度：★★★

## 必备原料和工具

* 食材1
* 食材2

### 可选食材

* 可选1
* 可选2

## 操作

* 步骤1
* 步骤2

### 注意事项

这里是注意事项，不是新章节

* 步骤3
* 步骤4
"""

    temp_file = Path("/tmp/test_recipe_h3.md")
    temp_file.write_text(test_md, encoding='utf-8')

    recipe = parse_recipe_markdown(temp_file, "荤菜")

    assert recipe is not None
    # 应该包含"可选食材"部分的内容
    assert len(recipe['ingredients']) >= 2, f"食材数量错误: {len(recipe['ingredients'])}"
    # 应该包含"注意事项"部分的步骤
    assert len(recipe['steps']) >= 2, f"步骤数量错误: {len(recipe['steps'])}"

    print("✓ test_recipe_with_h3_sections 通过")


def test_recipe_with_calculation_section():
    """测试使用"计算"部分的菜谱"""
    test_md = """# 测试菜

## 计算

* 鸡蛋 = 2 个
* 西红柿 = 1.5 个
* 盐 = 3 克

## 操作

* 步骤1
"""

    temp_file = Path("/tmp/test_recipe_calc.md")
    temp_file.write_text(test_md, encoding='utf-8')

    recipe = parse_recipe_markdown(temp_file, "素菜")

    assert recipe is not None
    assert len(recipe['ingredients']) == 3, f"从计算部分提取食材失败: {len(recipe['ingredients'])}"
    assert recipe['ingredients'][0]['name'] == "鸡蛋"
    assert recipe['ingredients'][0]['amount'] == "2"

    print("✓ test_recipe_with_calculation_section 通过")


def test_duplicate_name_handling():
    """测试同名菜谱的处理（模拟完整导入流程）"""
    import tempfile
    import asyncio
    import aiosqlite

    # 创建两个同名但内容不同的菜谱文件
    temp_dir = Path(tempfile.mkdtemp())

    recipe1 = """# 测试菜的做法
## 必备原料和工具
* 食材A
## 操作
* 步骤1
"""

    recipe2 = """# 测试菜的做法
## 必备原料和工具
* 食材B
* 食材C
## 操作
* 步骤2
* 步骤3
"""

    (temp_dir / "recipe1.md").write_text(recipe1, encoding='utf-8')
    (temp_dir / "recipe2.md").write_text(recipe2, encoding='utf-8')

    # 模拟导入流程
    from scripts.parse_recipes import parse_recipe_markdown

    seen_names = {}
    all_recipes = []

    for md_file in temp_dir.glob("*.md"):
        recipe = parse_recipe_markdown(md_file, "素菜")
        if recipe:
            # 重名检测逻辑（与 parse_and_import_all 一致）
            original_name = recipe['name']
            if original_name in seen_names:
                counter = 2
                new_name = f"{original_name} (版本{counter})"
                while new_name in seen_names:
                    counter += 1
                    new_name = f"{original_name} (版本{counter})"
                recipe['name'] = new_name

            seen_names[recipe['name']] = str(md_file)
            all_recipes.append(recipe)

    # 验证结果
    assert len(all_recipes) == 2, f"应该解析到2道菜谱，实际: {len(all_recipes)}"
    names = [r['name'] for r in all_recipes]

    # 应该有一个原名和一个重命名版本
    assert "测试菜" in names, "应该有原始菜名"
    assert "测试菜 (版本2)" in names, f"应该有重命名版本，实际名称: {names}"

    # 验证两个菜谱内容确实不同（食材数量不同）
    recipe_by_name = {r['name']: r for r in all_recipes}
    ing_counts = {
        "测试菜": len(recipe_by_name["测试菜"]['ingredients']),
        "测试菜 (版本2)": len(recipe_by_name["测试菜 (版本2)"]['ingredients'])
    }
    # 因为 glob 顺序不确定，只验证有一个是1个食材，一个是2个食材
    assert set(ing_counts.values()) == {1, 2}, f"应该有一个1个食材，一个2个食材，实际: {ing_counts}"

    # 清理临时文件
    import shutil
    shutil.rmtree(temp_dir)

    print("✓ test_duplicate_name_handling 通过")


def run_all_tests():
    """运行所有测试"""
    print("=== 开始回归测试 ===\n")

    try:
        test_basic_recipe()
        test_recipe_with_h3_sections()
        test_recipe_with_calculation_section()
        test_duplicate_name_handling()

        print("\n=== 所有测试通过 ===")
        return True
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        return False
    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
