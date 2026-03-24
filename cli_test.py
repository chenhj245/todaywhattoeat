#!/usr/bin/env python3
"""
KitchenMind CLI 测试界面

用于测试 Agent 核心功能
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from backend.agent import KitchenMindAgent


async def main():
    """主函数"""
    print("=== KitchenMind CLI 测试界面 ===")
    print("输入 'quit' 或 'exit' 退出")
    print("输入 'clear' 清空对话历史")
    print("输入 'help' 查看帮助\n")

    agent = KitchenMindAgent()

    while True:
        try:
            # 读取用户输入
            user_input = input("\n你: ").strip()

            if not user_input:
                continue

            # 特殊命令
            if user_input.lower() in ('quit', 'exit'):
                print("再见！")
                break

            if user_input.lower() == 'clear':
                agent.clear_history()
                print("[系统] 对话历史已清空")
                continue

            if user_input.lower() == 'help':
                print("""
可用的测试指令：
- "买了鸡蛋、西红柿" - 测试添加食材
- "做了番茄炒蛋" - 测试消耗食材
- "今晚吃什么" - 测试推荐菜品
- "冰箱里有什么" - 查看库存
- "撤销" - 撤销上一次操作
- "买什么" - 生成购物清单
                """)
                continue

            # 调用 Agent
            print("\nKitchenMind: ", end="", flush=True)
            response = await agent.chat(user_input)
            print(response)

        except KeyboardInterrupt:
            print("\n\n再见！")
            break
        except Exception as e:
            print(f"\n[错误] {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
