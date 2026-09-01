"""生成不暴露方案标题和 Function 名称的盲评稿副本。"""

import argparse
import os
import re


def neutralize(text):
    lines = []
    for line in text.splitlines():
        if re.match(r"^# (?!盲评稿：).+", line):
            continue
        match = re.match(r"^## (\d+)\. .+$", line)
        if match:
            line = f"## 第{match.group(1)}段"
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--source-dir", default="")
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.abspath(os.path.join(here, "..", "data"))
    source = args.source_dir or os.path.join(
        data_dir, "outline_eval", args.snapshot_id, "comparison"
    )
    target = args.out_dir or os.path.join(
        data_dir, "outline_eval", args.snapshot_id, "blind_review_v1"
    )
    os.makedirs(target, exist_ok=True)

    for name in ("悬疑惊悚.md", "现代情感.md", "末世科幻.md"):
        with open(os.path.join(source, name), encoding="utf-8") as handle:
            content = handle.read()
        with open(os.path.join(target, name), "w", encoding="utf-8") as handle:
            handle.write(neutralize(content))
    print(target)


if __name__ == "__main__":
    main()
