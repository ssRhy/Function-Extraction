"""
Pre-Processor Node - 故事文本标准化（分句、分段）
LangGraph 范式
"""

import uuid
import re
from datetime import datetime
from pydantic import BaseModel, Field

from Agent.state import NarrativePipelineState
from Agent.llm import chat_structured
from Prompt.Pre_prompt import PREPROCESSOR_SYSTEM_PROMPT


# ========== Pydantic Schema ==========

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


# ============================================================
# Node 函数 - LangGraph 范式
# ============================================================

def preprocessor_node(state: NarrativePipelineState) -> NarrativePipelineState:
    """
    Pre-Processor 节点

    输入: raw_text + story_config
    输出: normalized_story

    LangGraph 自动处理：
    - 状态字段直接覆盖返回
    - messages 通过 add_messages 自动追加
    """
    raw_text = state.get("raw_text")
    story_config = state.get("story_config", {})

    if not raw_text:
        return {"normalized_story": None, "messages": []}

    # 提取配置
    story_id = story_config.get("story_id") or str(uuid.uuid4())[:8]
    story_type = story_config.get("story_type", "unknown")
    title = story_config.get("title", "")

    if not title:
        first_line = raw_text.split('\n')[0].strip()
        title = first_line if len(first_line) < 50 else f"story_{story_id}"

    # 调用 LLM
    result = chat_structured(
        [
            {"role": "system", "content": PREPROCESSOR_SYSTEM_PROMPT},
            {"role": "user", "content": raw_text.strip()}
        ],
        NormalizedResult
    )

    segments = [{
        "segment_id": f"{story_id}_{seg.get('segment_id', f'seg_{i}')}",
        "content": seg.get("content", ""),
        "sentence_indices": seg.get("sentence_indices", [])
    } for i, seg in enumerate(result.segments)]

    sentences = result.sentences
    if not sentences:
        # LLM 长输出时常丢空 sentences 字段，从 segments.content 按标点兜底切句
        import re
        sentences = [s.strip() for seg in segments for s in re.split(r'(?<=[。！？])', seg["content"]) if s.strip()]

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
