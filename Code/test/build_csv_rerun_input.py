"""一次性：从 functions.csv 生成 CSV-derived 重跑输入（新 namespace，不写回 evolve_official）。
去重规则（HANDOFF 2026-08-20）：共享名称优先 evolve_official 卡片 + bootstrap 独有 Function。

用法:
    python test/build_csv_rerun_input.py            # dry-run 打印去重结果
    python test/build_csv_rerun_input.py --apply    # 生成 JSONL + 导入新 namespace
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "data", "registry", "functions.csv")
NS = "csv_rerun"
OUT_JSONL = os.path.join(ROOT, "data", "registry", f"functions_{NS}_input.jsonl")


def load_deduped() -> tuple[list[dict], dict[str, str]]:
    rows = []
    with open(CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    by_name = {}
    src = {}
    for r in rows:
        name = r["function_name"]
        payload = json.loads(r["payload"])
        if name not in by_name:
            by_name[name] = payload
            src[name] = r["namespace"]
        elif r["namespace"] == "evolve_official":
            by_name[name] = payload
            src[name] = "evolve_official"
    return list(by_name.values()), src


def main() -> None:
    parser = argparse.ArgumentParser(description="CSV → 35 个唯一 Function 重跑输入")
    parser.add_argument("--apply", action="store_true", help="生成 JSONL 并导入新 namespace")
    args = parser.parse_args()

    funcs, src = load_deduped()
    names = [f["function_name"] for f in funcs]
    ids = [f["function_id"] for f in funcs]
    assert len(names) == len(set(names)), "function_name 不唯一"
    assert len(ids) == len(set(ids)), "function_id 不唯一"
    assert all(f.get("definition") for f in funcs), "存在空 definition"
    print(f"CSV-derived 重跑输入: {len(funcs)} 个唯一 Function（name/id 均唯一）")
    print(f"来源分布: {dict(Counter(src.values()))}")

    if not args.apply:
        print("dry-run 完成（未写文件/未导入），加 --apply 执行导入")
        return

    os.makedirs(os.path.dirname(OUT_JSONL), exist_ok=True)
    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for fn in funcs:
            f.write(json.dumps(fn, ensure_ascii=False) + "\n")
    print(f"输入已写入: {OUT_JSONL}")

    sys.path.insert(0, ROOT)
    from FunctionExtract_Agent.Registry.registry import RegistryStore
    store = RegistryStore(namespace=NS)
    store.replace_all(funcs)
    print(f"已导入 namespace={NS}: {store.count()} 个 Function")


if __name__ == "__main__":
    main()
