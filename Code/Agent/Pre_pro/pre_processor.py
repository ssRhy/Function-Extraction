"""
Pre-Processor Node - 故事文本标准化（分句、分段）

LLM 实现：调用 LLM 按叙事结构分句/分段（保留原文，不改写）。
规则兜底：LLM 输出缺失/解析失败，或分句塌缩（整篇被塞进 1-2 句）时，
对每个段落按 。！？ 切句（_split_sentences）。
行清洗/段落合并工具（_clean_lines/_join_paragraphs/_split_sentences）同时被
clean_corpus.py 复用，因此保留在此。
"""

import re
import hashlib
from datetime import datetime
from pydantic import BaseModel, Field

from Agent.state import NarrativePipelineState
from Agent.llm import chat_structured
from Prompt.Pre_prompt import PREPROCESSOR_SYSTEM_PROMPT

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？])")
# 句末标点（可带闭合引号）：用于判断段落是否已收束
_FINAL_PUNCT_RE = re.compile(r"[。！？!?…]+[”」』]?$")
# 纯闭合引号/引号行：并入当前段落（不触发收束）
_QUOTE_ONLY_RE = re.compile(r"^[”」』“「『]+$")
# 章节/列表数字标记行（如 01、1、1.、1、1．，含全角数字/全角点）
_MARKER_RE = re.compile(r"^[\d０-９]{1,3}([.、．])?$")
# 纯标点/装饰行（用于判断数字行是否为"孤立"章节标记）
_PUNCT_ONLY_RE = re.compile(r"^[，。！？：；、「」『』“”（）()…·\-—\s]*$")


def _stable_story_id(raw_text: str) -> str:
    """无显式 story_id 时的稳定回退：原文前50字符的 sha256 前8位"""
    return hashlib.sha256(raw_text[:50].encode("utf-8")).hexdigest()[:8]


def _clean_lines(raw_text: str) -> list[str]:
    """清洗行：去空白/零宽字符；仅剔除"孤立"数字标记行。

    孤立判定：数字行前后都不是纯标点行——此时它才是章节/列表标记
    （如整段式文本中的 01/1/1.）。碎片式文本中独立数字常是正文内容
    （如时间 23：58 被拆成 23 / ： / 58 三行），此时前后必夹标点行，保留。

    局限：该启发式无法区分"独立的年份/编号段落"与"章节标记"，在极少数
    整段式文本中可能误删独立成行的年份/编号；语料实测仅影响章节标记，可接受。
    """
    lines = []
    for ln in raw_text.splitlines():
        s = ln.strip().replace("\u200b", "").strip()
        if not s:
            continue
        lines.append(s)

    def is_isolated_marker(i: int) -> bool:
        if not _MARKER_RE.match(lines[i]):
            return False
        for j in (i - 1, i + 1):
            if 0 <= j < len(lines) and _PUNCT_ONLY_RE.fullmatch(lines[j]):
                return False
        return True

    return [ln for i, ln in enumerate(lines) if not is_isolated_marker(i)]


def _join_paragraphs(lines: list[str]) -> list[str]:
    """把行流合并为段落：段落以句末标点收束；碎片式行自动拼接。"""
    paragraphs = []
    buf: list[str] = []
    for ln in lines:
        if buf and _FINAL_PUNCT_RE.search(buf[-1]) and not _QUOTE_ONLY_RE.match(ln):
            paragraphs.append("".join(buf))
            buf = []
        buf.append(ln)
    if buf:
        paragraphs.append("".join(buf))
    return paragraphs


def _split_sentences(para: str) -> list[str]:
    """按句末标点切句，并修复引号边界：

    - 纯引号碎片并入前一句（'“我们需要一根桅杆。”' 切出 ['…。', '”'] → 还原单句）；
    - 句首闭合引号移回前一句（'“快跑！”他说。' 切出 ['“快跑！', '”他说。'] → ['“快跑！”', '他说。']）。
    两者都避免出现以孤立引号开头/成句的碎片。
    """
    _LEADING_QUOTE_RE = re.compile(r"^[”」』]+")
    sentences = []
    for part in _SENTENCE_SPLIT_RE.split(para):
        s = part.strip()
        if not s:
            continue
        if sentences and _QUOTE_ONLY_RE.fullmatch(s):
            sentences[-1] += s
            continue
        if sentences and _FINAL_PUNCT_RE.search(sentences[-1]):
            m = _LEADING_QUOTE_RE.match(s)
            if m:
                sentences[-1] += m.group(0)
                s = s[m.end():]
                if not s:
                    continue
        sentences.append(s)
    return sentences


