"""生成一篇只使用基础素材的纯 LLM 正文，用于与 Story_Agent 结果对比。"""

import argparse
import json
import os
import sys
import time

from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from FunctionExtract_Agent.llm import chat_structured


SOURCE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "story_eval_modern_reasoning_high_20260828T",
    "现代情感_20260828T000710_story_20260828T113744.json",
)
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "story_eval_pure_llm_20260828T")


class DirectStory(BaseModel):
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)


PROMPT = """你是中文短篇小说作者。根据用户提供的基础素材，独立创作一篇完整的现代情感短篇小说。

只输出 JSON，字段严格为：{{"title":"自然标题","text":"完整正文"}}。

要求：
1. 使用第三人称限知视角，以女主为中心；
2. 正文至少 {min_chars} 个、最好 {target_min}—{target_max} 个中文字符；未达到 {min_chars} 字不要结束，完整呈现铺垫、冲突升级、人物动机、情感递进、高潮和结局；
3. 基础素材是创作边界：不得新增与核心冲突无关的主线、核心人物或另一套结局；
4. 让人物通过具体行动和选择推进故事，避免用概述替代关键场面；
5. 结尾必须实际完成结局方向中的解决动作，明确消除威胁、回应核心冲突，并展示人物关系和生活进入的稳定状态；
6. 不要出现“Function”、结构分析、场景编号、系统说明或写作说明。"""


def main():
    parser = argparse.ArgumentParser(description="生成纯 LLM 正文对照")
    parser.add_argument("--outline-json", default=SOURCE_PATH)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--min-chars", type=int, default=6000)
    parser.add_argument("--target-min", type=int, default=6200)
    parser.add_argument("--target-max", type=int, default=6800)
    args = parser.parse_args()
    with open(args.outline_json, encoding="utf-8") as f:
        document = json.load(f)
    source = document.get("source_outline", document)
    material = {
        "genre": source["genre"],
        "world_setting": source["seed"]["world_setting"],
        "characters": source["seed"]["characters"],
        "core_conflict": source["seed"]["core_conflict"],
        "ending_direction": source["seed"]["ending_direction"],
    }
    story = chat_structured([
        {"role": "system", "content": PROMPT.format(**vars(args))},
        {"role": "user", "content": json.dumps(material, ensure_ascii=False)},
    ], DirectStory, reasoning_effort="medium").model_dump()
    os.makedirs(args.out_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    stem = f"{source['genre']}_纯LLM_story_{timestamp}"
    text = story["text"]
    result = {
        "source_story": os.path.abspath(args.outline_json),
        "mode": "pure_llm_direct",
        "reasoning_effort": "medium",
        "input_material": material,
        "story": story,
        "chinese_char_count": sum("\u4e00" <= ch <= "\u9fff" for ch in text),
    }
    json_path = os.path.join(args.out_dir, stem + ".json")
    md_path = os.path.join(args.out_dir, stem + ".md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {story['title']}\n\n{text}\n")
    print(f"[PureLLM] result={json_path}")
    print(f"[PureLLM] markdown={md_path}")
    print(f"[PureLLM] chinese_char_count={result['chinese_char_count']}")


if __name__ == "__main__":
    main()
