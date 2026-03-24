"""
LLM 调用封装

支持 Ollama 本地推理和 Qwen API 云端备用
"""
import httpx
import json
from typing import List, Dict, Optional, AsyncGenerator
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    OLLAMA_BASE_URL,
    OLLAMA_SMALL_MODEL,
    OLLAMA_LARGE_MODEL,
    QWEN_API_KEY,
    QWEN_API_BASE,
    LLM_PROVIDER
)


class LLMClient:
    """LLM 调用客户端"""

    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip('/')
        # 禁用环境变量代理，Ollama 是本地服务
        self.client = httpx.AsyncClient(timeout=60.0, trust_env=False)

    async def _check_ollama_health(self) -> bool:
        """检查 Ollama 本地服务是否可用"""
        health_url = f"{self.base_url}/api/tags"
        try:
            response = await self.client.get(health_url)
            response.raise_for_status()
            print(f"[LLM] Ollama 健康检查通过: {health_url}", flush=True)
            return True
        except Exception as e:
            print(f"[LLM] Ollama 健康检查失败: {repr(e)}", flush=True)
            print(f"[LLM] 健康检查 URL: {health_url}", flush=True)
            return False

    @staticmethod
    def _log_http_error(prefix: str, error: Exception):
        print(f"{prefix}: {repr(error)}", flush=True)
        response = getattr(error, "response", None)
        request = getattr(error, "request", None)
        if request is not None:
            print(f"[LLM] 请求方法: {request.method}", flush=True)
            print(f"[LLM] 请求 URL: {request.url}", flush=True)
        if response is not None:
            print(f"[LLM] 状态码: {response.status_code}", flush=True)
            print(f"[LLM] 响应体: {response.text[:500]}", flush=True)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = OLLAMA_SMALL_MODEL,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        stream: bool = False
    ) -> Dict:
        """
        调用 chat completion API

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            model: 模型名称
            tools: 工具定义列表（OpenAI 格式）
            temperature: 温度参数
            stream: 是否流式返回

        Returns:
            响应字典
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream
        }

        if tools:
            payload["tools"] = tools

        provider = (LLM_PROVIDER or "auto").lower()
        print(f"[LLM] 当前提供方模式: {provider}", flush=True)

        if provider == "qwen":
            if QWEN_API_KEY:
                print("[LLM] 已强制使用 Qwen 在线模型", flush=True)
                try:
                    return await self._call_qwen_api(messages, model, tools, temperature, stream)
                except Exception as qwen_error:
                    self._log_http_error("[LLM] Qwen 强制模式调用失败", qwen_error)
                    return {
                        "error": str(qwen_error),
                        "message": {
                            "role": "assistant",
                            "content": "抱歉，在线模型暂时不可用，请稍后再试。"
                        }
                    }
            return {
                "error": "Qwen API key not configured",
                "message": {
                    "role": "assistant",
                    "content": "抱歉，在线模型未配置。"
                }
            }

        if provider == "ollama":
            print("[LLM] 已强制使用 Ollama 本地模型", flush=True)
            return await self._call_ollama_api(payload, model)

        # auto 模式: 优先 Ollama，失败后回退 Qwen
        print("[LLM] auto 模式：优先 Ollama，失败后回退 Qwen", flush=True)
        try:
            return await self._call_ollama_api(payload, model)
        except Exception as e:
            if QWEN_API_KEY:
                print(f"[LLM] 尝试使用千问 API 作为备用...", flush=True)
                try:
                    return await self._call_qwen_api(messages, model, tools, temperature, stream)
                except Exception as qwen_error:
                    self._log_http_error("[LLM] 千问 API 调用也失败", qwen_error)
            return {
                "error": str(e),
                "message": {
                    "role": "assistant",
                    "content": "抱歉，我现在遇到了一些问题，请稍后再试。"
                }
            }

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = OLLAMA_SMALL_MODEL,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        """
        流式调用 chat completion API

        Yields:
            逐个返回的文本片段
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True
        }

        if tools:
            payload["tools"] = tools

        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)
                            if "message" in chunk:
                                content = chunk["message"].get("content", "")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue

        except httpx.HTTPError as e:
            self._log_http_error("[LLM] 流式调用失败", e)
            yield "抱歉，我现在遇到了一些问题。"

    async def _call_qwen_api(
        self,
        messages: List[Dict[str, str]],
        model: str,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        stream: bool = False
    ) -> Dict:
        """
        调用千问 API（OpenAI 兼容格式）

        Args:
            messages: 消息列表
            model: 模型名称（会映射到千问模型）
            tools: 工具定义列表
            temperature: 温度参数
            stream: 是否流式返回

        Returns:
            响应字典（Ollama 格式）
        """
        # 当前套餐仅支持 qwen3.5-plus，统一映射到专属可用模型
        qwen_model_map = {
            "qwen3.5:9b": "qwen3.5-plus",
            "qwen3.5:35b": "qwen3.5-plus"
        }
        qwen_model = qwen_model_map.get(model, "qwen3.5-plus")

        payload = {
            "model": qwen_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False  # 暂不支持流式
        }

        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {QWEN_API_KEY}",
            "Content-Type": "application/json"
        }

        print(f"[LLM] 千问 API 请求: {QWEN_API_BASE}/chat/completions", flush=True)
        print(f"[LLM] 千问模型: {qwen_model}", flush=True)
        print(f"[LLM] 消息数量: {len(messages)}", flush=True)

        response = await self.client.post(
            f"{QWEN_API_BASE}/chat/completions",
            json=payload,
            headers=headers
        )

        if response.status_code != 200:
            error_text = response.text
            print(f"[LLM] 千问 API 错误响应: {error_text[:500]}", flush=True)

        response.raise_for_status()

        # 转换为 Ollama 格式
        openai_response = response.json()
        choice = openai_response["choices"][0]

        ollama_response = {
            "model": model,
            "created_at": openai_response.get("created", ""),
            "message": {
                "role": choice["message"]["role"],
                "content": choice["message"].get("content", "")
            },
            "done": True
        }

        # 处理工具调用
        if "tool_calls" in choice["message"]:
            ollama_response["message"]["tool_calls"] = choice["message"]["tool_calls"]

        return ollama_response

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()


# 全局客户端实例
_llm_client = None


def get_llm_client() -> LLMClient:
    """获取全局 LLM 客户端"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


async def simple_chat(
    user_message: str,
    system_prompt: Optional[str] = None,
    model: str = OLLAMA_SMALL_MODEL
) -> str:
    """
    简单的单轮对话

    Args:
        user_message: 用户消息
        system_prompt: 系统提示（可选）
        model: 模型名称

    Returns:
        助手回复文本
    """
    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": user_message})

    client = get_llm_client()
    response = await client.chat(messages, model=model)

    if "error" in response:
        return response["message"]["content"]

    return response.get("message", {}).get("content", "")


async def chat_with_tools(
    user_message: str,
    tools: List[Dict],
    system_prompt: Optional[str] = None,
    model: str = OLLAMA_SMALL_MODEL,
    conversation_history: Optional[List[Dict]] = None
) -> Dict:
    """
    带工具调用的对话

    Args:
        user_message: 用户消息
        tools: 工具定义列表
        system_prompt: 系统提示
        model: 模型名称
        conversation_history: 历史对话记录

    Returns:
        完整响应，包含可能的 tool_calls
    """
    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_message})

    client = get_llm_client()
    response = await client.chat(messages, model=model, tools=tools)

    return response
