"""直接复用结构化正文节点的完整 prompt，生成一篇对照正文。"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from FunctionExtract_Agent.llm import chat_structured
from Story_Agent.Prompt.Story_prompt import STORY_PROMPT
from Story_Agent.state import StoryDraft


DEFAULT_SOURCE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "story_eval_structured_scifi_20260828T",
    "末世科幻_20260828T000300_story_20260828T121750.json",
)
DEFAULT_OUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "data", "story_eval_extracted_prompt_20260828T"
)


def _load(path):
    with open(path, encoding="utf-8") as f:
        document = json.load(f)
    required = {
        "source_outline", "function_constraints", "scene_plan",
        "scene_developments", "story",
    }
    missing = sorted(required - set(document))
    if missing:
        raise ValueError(f"结构化正文产物缺少字段: {', '.join(missing)}")
    return document


def _build_input(document):
    source = document["source_outline"]
    return {
        "seed": source["seed"],
        "function_constraints": document["function_constraints"],
        "scene_plan": document["scene_plan"],
        "scene_developments": document["scene_developments"],
        "writing_requirements": {
            "min_chinese_chars": 3000,
        },
        "ending_spec": source.get("ending_spec"),
        "ending": source["outline"]["ending"],
    }


def main():
    parser = argparse.ArgumentParser(description="复用结构化正文 prompt 直接生成对照正文")
    parser.add_argument("--structured-json", default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    document = _load(args.structured_json)
    user_input = _build_input(document)
    story = chat_structured(
        [
            {"role": "system", "content": STORY_PROMPT},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
        ],
        StoryDraft,
        reasoning_effort="medium",
    ).model_dump()

    text = "\n\n".join(scene["text"] for scene in story["scenes"])
    chinese_char_count = sum("\u4e00" <= ch <= "\u9fff" for ch in text)
    baseline = document["story"]
    baseline_text = "\n\n".join(scene["text"] for scene in baseline["scenes"])
    baseline_count = sum("\u4e00" <= ch <= "\u9fff" for ch in baseline_text)

    os.makedirs(args.out_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    stem = f"{document['source_outline']['genre']}_提取prompt_story_{timestamp}"
    result = {
        "source_structured_story": os.path.abspath(args.structured_json),
        "mode": "extracted_story_prompt_direct",
        "reasoning_effort": "medium",
        "system_prompt": STORY_PROMPT,
        "input_payload": user_input,
        "story": story,
        "chinese_char_count": chinese_char_count,
        "length_ok": chinese_char_count >= 3000,
        "comparison": {
            "structured_chinese_char_count": baseline_count,
            "direct_chinese_char_count": chinese_char_count,
            "difference": chinese_char_count - baseline_count,
        },
    }
    json_path = os.path.join(args.out_dir, stem + ".json")
    md_path = os.path.join(args.out_dir, stem + ".md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {story['title']}\n\n{text}\n")
    print(f"[ExtractedPrompt] result={json_path}")
    print(f"[ExtractedPrompt] markdown={md_path}")
    print(f"[ExtractedPrompt] direct_chinese_char_count={chinese_char_count}")
    print(f"[ExtractedPrompt] structured_chinese_char_count={baseline_count}")
    print(f"[ExtractedPrompt] difference={chinese_char_count - baseline_count}")


if __name__ == "__main__":
    main()
