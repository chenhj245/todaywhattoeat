"""
Agent 核心逻辑

包含意图路由、工具调用和主循环
"""
import re
import json
from typing import Dict, Optional, Tuple
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.llm import chat_with_tools, get_llm_client, OLLAMA_SMALL_MODEL, OLLAMA_LARGE_MODEL
from backend import tools
from backend.tools import TOOLS_DEFINITION


# 意图路由模式（规则匹配）
# 注意：query 应该放在前面，以便"冰箱里还有什么"优先匹配 query 而不是 add
INTENT_PATTERNS = {
    "query": [
        r"(冰箱|家)里(还)?有(什么|多少|哪些|几)", r"库存", r"查看", r"还剩", r"剩(什么|多少)"
    ],
    "add": [
        r"买了", r"带了", r"拿了", r"买回", r"带回",
        r"补了", r"囤了", r"(放|存)进(冰箱|家)"
    ],
    "consume": [
        r"做了", r"炒了", r"煮了", r"蒸了", r"烤了",
        r"吃了", r"吃掉", r"用了", r"用掉", r"扔了", r"坏了"
    ],
    "suggest": [
        r"吃什么", r"做什么", r"推荐", r"建议", r"今[天晚]",
        r"想吃", r"能做", r"有什么菜", r"帮我想"
    ],
    "shopping": [
        r"买什么", r"购物", r"采购", r"清单", r"缺什么", r"要买"
    ],
    "undo": [
        r"撤[回销]", r"取消", r"搞错", r"不对", r"删[掉除]"
    ]
}


def classify_intent(text: str) -> Tuple[str, str]:
    """
    规则式意图分类

    Returns:
        (intent, model_tier)
        intent: add/consume/suggest/shopping/undo/query/unknown
        model_tier: small/large
    """
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                # 简单意图用小模型，复杂意图用大模型
                if intent in ("add", "consume", "undo", "query"):
                    return intent, "small"
                else:
                    return intent, "large"

    # 无法识别 → 交给大模型
    return "unknown", "large"


# Agent System Prompt
SYSTEM_PROMPT = """你是 KitchenMind，一个家庭厨房助手。你的目标是帮用户解决"今晚吃什么"的问题。

## 你的核心能力
- 记住用户家里有什么食材（通过工具管理库存）
- 推荐适合当前库存和用户偏好的菜品
- 在用户买菜、做饭时自动更新库存状态
- 生成购物清单

## 你的行为准则

### 关于库存更新
- 用户说"买了XXX"时，直接调用 add_items，不需要确认
- 用户说"做了XXX菜"时，调用 consume_items 按菜谱扣减，在回复中顺带提一句扣了什么
- 如果不确定用量（比如"做了个面"），给出你的最佳猜测，在回复中说明你的假设
- 永远不要要求用户填写精确克数

### 关于推荐
- 推荐前先调用 get_kitchen_state 了解当前库存
- 优先推荐：高置信度食材能做的菜 > 临期食材优先消耗 > 用户口味偏好
- 每次推荐 1-3 道菜，给出预估时间和难度
- 如果某道菜缺少 1-2 样食材，直接说明缺什么，而不是不推荐
- 用"如果你家还有XX的话"这种措辞处理低置信度食材

### 关于语气
- 像一个了解你厨房的朋友，不是一个系统
- 出错时说"我可能记错了"，不说"数据有误"
- 保持简洁，不要长篇大论
- 可以偶尔表达对食物的热情

### 关于纠错
- 用户说"搞错了""撤回"时，立即调用 undo_last_action
- 纠错后态度轻松："好的，已经撤回了"
"""


async def execute_tool(tool_name: str, arguments: Dict) -> Dict:
    """
    执行工具函数

    Args:
        tool_name: 工具名称
        arguments: 参数字典

    Returns:
        工具执行结果
    """
    tool_map = {
        "add_items": tools.add_items,
        "consume_items": tools.consume_items,
        "get_kitchen_state": tools.get_kitchen_state,
        "suggest_meals": tools.suggest_meals,
        "generate_shopping_list": tools.generate_shopping_list,
        "undo_last_action": tools.undo_last_action
    }

    if tool_name not in tool_map:
        return {
            "success": False,
            "error": f"未知工具: {tool_name}"
        }

    try:
        result = await tool_map[tool_name](**arguments)
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


