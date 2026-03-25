"""
FastAPI 主应用

提供 RESTful API 和 SSE 流式对话接口
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict
import asyncio
import json
from pathlib import Path
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend import agent, tools, database as db
from backend.confidence import calculate_current_confidence, get_recommendation_note


def log_debug(message: str):
    print(message, flush=True)

# 创建 FastAPI 应用
app = FastAPI(
    title="KitchenMind API",
    description="对话驱动的厨房状态管理 Agent",
    version="1.0.0"
)

# 创建全局 Agent 实例（维护会话历史）
kitchen_agent = agent.KitchenMindAgent()

# CORS 配置（开发环境）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


# ========== 数据模型 ==========

class ChatMessage(BaseModel):
    """聊天消息"""
    message: str
    stream: bool = False  # 是否使用流式响应


class UndoResponse(BaseModel):
    """撤销响应"""
    success: bool
    message: str
    action_type: Optional[str] = None


class KitchenStateResponse(BaseModel):
    """厨房状态响应"""
    success: bool
    total_items: int
    high_confidence: List[Dict]
    medium_confidence: List[Dict]
    low_confidence: List[Dict]


class ShoppingListResponse(BaseModel):
    """购物清单响应"""
    success: bool
    shopping_list: List[Dict]
    planned_meals: List[str]


# ========== API 端点 ==========

@app.get("/")
async def root():
    """根路径 - API 信息"""
    return {
        "name": "KitchenMind API",
        "version": "1.0.0",
        "endpoints": {
            "chat": "POST /api/chat - 对话接口",
            "chat_stream": "POST /api/chat (stream=true) - 流式对话",
            "chat_clear": "POST /api/chat/clear - 清空对话历史",
            "kitchen_state": "GET /api/kitchen/state - 厨房状态",
            "undo": "POST /api/kitchen/undo - 撤销操作",
            "shopping_list": "GET /api/shopping - 购物清单"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


@app.post("/api/chat")
async def chat(message: ChatMessage):
    """
    对话接口

    支持两种模式:
    - stream=false: 返回完整 JSON 响应
    - stream=true: 返回 SSE 流式响应
    """
    log_debug(f"[API] 收到聊天请求 stream={message.stream} message={message.message[:120]}")

    if message.stream:
        # 流式响应
        log_debug("[API] 使用 SSE 流式响应")
        return StreamingResponse(
            chat_stream_generator(message.message),
            media_type="text/event-stream"
        )
    else:
        # 非流式响应（使用全局 agent 实例维护历史）
        try:
            assistant_message = await kitchen_agent.chat(message.message)
            log_debug(f"[API] 非流式响应完成 message={assistant_message[:100]}")
            return JSONResponse(content={"assistant_message": assistant_message})
        except Exception as e:
            log_debug(f"[API] 非流式聊天请求失败 error={e}")
            raise HTTPException(status_code=500, detail=str(e))


async def chat_stream_generator(user_message: str):
    """
    SSE 流式生成器

    生成格式:
    data: {"type": "intent", "content": "add"}
    data: {"type": "tool", "content": {...}}
    data: {"type": "message", "content": "已添加..."}
    data: {"type": "done"}
    """
    try:
        log_debug(f"[API] SSE 生成器启动 message={user_message[:120]}")

        # 1. 发送意图识别结果
        intent, model_tier = agent.classify_intent(user_message)
        log_debug(f"[API] SSE 意图识别 intent={intent} model_tier={model_tier}")
        yield f"data: {json.dumps({'type': 'intent', 'content': intent}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.01)  # 模拟流式效果

        # 2. 处理消息（使用全局 agent 实例维护历史和会话状态）
        result = await kitchen_agent.process(user_message)
        log_debug(f"[API] SSE 处理完成 intent={result.get('intent')} model={result.get('model_used')} tool_count={len(result.get('tool_results', []))}")

        # 3. 发送工具调用结果
        if result.get("tool_results"):
            for tool_result in result["tool_results"]:
                yield f"data: {json.dumps({'type': 'tool', 'content': tool_result}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)

        # 4. 发送 AI 回复（模拟逐字输出）
        assistant_message = result.get("assistant_message", "")
        if assistant_message:
            # 按标点符号分割，模拟流式输出
            chunks = []
            current_chunk = ""
            for char in assistant_message:
                current_chunk += char
                if char in "。！？\n，、；：":
                    chunks.append(current_chunk)
                    current_chunk = ""
            if current_chunk:
                chunks.append(current_chunk)

            for chunk in chunks:
                yield f"data: {json.dumps({'type': 'message_chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.05)  # 模拟打字效果

        # 5. 发送完成信号
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        log_debug("[API] SSE 响应完成")

    except Exception as e:
        log_debug(f"[API] SSE 聊天请求失败 error={e}")
        error_msg = f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        yield error_msg


@app.get("/api/kitchen/state")
async def get_kitchen_state():
    """
    获取厨房库存状态

    返回按置信度分组的食材列表
    """
    try:
        result = await tools.get_kitchen_state()
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/kitchen/undo")
async def undo_last_action():
    """
    撤销上一次操作

    支持撤销 add 和 consume 操作
    """
    try:
        result = await tools.undo_last_action()
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/clear")
async def clear_chat_history():
    """
    清空对话历史

    用于重置会话上下文
    """
    try:
        kitchen_agent.clear_history()
        log_debug("[API] 对话历史已清空")
        return JSONResponse(content={"success": True, "message": "对话历史已清空"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/shopping")
async def get_shopping_list(meals: Optional[str] = None):
    """
    获取购物清单

    参数:
        meals: 计划做的菜品，逗号分隔（如 "番茄炒蛋,红烧肉"）
    """
    try:
        planned_meals = meals.split(",") if meals else []
        result = await tools.generate_shopping_list(planned_meals=planned_meals)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/suggest")
async def suggest_meals(max_results: int = 5):
    """
    推荐菜品

    参数:
        max_results: 最多返回几个推荐
    """
    try:
        result = await tools.suggest_meals(max_results=max_results)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== 启动配置 ==========

if __name__ == "__main__":
    import uvicorn

    print("🚀 启动 KitchenMind API 服务...")
    print("📍 访问地址: http://localhost:8000")
    print("📖 API 文档: http://localhost:8000/docs")

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # 开发模式自动重载
        log_level="info"
    )
