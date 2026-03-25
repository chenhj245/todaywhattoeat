"""PydanticAI 驱动的结构化参数提取层。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Type


def _preview_text(text: str, limit: int = 200) -> str:
    text = (text or "").replace("\n", "\\n")
    return text[:limit] + ("..." if len(text) > limit else "")


import httpx
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from config import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_SMALL_MODEL,
    OLLAMA_LARGE_MODEL,
)
from backend.llm import get_llm_client
from backend.schemas import (
    AddPayload,
    ClarifyPayload,
    ConsumePayload,
    DeletePayload,
    HowtoPayload,
    QueryPayload,
    RecipeCheckPayload,
    ShoppingPayload,
    SuggestPayload,
)


SCHEMA_BY_INTENT: dict[str, Type[BaseModel]] = {
    "add": AddPayload,
    "consume": ConsumePayload,
    "delete": DeletePayload,
    "query": QueryPayload,
    "shopping": ShoppingPayload,
    "suggest": SuggestPayload,
    "howto": HowtoPayload,
    "recipe_check": RecipeCheckPayload,
    "clarify": ClarifyPayload,
    "repair": ClarifyPayload,
}


INSTRUCTIONS_BY_INTENT = {
    "add": (
        "你是厨房库存参数提取器。只输出符合 schema 的结构化结果。"
        "提取用户新添加、购买、带回家的食材。"
        "如果有明确数量就填 quantity_num 和 unit；否则保留 quantity_desc 或留空。"
    ),
    "consume": (
        "你是厨房消耗参数提取器。只输出符合 schema 的结构化结果。"
        "如果用户提到做了多道菜，必须把所有菜名放进 recipe_names 列表。"
        "如果用户手动说用了哪些食材，则填 items 列表。"
        "reason 用简洁中文概括用户本次消耗行为。"
    ),
    "delete": (
        "你是厨房删除条件提取器。只输出符合 schema 的结构化结果。"
        "mode 只能是 exact、contains、prefix、predicate。"
        "predicate 只能是 contains_ascii 或 contains_digit。"
        "不要把情绪、评价、代词当 keyword。"
        "如果用户只是抱怨系统没删掉，不要编造 keyword，返回空条件。"
    ),
    "query": (
        "你是库存查询参数提取器。只输出符合 schema 的结构化结果。"
        "大多数普通查询使用默认 min_confidence=0.1。"
        "如果用户明确要看全部库存，可设置为 0。"
    ),
    "shopping": (
        "你是购物清单参数提取器。只输出符合 schema 的结构化结果。"
        "planned_meals 里放用户计划要做的菜。"
    ),
    "suggest": (
        "你是菜品推荐参数提取器。只输出符合 schema 的结构化结果。"
        "constraints 保留用户原始需求要点，比如人数、口味、减肥、清淡、时间要求。"
        "如果用户说除了某道菜、不要某道菜，把它放进 exclude_recipes。"
        "如果用户提到几个人吃饭，提取 servings。"
        "如果用户在问搭配主菜的小菜，meal_role 填 side_dish。"
        "max_results 默认 3。"
    ),
    "howto": (
        "你是菜谱做法参数提取器。只输出符合 schema 的结构化结果。"
        "提取用户想知道做法的菜名。"
    ),
    "recipe_check": (
        "你是菜谱可行性判断参数提取器。只输出符合 schema 的结构化结果。"
        "提取用户要确认能不能做的菜名，以及特别关心的食材名。"
    ),
    "clarify": "你只需要生成一个简短的澄清提示。",
    "repair": "你只需要生成一个简短的修复/澄清提示。",
}


@lru_cache(maxsize=4)
def _build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=15.0),
        trust_env=False,
    )


@lru_cache(maxsize=4)
def _build_ollama_model(model_name: str) -> OpenAIModel:
    provider = OpenAIProvider(
        base_url=f"{OLLAMA_BASE_URL.rstrip('/')}/v1",
        api_key="ollama",
        http_client=_build_http_client(),
    )
    return OpenAIModel(model_name, provider=provider)


async def _run_with_ollama_pydantic_ai(
    intent: str,
    user_message: str,
    model_tier: str,
    context_text: str = "",
) -> BaseModel:
    schema = SCHEMA_BY_INTENT[intent]
    model_name = OLLAMA_SMALL_MODEL if model_tier == "small" else OLLAMA_LARGE_MODEL
    print(f"[PydanticAI] provider=ollama intent={intent} model={model_name}", flush=True)
    model = _build_ollama_model(model_name)
    extractor = Agent(
        model=model,
        output_type=schema,
        instructions=INSTRUCTIONS_BY_INTENT[intent],
        retries=1,
        defer_model_check=True,
    )
    prompt = f"用户原话: {user_message}"
    if context_text:
        prompt += f"\n上下文: {context_text}"
    result = await extractor.run(prompt)
    print(f"[PydanticAI] structured output: {_preview_text(result.output.model_dump_json(ensure_ascii=False))}", flush=True)
    return result.output


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        return json.loads(match.group(0))


async def _run_with_qwen_json_validation(
    intent: str,
    user_message: str,
    model_tier: str,
    context_text: str = "",
) -> BaseModel:
    schema = SCHEMA_BY_INTENT[intent]
    model_name = OLLAMA_SMALL_MODEL if model_tier == "small" else OLLAMA_LARGE_MODEL
    print(f"[PydanticAI] provider=qwen intent={intent} model={model_name} transport=json-validation", flush=True)
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    prompt = (
        f"你是结构化参数提取器。{INSTRUCTIONS_BY_INTENT[intent]}\n"
        f"只输出一个 JSON 对象，不要输出 markdown，不要解释。\n"
        f"输出必须符合这个 JSON Schema: {schema_json}\n"
        f"用户原话: {user_message}"
    )
    if context_text:
        prompt += f"\n上下文: {context_text}"

    client = get_llm_client()
    response = await client._call_qwen_api(
        messages=[{"role": "user", "content": prompt}],
        model=model_name,
        tools=None,
        temperature=0.1,
        stream=False,
    )
    content = response.get("message", {}).get("content", "")
    print(f"[PydanticAI] raw text output: {_preview_text(content)}", flush=True)
    data = _extract_json_object(content)
    validated = schema.model_validate(data)
    print(f"[PydanticAI] structured output: {_preview_text(validated.model_dump_json(ensure_ascii=False))}", flush=True)
    return validated


async def extract_structured_payload(
    intent: str,
    user_message: str,
    model_tier: str = "small",
    context_text: str = "",
) -> BaseModel:
    provider = (LLM_PROVIDER or "auto").lower()

    if provider == "qwen":
        return await _run_with_qwen_json_validation(intent, user_message, model_tier, context_text)

    if provider == "ollama":
        return await _run_with_ollama_pydantic_ai(intent, user_message, model_tier, context_text)

    try:
        return await _run_with_ollama_pydantic_ai(intent, user_message, model_tier, context_text)
    except Exception as ollama_error:
        print(f"[PydanticAI] Ollama 提取失败: {repr(ollama_error)}", flush=True)
        return await _run_with_qwen_json_validation(intent, user_message, model_tier, context_text)
