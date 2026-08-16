"""Pre-Processor 测试（离线）：规则工具直测 + mock LLM 验证 LLM 路径与兜底"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import Agent.Pre_pro.pre_processor as pp
from Agent.Pre_pro.pre_processor import (
    _clean_lines,
    _join_paragraphs,
    _split_sentences,
    preprocessor_node,
    NormalizedResult,
)


def _with_mock_llm(fake, fn):
    original = pp.chat_structured
    pp.chat_structured = lambda messages, schema, **kw: fake
    try:
        return fn()
    finally:
        pp.chat_structured = original


def test_clean_lines_markers():
    # 孤立数字标记（含全角）剔除；碎片式内容数字保留
    cleaned = _clean_lines("01\n第一段。\n４\n第二段！\n７．\n第三段？\n23\n：\n58\n")
    assert cleaned == ["第一段。", "第二段！", "第三段？", "23", "：", "58"], cleaned
    print("规则 _clean_lines 标记剔除/内容保留: OK")


def test_join_paragraphs_fragments():
    lines = ["我拿着星卡", "，", "紧张地递给人员看", "。", "他上下打量了我一下", "，", "侧过了身", "。"]
    paras = _join_paragraphs(lines)
    assert paras == ["我拿着星卡，紧张地递给人员看。", "他上下打量了我一下，侧过了身。"], paras
    print("规则 _join_paragraphs 碎片拼接: OK")


def test_split_sentences_quote_merge():
    # 纯引号碎片并入前句 + 句首闭合引号移回前句
    assert _split_sentences("他说道：“我们需要一根桅杆。”") == ["他说道：“我们需要一根桅杆。”"]
    assert _split_sentences("“快跑！”他说。") == ["“快跑！”", "他说。"]
    assert _split_sentences("她说：“你好。”然后走了。") == ["她说：“你好。”", "然后走了。"]
    print("规则 _split_sentences 引号边界: OK")


def test_llm_path():
    fake = NormalizedResult(
        segments=[{"id": "seg_0", "content": "第一句。第二句！", "sentence_indices": [0, 1]}],
        sentences=["第一句。", "第二句！"],
        paragraph_count=1,
    )
    result = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": "第一句。第二句！", "story_config": {"story_id": "s1"}}))
    ns = result["normalized_story"]
    assert ns["sentences"] == ["第一句。", "第二句！"], ns["sentences"]
    assert ns["paragraph_count"] == 1
    assert ns["segments"][0]["segment_id"] == "s1_seg_0", ns["segments"][0]["segment_id"]
    assert ns["segments"][0]["sentence_indices"] == [0, 1]
    print("LLM 主路径（mock）: OK")


def test_llm_fallback_rule_split():
    # LLM 返回空 sentences 时，按段规则切句兜底
    fake = NormalizedResult(
        segments=[{"id": "seg_0", "content": "他说道：“我们需要一根桅杆。”", "sentence_indices": []}],
        sentences=[],
        paragraph_count=1,
    )
    result = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": "他说道：“我们需要一根桅杆。”", "story_config": {"story_id": "s1"}}))
    ns = result["normalized_story"]
    assert ns["sentences"] == ["他说道：“我们需要一根桅杆。”"], ns["sentences"]
    print("LLM 空输出规则兜底: OK")


def test_stable_story_id():
    fake = NormalizedResult(segments=[], sentences=[], paragraph_count=0)
    r1 = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": "同样的故事开头。", "story_config": {}}))
    r2 = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": "同样的故事开头。", "story_config": {}}))
    sid1 = r1["normalized_story"]["metadata"]["story_id"]
    sid2 = r2["normalized_story"]["metadata"]["story_id"]
    assert sid1 == sid2, (sid1, sid2)
    r3 = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": "同样的故事开头。", "story_config": {"story_id": "custom01"}}))
    assert r3["normalized_story"]["metadata"]["story_id"] == "custom01"
    print(f"稳定 story_id: {sid1} / 显式覆盖 OK")


def test_prompt_import():
    from Prompt.Pre_prompt import PREPROCESSOR_SYSTEM_PROMPT
    assert "segments" in PREPROCESSOR_SYSTEM_PROMPT and "sentences" in PREPROCESSOR_SYSTEM_PROMPT
    print("Pre_prompt 恢复可导入: OK")


def test_empty():
    called = []
    original = pp.chat_structured
    pp.chat_structured = lambda *a, **k: called.append(1) or None
    try:
        result = preprocessor_node({"raw_text": "", "story_config": {}})
    finally:
        pp.chat_structured = original
    assert result["normalized_story"] is None
    assert called == [], "空输入不应调用 LLM"
    print("空输入兜底（不调用 LLM）: OK")



def test_llm_collapse_fallback():
    # LLM 把整篇塞进 1 句（塌缩）时，改用规则切句兜底
    raw = "第一句。\n第二句！\n第三句？\n第四句。\n第五句。\n第六句。\n第七句。\n第八句。"
    fake = NormalizedResult(
        segments=[{"id": "seg_0", "content": raw.replace("\n", ""), "sentence_indices": []}],
        sentences=[raw.replace("\n", "")],
        paragraph_count=1,
    )
    result = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": raw, "story_config": {"story_id": "s1"}}))
    ns = result["normalized_story"]
    assert len(ns["sentences"]) >= 8, ns["sentences"]
    assert ns["sentences"][0] == "第一句。", ns["sentences"][0]
    print("LLM 分句塌缩规则兜底: OK")


def test_llm_not_collapsed_kept():
    # 正常 LLM 分句（句子数≈标点数）不被误判
    raw = "第一句。\n第二句！\n第三句？\n第四句。\n第五句。\n第六句。\n第七句。\n第八句。"
    sents = ["第一句。", "第二句！", "第三句？", "第四句。", "第五句。", "第六句。", "第七句。", "第八句。"]
    fake = NormalizedResult(
        segments=[{"id": "seg_0", "content": raw.replace("\n", ""), "sentence_indices": list(range(8))}],
        sentences=sents,
        paragraph_count=1,
    )
    result = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": raw, "story_config": {"story_id": "s1"}}))
    ns = result["normalized_story"]
    assert len(ns["sentences"]) == 8, ns["sentences"]
    print("正常 LLM 分句保留: OK")


if __name__ == "__main__":
    test_clean_lines_markers()
    test_join_paragraphs_fragments()
    test_split_sentences_quote_merge()
    test_llm_path()
    test_llm_fallback_rule_split()
    test_llm_collapse_fallback()
    test_llm_not_collapsed_kept()
    test_stable_story_id()
    test_prompt_import()
    test_empty()
    print("所有测试通过!")