_SENTENCE_END_RE = re.compile(r"[。！？!?]")


def _is_collapsed_sentences(sentences: list[str], raw_text: str) -> bool:
    """检测 LLM 分句塌缩：返回句子数远少于文本应有的句末标点数。

    正常 LLM 分句句子数 ≈ 句末标点数；塌缩时会把整篇塞进 1-2 个"句子"。
    阈值：句子数 < 标点数 / 3，且标点数 >= 8，视为塌缩。
    """
    ends = len(_SENTENCE_END_RE.findall(raw_text))
    return ends >= 8 and len(sentences) * 3 < ends


def _rule_normalized_result(raw_text: str):
    """按行分段 + 。！？ 切句构造 NormalizedResult（无 LLM 的规则兜底）。"""
    paragraphs = _join_paragraphs(_clean_lines(raw_text))
    sentences: list[str] = []
    segs: list[dict] = []
    for i, para in enumerate(paragraphs):
        start = len(sentences)
        sentences.extend(_split_sentences(para))
        segs.append({
            "id": f"seg_{i}",
            "content": para,
            "sentence_indices": list(range(start, len(sentences)))
        })
    return NormalizedResult(segments=segs, sentences=sentences, paragraph_count=len(paragraphs))


class NormalizedResult(BaseModel):
    segments: list[dict] = Field(default_factory=list)
    sentences: list[str] = Field(default_factory=list)
    paragraph_count: int = Field(default=0)

    def model_post_init(self, _):
        normalized = []
        for i, seg in enumerate(self.segments):
            seg = dict(seg)
            seg.setdefault("segment_id", seg.pop("id", f"seg_{i+1}"))
            seg.setdefault("content", seg.pop("sentences", ""))
            normalized.append(seg)
        object.__setattr__(self, "segments", normalized)


def preprocessor_node(state: NarrativePipelineState) -> NarrativePipelineState:
    """
    Pre-Processor 节点

    输入: raw_text + story_config
    输出: normalized_story

    先调用 LLM 做结构化分句/分段；若 LLM 输出缺失 sentences（长输出常见），
    用规则切句（_split_sentences）对每个段落兜底。
    """
    raw_text = state.get("raw_text")
    story_config = state.get("story_config", {})

    if not raw_text:
        return {"normalized_story": None, "messages": []}

    story_id = story_config.get("story_id") or _stable_story_id(raw_text)
    story_type = story_config.get("story_type", "unknown")
    title = story_config.get("title", "")

    if not title:
        first_line = raw_text.split("\n")[0].strip()
        title = first_line if len(first_line) < 50 else f"story_{story_id}"

    # 调用 LLM（偶发输出失控/截断导致 JSON 解析失败：重试 1 次，仍失败则规则切句兜底）
    result = None
    for attempt in range(2):
        try:
            result = chat_structured(
                [
                    {"role": "system", "content": PREPROCESSOR_SYSTEM_PROMPT},
                    {"role": "user", "content": raw_text.strip()}
                ],
                NormalizedResult
            )
            break
        except ValueError:
            print(f"  [Pre-Processor] LLM 分句 JSON 解析失败（第 {attempt + 1} 次），重试...")
    if result is None:
        print("  [Pre-Processor] LLM 分句两次失败，改用规则切句（。！？）兜底")
        result = _rule_normalized_result(raw_text)
    elif _is_collapsed_sentences(result.sentences, raw_text):
        print("  [Pre-Processor] 检测到 LLM 分句塌缩，改用规则切句兜底")
        result = _rule_normalized_result(raw_text)
    elif not result.sentences:
        print("  [Pre-Processor] LLM 输出缺少 sentences，改用规则切句兜底")
        result = _rule_normalized_result(raw_text)

    segments = [{
        "segment_id": f"{story_id}_{seg.get('segment_id', f'seg_{i}')}",
        "content": seg.get("content", ""),
        "sentence_indices": seg.get("sentence_indices", [])
    } for i, seg in enumerate(result.segments)]

    sentences = result.sentences
    paragraph_count = result.paragraph_count or len(segments)

    metadata = {
        "story_id": story_id,
        "story_type": story_type,
        "title": title,
        "processed_at": datetime.now().isoformat()
    }

    normalized = {
        "metadata": metadata,
        "raw_text": raw_text,
        "segments": segments,
        "sentences": sentences,
        "paragraph_count": paragraph_count
    }

    return {
        "normalized_story": normalized,
        "messages": [{
            "role": "system",
            "content": f"[Pre-Processor] 完成 (ID={story_id}, 段落={len(segments)}, 句子={len(sentences)})"
        }]
    }