"""
LLM 调用模块 - 统一管理 DeepSeek API
"""

import os
import sys
import json
import re
import atexit
import time
from openai import OpenAI
from pydantic import ValidationError

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


def chat(messages: list, model: str = "deepseek-v4-flash", response_format: dict | None = None) -> str:
    """通用 chat 接口"""
    client = get_client()
    kwargs = {
        "model": model,
        "messages": messages,
        "reasoning_effort": "none"  # 硬编码：bootstrap 全链路统一使用 none，不暴露参数
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


# JSON 解析/校验失败的最大重试次数（把错误反馈给 LLM 让它自纠正）
_STRUCTURED_RETRY = 2


def _strip_json_fences(content: str) -> str:
    """去掉 LLM 可能包裹的 ```json 代码块围栏。"""
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def _repair_json(content: str) -> str:
    """轻量修复：剔除非法控制字符、去掉尾逗号（尽力而为，失败仍走重试）。"""
    repaired = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", content)
    return re.sub(r",\s*([}\]])", r"\1", repaired)


def chat_structured(messages: list, output_schema: type, model: str = "deepseek-v4-flash"):
    """
    强制 JSON 格式返回 + Pydantic 验证解析。

    JSON 解析失败（坏 JSON）或字段校验失败（缺字段/类型错）时，把错误反馈给 LLM
    自动重试（最多 _STRUCTURED_RETRY 次），保证结构化输出层自纠正，不再由上层崩溃。
    """
    last_error = ""
    last_content = ""
    for attempt in range(_STRUCTURED_RETRY + 1):
        content = _strip_json_fences(chat(messages, response_format={"type": "json_object"}) or "")
        last_content = content
        if not content:
            last_error = "LLM 返回空响应"
        else:
            data = None
            for candidate in (content, _repair_json(content)):
                try:
                    data = json.loads(candidate)
                    break
                except json.JSONDecodeError as e:
                    last_error = f"JSON 解析失败: {e}"
            if data is not None:
                try:
                    return output_schema.model_validate(data)
                except ValidationError as e:
                    last_error = f"字段校验失败: {str(e)[:300]}"
        if attempt < _STRUCTURED_RETRY:
            print(f"  [llm] 结构化输出重试 {attempt + 1}/{_STRUCTURED_RETRY}: {last_error}")
            messages = list(messages) + [{
                "role": "user",
                "content": f"你上次的输出解析失败：{last_error}\n请只重新输出符合要求的 JSON。",
            }]
    raise ValueError(f"结构化输出 {_STRUCTURED_RETRY} 次重试后仍失败: {last_error}\n原始内容: {last_content[:200]}")
