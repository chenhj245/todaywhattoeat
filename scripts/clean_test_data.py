"""
清理测试数据脚本

用于清除测试污染的生产数据库数据
"""
import asyncio
import aiosqlite
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH


async def clean_test_data(days_threshold: int = 7, dry_run: bool = False):
    """
    清理测试残留数据（安全版本）

    策略：
    1. 只删除最近 N 天内创建的重复数据
    2. 如果同一天内有多条同名记录，只保留最早一条
    3. 支持 dry_run 模式预览

    Args:
        days_threshold: 只清理最近几天的数据（默认7天）
        dry_run: True 时只显示会删除什么，不实际删除
    """
    async with aiosqlite.connect(DB_PATH) as db:
        from datetime import datetime, timedelta

        # 计算时间阈值
        threshold_date = (datetime.now() - timedelta(days=days_threshold)).isoformat()

        # 获取清理前统计
        cursor = await db.execute("SELECT COUNT(*) FROM kitchen_items WHERE is_active = 1")
        before_count = (await cursor.fetchone())[0]

        # 找到要删除的重复记录（限制在时间窗口内）
        cursor = await db.execute("""
            SELECT id, name, created_at
            FROM kitchen_items
            WHERE is_active = 1
              AND created_at >= ?
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM kitchen_items
                  WHERE is_active = 1
                    AND created_at >= ?
                  GROUP BY name, DATE(created_at)
              )
            ORDER BY name, created_at
        """, (threshold_date, threshold_date))

        to_delete = await cursor.fetchall()

        if dry_run:
            print(f"🔍 预览模式（不会实际删除）")
            print(f"📅 时间范围: 最近 {days_threshold} 天")
            print(f"📊 将要删除的记录:")
            for row in to_delete:
                print(f"  - ID {row[0]}: {row[1]} (创建于 {row[2]})")
            print(f"✓ 预计删除: {len(to_delete)} 条")
            return

        # 实际删除
        if to_delete:
            delete_ids = [row[0] for row in to_delete]
            placeholders = ','.join('?' * len(delete_ids))
            await db.execute(f"""
                DELETE FROM kitchen_items
                WHERE id IN ({placeholders})
            """, delete_ids)

        # 获取清理后统计
        cursor = await db.execute("SELECT COUNT(*) FROM kitchen_items WHERE is_active = 1")
        after_count = (await cursor.fetchone())[0]

        await db.commit()

        print(f"✓ 清理完成（最近 {days_threshold} 天的重复数据）")
        print(f"  清理前: {before_count} 条")
        print(f"  清理后: {after_count} 条")
        print(f"  删除: {before_count - after_count} 条重复数据")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="清理测试数据")
    parser.add_argument("--days", type=int, default=7, help="只清理最近N天的数据")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际删除")
    args = parser.parse_args()

    asyncio.run(clean_test_data(days_threshold=args.days, dry_run=args.dry_run))