async def process_message(
    user_message: str,
    conversation_history: Optional[list] = None
) -> Dict:
    """
    处理用户消息的主函数

    Args:
        user_message: 用户输入
        conversation_history: 历史对话（可选）

    Returns:
        {
            "assistant_message": str,  # 助手回复
            "tool_results": list,      # 工具调用结果
            "intent": str,             # 识别的意图
            "model_used": str          # 使用的模型
        }
    """
    # 1. 意图路由
    intent, model_tier = classify_intent(user_message)
    model = OLLAMA_SMALL_MODEL if model_tier == "small" else OLLAMA_LARGE_MODEL

    print(f"[Agent] 意图: {intent}, 模型: {model}")

    # 2. suggest 意图硬路由（直接调用工具，不走 LLM）
    if intent == "suggest":
        print(f"[Agent] 硬路由 suggest_meals")
        result = await tools.suggest_meals(constraints=user_message, max_results=3)

        # 将工具结果传给 LLM 生成自然语言回复
        tool_results = [{
            "tool": "suggest_meals",
            "result": result
        }]

        # 让 LLM 总结工具结果
        from backend.llm import simple_chat
        summary_prompt = f"""用户问: {user_message}

我调用了推荐工具，结果如下：
{json.dumps(result, ensure_ascii=False, indent=2)}

请用简洁、友好的语气总结推荐结果，包括：
1. 推荐了哪几道菜
2. 匹配度如何
3. 如果缺食材，简单提醒

保持口语化，像朋友聊天。"""

        assistant_message = await simple_chat(summary_prompt, model=model)

        return {
            "assistant_message": assistant_message,
            "tool_results": tool_results,
            "intent": intent,
            "model_used": model
        }

    # 3. 调用 LLM（带工具）
    response = await chat_with_tools(
        user_message=user_message,
        tools=TOOLS_DEFINITION,
        system_prompt=SYSTEM_PROMPT,
        model=model,
        conversation_history=conversation_history
    )

    # 3. 处理响应
    tool_results = []
    assistant_message = ""

    if "error" in response:
        assistant_message = response.get("message", {}).get("content", "抱歉，出现了问题")
        return {
            "assistant_message": assistant_message,
            "tool_results": [],
            "intent": intent,
            "model_used": model,
            "error": response["error"]
        }

    message = response.get("message", {})

    # 检查是否有工具调用
    tool_calls = message.get("tool_calls", [])

    if tool_calls:
        # 执行所有工具调用
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            tool_name = function.get("name")
            arguments_str = function.get("arguments", "{}")

            try:
                arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
            except json.JSONDecodeError:
                arguments = {}

            print(f"[Agent] 调用工具: {tool_name}({arguments})")

            # 执行工具
            result = await execute_tool(tool_name, arguments)
            tool_results.append({
                "tool": tool_name,
                "result": result
            })

        # 生成最终回复：将工具结果回传给模型做第二轮总结
        if tool_results:
            # 构建工具结果摘要
            tool_summary = []
            for tr in tool_results:
                tool_name = tr["tool"]
                result = tr["result"]
                tool_summary.append(f"工具 {tool_name} 返回:\n{json.dumps(result, ensure_ascii=False, indent=2)}")

            # 第二轮：让 LLM 基于工具结果生成自然语言回复
            from backend.llm import simple_chat
            summary_prompt = f"""用户问: {user_message}

我调用了工具，结果如下：
{chr(10).join(tool_summary)}

请用简洁、友好的语气总结结果，像朋友聊天一样自然。"""

            assistant_message = await simple_chat(summary_prompt, model=model)
            print(f"[Agent] 二轮总结完成")
    else:
        # 没有工具调用，直接返回 LLM 回复
        assistant_message = message.get("content", "")

    return {
        "assistant_message": assistant_message,
        "tool_results": tool_results,
        "intent": intent,
        "model_used": model
    }


class KitchenMindAgent:
    """KitchenMind Agent 类（便于管理状态）"""

    def __init__(self):
        self.conversation_history = []

    async def chat(self, user_message: str) -> str:
        """
        对话接口

        Args:
            user_message: 用户消息

        Returns:
            助手回复
        """
        # 处理消息
        result = await process_message(
            user_message,
            conversation_history=self.conversation_history
        )

        # 更新历史
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })
        self.conversation_history.append({
            "role": "assistant",
            "content": result["assistant_message"]
        })

        # 限制历史长度（保留最近 10 轮）
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

        return result["assistant_message"]

    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []
