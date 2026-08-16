"""Pre-Processor 测试（离线）：规则工具直测 + mock LLM 验证 V3 混合切句路径与兜底"""

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
    PreCorrection,
)


def _with_mock_llm(fake, fn):
    original = pp.chat_structured
    pp.chat_structured = lambda messages, schema, **kw: fake
    try:
        return fn()
    finally:
        pp.chat_structured = original


def test_clean_lines_markers():
    cleaned = _clean_lines("01\n第一段。\n４\n第二段！\n７．\n第三段？\n23\n：\n58\n")
    assert cleaned == ["第一段。", "第二段！", "第三段？", "23", "：", "58"], cleaned
    print("规则 _clean_lines 标记剔除/内容保留: OK")


def test_join_paragraphs_fragments():
    lines = ["我拿着星卡", "，", "紧张地递给人员看", "。", "他上下打量了我一下", "，", "侧过了身", "。"]
    paras = _join_paragraphs(lines)
    assert paras == ["我拿着星卡，紧张地递给人员看。", "他上下打量了我一下，侧过了身。"], paras
    print("规则 _join_paragraphs 碎片拼接: OK")


def test_split_sentences_quote_merge():
    assert _split_sentences("他说道：“我们需要一根桅杆。”") == ["他说道：“我们需要一根桅杆。”"]
    assert _split_sentences("“快跑！”他说。") == ["“快跑！”", "他说。"]
    assert _split_sentences("她说：“你好。”然后走了。") == ["她说：“你好。”", "然后走了。"]
    print("规则 _split_sentences 引号边界: OK")


def test_llm_path():
    # V3 混合切句：规则切句生成候选 + LLM 只输出合并修正（不回显全文）
    fake = PreCorrection(merges=[[0, 1]])
    result = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": "第一句。第二句！", "story_config": {"story_id": "s1"}}))
    ns = result["normalized_story"]
    assert ns["sentences"] == ["第一句。第二句！"], ns["sentences"]
    assert ns["paragraph_count"] == 1
    assert ns["segments"][0]["segment_id"] == "s1_seg_0", ns["segments"][0]["segment_id"]
    assert ns["segments"][0]["sentence_indices"] == [0], ns["segments"][0]["sentence_indices"]
    print("V3 混合切句 LLM 修正路径（mock）: OK")


def test_llm_fallback_rule_split():
    # LLM 修正两次失败 → 规则切句兜底
    original = pp.chat_structured

    def _raise(*a, **k):
        raise ValueError("parse fail")

    pp.chat_structured = _raise
    try:
        result = preprocessor_node(
            {"raw_text": "他说道：“我们需要一根桅杆。”", "story_config": {"story_id": "s1"}})
    finally:
        pp.chat_structured = original
    ns = result["normalized_story"]
    assert ns["sentences"] == ["他说道：“我们需要一根桅杆。”"], ns["sentences"]
    print("LLM 修正失败规则兜底: OK")


def test_stable_story_id():
    fake = PreCorrection(merges=[], splits=[])
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
    from Prompt.Pre_prompt import PRE_HYBRID_SYSTEM_PROMPT
    assert "merges" in PRE_HYBRID_SYSTEM_PROMPT and "splits" in PRE_HYBRID_SYSTEM_PROMPT
    print("Pre_prompt 混合提示词可导入: OK")


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
    # LLM 把整篇合并成 1 句（塌缩）时，改用规则切句兜底
    raw = "第一句。\n第二句！\n第三句？\n第四句。\n第五句。\n第六句。\n第七句。\n第八句。"
    fake = PreCorrection(merges=[list(range(8))])
    result = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": raw, "story_config": {"story_id": "s1"}}))
    ns = result["normalized_story"]
    assert len(ns["sentences"]) >= 8, ns["sentences"]
    assert ns["sentences"][0] == "第一句。", ns["sentences"][0]
    print("混合切句塌缩规则兜底: OK")


def test_llm_not_collapsed_kept():
    # 正常修正（无合并/拆分）保留规则切句结果
    raw = "第一句。\n第二句！\n第三句？\n第四句。\n第五句。\n第六句。\n第七句。\n第八句。"
    fake = PreCorrection(merges=[], splits=[])
    result = _with_mock_llm(fake, lambda: preprocessor_node(
        {"raw_text": raw, "story_config": {"story_id": "s1"}}))
    ns = result["normalized_story"]
    assert len(ns["sentences"]) == 8, ns["sentences"]
    print("正常修正保留规则切句: OK")


if __name__ == "__main__":
    test_clean_lines_markers()
    test_join_paragraphs_fragments()
    test_split_sentences_quote_merge()
    test_llm_path()
    test_llm_fallback_rule_split()
    test_stable_story_id()
    test_prompt_import()
    test_empty()
    test_llm_collapse_fallback()
    test_llm_not_collapsed_kept()
    print("所有测试通过!")
