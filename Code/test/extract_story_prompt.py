"""从结构化正文产物重建 write_story 的可复制 prompt。"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Story_Agent.Prompt.Story_prompt import STORY_PROMPT


DEFAULT_SOURCE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "story_eval_modern_reasoning_high_20260828T",
    "现代情感_20260828T000710_story_20260828T113744.json",
)
DEFAULT_OUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "data", "story_prompt_extract_20260828T"
)


def build_payload(document):
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
    parser = argparse.ArgumentParser(description="提取结构化正文的完整故事 prompt")
    parser.add_argument("--structured-json", default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    with open(args.structured_json, encoding="utf-8") as f:
        document = json.load(f)
    payload = build_payload(document)
    prompt = (
        "SYSTEM PROMPT\n"
        "============\n"
        f"{STORY_PROMPT}\n\n"
        "USER INPUT JSON\n"
        "===============\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
    )

    os.makedirs(args.out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.structured_json))[0]
    path = os.path.join(args.out_dir, stem + "_story_prompt.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt)
    print(path)
    print(f"prompt_chars={len(prompt)}")


if __name__ == "__main__":
    main()
