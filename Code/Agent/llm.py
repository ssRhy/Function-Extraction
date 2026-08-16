"""
LLM 调用模块 - 统一管理 DeepSeek API
"""

import os
import sys
import json
import atexit
import time
from openai import OpenAI

# ---- usage/耗时统计（LLM_USAGE=1 时启用；按调用方函数名归因） ----
_USAGE = {"calls": 0, "prompt": 0, "completion": 0, "elapsed": 0.0}
_BY_TAG: dict = {}


def _caller_name() -> str:
    try:
        return sys._getframe(4).f_code.co_name
    except Exception:
        return "?"


def _record_usage(prompt_tokens: int, completion_tokens: int, elapsed: float) -> None:
    _USAGE["calls"] += 1
    _USAGE["prompt"] += prompt_tokens
    _USAGE["completion"] += completion_tokens
    _USAGE["elapsed"] += elapsed
    tag = _caller_name()
    d = _BY_TAG.setdefault(tag, {"calls": 0, "prompt": 0, "completion": 0, "elapsed": 0.0})
    d["calls"] += 1
    d["prompt"] += prompt_tokens
    d["completion"] += completion_tokens
    d["elapsed"] += elapsed
    total = prompt_tokens + completion_tokens
    print(f"[LLM] {tag}: prompt={prompt_tokens} completion={completion_tokens} total={total} tok, {elapsed:.1f}s")


def _print_usage_summary() -> None:
    if not _USAGE["calls"]:
        return
    print("\n=== LLM Usage 汇总 ===")
    total = _USAGE["prompt"] + _USAGE["completion"]
    print(f"总调用 {_USAGE['calls']} 次 | prompt {_USAGE['prompt']} | completion {_USAGE['completion']} | 总token {total} | LLM 墙钟 {_USAGE['elapsed']:.1f}s")
    for tag, d in sorted(_BY_TAG.items()):
        print(f"  {tag}: {d['calls']} 次, prompt={d['prompt']}, completion={d['completion']}, 总token={d['prompt'] + d['completion']}, {d['elapsed']:.1f}s")


atexit.register(_print_usage_summary)


def get_client():
    """获取 DeepSeek 客户端（单例）"""
    if not hasattr(get_client, "_client"):
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        with open(env_path, "r") as f:
            api_key = f.read().strip()
        get_client._client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return get_client._client


def chat(messages: list, model: str = "deepseek-v4-flash", reasoning_effort: str = "none", response_format: dict | None = None) -> str:
    """通用 chat 接口"""
    client = get_client()
    kwargs = {
        "model": model,
        "messages": messages,
        "reasoning_effort": reasoning_effort
    }
    if response_format:
        kwargs["response_format"] = response_format
    t0 = time.perf_counter()
    response = client.chat.completions.create(**kwargs)
    elapsed = time.perf_counter() - t0
    content = response.choices[0].message.content
    if os.environ.get("LLM_USAGE") == "1":
        try:
            u = response.usage
            _record_usage(u.prompt_tokens, u.completion_tokens, elapsed)
        except Exception:
            _record_usage(0, 0, elapsed)
    return content


def chat_structured(messages: list, output_schema: type, model: str = "deepseek-v4-flash", reasoning_effort: str = "none"):
    """
    强制 JSON 格式返回 + Pydantic 验证解析。

    用法：
        from pydantic import BaseModel
        class User(BaseModel):
            name: str
            age: int
        user = chat_structured([...], User)
    """
    content = chat(messages, reasoning_effort=reasoning_effort, response_format={"type": "json_object"})

    if not content or not content.strip():
        raise ValueError("LLM 返回空响应")

    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]

    try:
        data = json.loads(content.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {e}\n原始内容: {content[:200]}")

    return output_schema.model_validate(data)
