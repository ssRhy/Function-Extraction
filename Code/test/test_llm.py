"""llm.py 结构化输出 JSON 数据层测试：正常解析 / 坏 JSON 重试 / 轻量修复 / 校验失败重试 / 仍失败报错。"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pydantic import BaseModel

import Agent.llm as llm


class _Item(BaseModel):
    name: str
    age: int


def _patch_chat(fake):
    orig = llm.chat
    llm.chat = fake
    return orig


def test_success():
    orig = _patch_chat(lambda messages, response_format=None, **kw: json.dumps({"name": "a", "age": 1}))
    try:
        r = llm.chat_structured([{"role": "user", "content": "x"}], _Item)
        assert r.name == "a" and r.age == 1
    finally:
        llm.chat = orig
    print("chat_structured 正常解析: OK")


def test_retry_after_bad_json():
    responses = iter(['{"name": "a", "age": ', '{"name": "a", "age": 1}'])
    calls = []
    orig = _patch_chat(lambda messages, response_format=None, **kw: (calls.append(messages) or next(responses)))
    try:
        r = llm.chat_structured([{"role": "user", "content": "x"}], _Item)
        assert r.name == "a"
    finally:
        llm.chat = orig
    assert len(calls) == 2, len(calls)
    assert "解析失败" in calls[1][-1]["content"], calls[1][-1]["content"]
    print("坏 JSON → 反馈重试成功: OK")


def test_repair_trailing_comma():
    orig = _patch_chat(lambda messages, response_format=None, **kw: '{"name": "a", "age": 1,}')
    try:
        r = llm.chat_structured([], _Item)
        assert r.age == 1
    finally:
        llm.chat = orig
    print("尾逗号轻量修复: OK")


def test_retry_after_validation_error():
    responses = iter(['{"name": "a"}', '{"name": "a", "age": 2}'])
    calls = []
    orig = _patch_chat(lambda messages, response_format=None, **kw: (calls.append(messages) or next(responses)))
    try:
        r = llm.chat_structured([], _Item)
        assert r.age == 2
    finally:
        llm.chat = orig
    assert len(calls) == 2, len(calls)
    assert "字段校验失败" in calls[1][-1]["content"], calls[1][-1]["content"]
    print("缺字段 → 反馈重试成功: OK")


def test_fails_after_retries():
    orig = _patch_chat(lambda messages, response_format=None, **kw: "not json at all")
    try:
        try:
            llm.chat_structured([], _Item)
            raise AssertionError("应抛 ValueError")
        except ValueError as e:
            assert "重试后仍失败" in str(e), e
    finally:
        llm.chat = orig
    print("重试后仍失败抛 ValueError: OK")


if __name__ == "__main__":
    test_success()
    test_retry_after_bad_json()
    test_repair_trailing_comma()
    test_retry_after_validation_error()
    test_fails_after_retries()
    print("\n全部 llm JSON 数据层测试通过")
