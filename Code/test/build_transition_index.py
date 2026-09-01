"""一次性构建 transition/realization index（确定性统计，零 LLM）。

从冻结快照 occurrences + Bank 统计：
- transitions: Function 邻接对（from->to 次数 + 支持故事数）
- mechanisms: 每个 Function 的真实实例机制（surface_form 去重 + 计数 + 样本 event）

用法（Code/ 下）：
    python -X utf8 test/build_transition_index.py [snapshot_dir] [bank_file] [out_dir]
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


_DEFAULT_SNAPSHOT = os.path.join(
    os.path.dirname(__file__), "..", "data", "ontology_snapshots",
    "evolve_250_20260822T063550401096Z_13b1bbda248f",
)
_DEFAULT_BANK = os.path.join(
    os.path.dirname(__file__), "..", "data", "evolve_250", "bank_evolve_250.jsonl",
)


def _obs_index(obs_id: str) -> int:
    match = re.fullmatch(r".+_obs_(\d+)", obs_id)
    return int(match.group(1)) if match else 0


def build_transitions(occurrences: list[dict]) -> list[dict]:
    """按故事恢复 MATCHED 序列，折叠连续重复，统计邻接对。"""
    by_story = defaultdict(list)
    for occ in occurrences:
        if occ.get("status") != "MATCHED":
            continue
        by_story[occ.get("story_id", "")].append(
            (_obs_index(occ["obs_id"]), occ["function_name"])
        )

    count = Counter()
    stories = defaultdict(set)
    for story, items in by_story.items():
        items.sort()
        prev = None
        for _, fn in items:
            if fn != prev:
                if prev is not None:
                    count[(prev, fn)] += 1
                    stories[(prev, fn)].add(story)
                prev = fn

    result = []
    for (src, dst), n in count.items():
        result.append({
            "from": src,
            "to": dst,
            "count": n,
            "support_stories": len(stories[(src, dst)]),
        })
    result.sort(key=lambda x: (-x["count"], x["from"], x["to"]))
    return result


def build_mechanisms(functions: list[dict], bank: dict) -> dict:
    """每个 Function 的实例机制：supporting ∩ Bank 的 surface_form 去重统计。"""
    result = {}
    for func in functions:
        seen = {}
        for obs_id in func.get("supporting_obs_ids", []):
            obs = bank.get(obs_id)
            surface_form = (obs or {}).get("surface_form", "")
            if not surface_form:
                continue
            entry = seen.setdefault(surface_form, {
                "surface_form": surface_form,
                "count": 0,
                "sample_event": obs.get("event", ""),
            })
            entry["count"] += 1
        mechanisms = sorted(seen.values(), key=lambda x: (-x["count"], x["surface_form"]))
        result[func["function_name"]] = {
            "function_id": func["function_id"],
            "mechanisms": mechanisms,
        }
    return result


def _load_jsonl(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_bank(path: str) -> dict:
    return {obs["obs_id"]: obs for obs in _load_jsonl(path)}


def main() -> None:
    snapshot_dir = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_SNAPSHOT
    bank_path = sys.argv[2] if len(sys.argv) > 2 else _DEFAULT_BANK
    out_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        os.path.dirname(__file__), "..", "data", "transition_index",
        os.path.basename(snapshot_dir),
    )
    os.makedirs(out_dir, exist_ok=True)

    functions = _load_jsonl(os.path.join(snapshot_dir, "functions.jsonl"))
    occurrences = _load_jsonl(os.path.join(snapshot_dir, "occurrences.jsonl"))
    bank = _load_bank(bank_path)
    transitions = build_transitions(occurrences)
    mechanisms = build_mechanisms(functions, bank)

    index = {
        "snapshot_id": os.path.basename(snapshot_dir),
        "transitions": transitions,
        "mechanisms": mechanisms,
    }
    out_path = os.path.join(out_dir, "transition_index.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"snapshot={os.path.basename(snapshot_dir)}")
    print(f"transitions={len(transitions)} 种邻接对")
    print(f"mechanisms 函数数={len(mechanisms)}")
    print(f"输出 -> {out_path}")


if __name__ == "__main__":
    main()
