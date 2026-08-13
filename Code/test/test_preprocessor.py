"""Pre-Processor 测试"""

import sys
from pre_processor import preprocessor_node, PreProcessorState


def test_preprocessor():
    if len(sys.argv) < 2:
        print("用法: python test_preprocessor.py <story_file.txt>")
        return

    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        raw_text = f.read()

    state = PreProcessorState(
        messages=[{"role": "user", "content": raw_text}],
        normalized_story=None
    )
    config = {"configurable": {"story_id": "test_001", "story_type": "fantasy"}}
    result = preprocessor_node(state, config)

    ns = result["normalized_story"]
    print(f"段落数: {ns['paragraph_count']}, 句子数: {len(ns['sentences'])}")
    for i, sent in enumerate(ns["sentences"], 1):
        print(f"  {i}. {sent}")


if __name__ == "__main__":
    test_preprocessor()
