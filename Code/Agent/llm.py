"""
LLM 调用模块 - 统一管理 DeepSeek API
"""

import os
import json
from openai import OpenAI


def get_client():
    """获取 DeepSeek 客户端（单例）"""
    if not hasattr(get_client, "_client"):
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        with open(env_path, "r") as f:
            api_key = f.read().strip()
        get_client._client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return get_client._client


def chat(messages: list, model: str = "deepseek-v4-flash", reasoning_effort: str = "low", response_format: dict | None = None) -> str:
    """通用 chat 接口"""
    client = get_client()
    kwargs = {
        "model": model,
        "messages": messages,
        "reasoning_effort": reasoning_effort
    }
    if response_format:
        kwargs["response_format"] = response_format
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    print(f"\n[DEBUG chat] raw response ({len(content) if content else 0} chars):")
    print("---BEGIN---")
    print(content if content else "<None>")
    print("---END---")
    return content


def chat_json(messages: list, model: str = "deepseek-v4-flash", reasoning_effort: str = "low") -> dict:
    """返回 JSON 格式，带错误处理"""
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
        return json.loads(content.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {e}\n原始内容: {content[:200]}")


def chat_structured(messages: list, output_schema: type, model: str = "deepseek-v4-flash", reasoning_effort: str = "low"):
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
