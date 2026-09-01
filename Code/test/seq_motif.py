"""Function 序列生成 + 套路统计工具（Propp 式分析第一步）

从 functions.db（Registry 指定命名空间）的 supporting_obs_ids 反推每篇故事的
Function 序列（obs_id = {story_id}_obs_{序号}，按序号即故事内顺序），
保留每个 Function 的出现次数/位置（供重复结构统计使用），附题材映射。

产物（data/sequences/）：
  sequences.jsonl  每篇：story_id / category / sequence（结构演变，压缩连续重复）
                    / events（每个 Function 的出现次数与位置）/ length

用法（Code/ 下）：
    python -X utf8 test/seq_motif.py [--namespace evolve_official] [--out-dir data/sequences]
"""

import argparse
import io
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.Registry.registry import RegistryStore

DEFAULT_CORPUS = "zhihu_story_subset_60_5domains_20260819_clean"


def load_sequences(namespace: str) -> dict[str, dict]:
    """从 Registry 提取每篇故事的 Function 序列（保留重复信息）。"""
    funcs = RegistryStore(namespace=namespace).load_all()
    per_story: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for f in funcs:
        name = f.get("function_name", "")
        for oid in f.get("supporting_obs_ids", []):
            m = re.match(r"(.+)_obs_(\d+)$", oid)
            if m:
                per_story[m.group(1)].append((int(m.group(2)), name))
    out = {}
    for sid, items in per_story.items():
        items = sorted(items)
        seq = [name for _, name in items]  # 原始序列（含连续重复）
        # 压缩连续重复：结构演变序列
        collapsed = []
        for x in seq:
            if not collapsed or collapsed[-1] != x:
                collapsed.append(x)
        # events：每个 Function 出现次数与位置
        events = []
        seen = set()
        for i, name in enumerate(seq):
            if name in seen:
                continue
            seen.add(name)
            positions = [j for j, n in enumerate(seq) if n == name]
            events.append({
                "function": name,
                "count": len(positions),
                "positions": positions,
            })
        out[sid] = {
            "story_id": sid,
            "sequence": collapsed,
            "events": events,
            "length": len(collapsed),
        }
    return out


def load_categories(corpus: str, base: str) -> dict[str, str]:
    """manifest -> story_id -> category。"""
    manifest = os.path.join(base, corpus, "manifest.json")
    if not os.path.exists(manifest):
        return {}
    mapping = {}
    with io.open(manifest, "r", encoding="utf-8") as f:
        for e in json.load(f):
            txt = e.get("txt_file", "").replace("\\", "/")
            mapping[os.path.splitext(os.path.basename(txt))[0]] = e.get("category")
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description="Function 序列生成 + 套路统计")
    parser.add_argument("--namespace", default="evolve_official")
    parser.add_argument("--out-dir", default="data/sequences")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    args = parser.parse_args()

    root = os.path.join(os.path.dirname(__file__), "..")
    seqs = load_sequences(args.namespace)
    cats = load_categories(args.corpus, root)
    for sid, s in seqs.items():
        s["category"] = cats.get(sid)
    os.makedirs(args.out_dir, exist_ok=True)
    dst = os.path.join(args.out_dir, "sequences.jsonl")
    with io.open(dst, "w", encoding="utf-8") as f:
        for sid in sorted(seqs):
            f.write(json.dumps(seqs[sid], ensure_ascii=False) + "\n")
    print(f"sequences written: {len(seqs)} 篇 → {dst}")
    for sid in sorted(seqs)[:3]:
        s = seqs[sid]
        print(f"  [{s['category']}] {sid}: " + " → ".join(s["sequence"]))
    from collections import Counter
    cat_count = Counter(s["category"] for s in seqs.values())
    print("题材分布:", dict(cat_count))


if __name__ == "__main__":
    main()
