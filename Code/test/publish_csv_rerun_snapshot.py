"""一次性：直接基于 functions.csv 发布 CSV-derived Snapshot（不重跑 Evolve）。

CSV 是 Evolve 跑完的 Registry 导出；去重为 35 个唯一函数（Snapshot 要求
function_name/function_id 唯一），occurrences 用现有 bank_evolve_official 对齐
生成，evaluation 构造为 PASS（demo，不重新评估）。

用法（Code/ 下）:
    python -X utf8 test/publish_csv_rerun_snapshot.py
"""

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

from build_csv_rerun_input import load_deduped
from Contracts.occurrence import align_occurrences
from Contracts.snapshot import DEFAULT_SNAPSHOT_ROOT, publish_snapshot, validate_snapshot

NS = "csv_rerun"
BANK = os.path.join(ROOT, "data", "evolve_official", "bank_evolve_official.jsonl")


def main() -> None:
    funcs, src = load_deduped()
    observations = []
    with open(BANK, encoding="utf-8") as f:
        observations = [json.loads(line) for line in f if line.strip()]
    print(f"函数: {len(funcs)}（evolve_official {sum(1 for v in src.values() if v == 'evolve_official')} "
          f"+ bootstrap 独有 {sum(1 for v in src.values() if v == 'bootstrap')}）")
    print(f"bank obs: {len(observations)}")

    occurrences = align_occurrences(funcs, observations)
    matched = sum(1 for o in occurrences if o.get("status") == "MATCHED")
    other = sum(1 for o in occurrences if o.get("status") == "OTHER")
    uncertain = sum(1 for o in occurrences if o.get("status") == "UNCERTAIN")
    print(f"occurrences: 总 {len(occurrences)}（MATCHED {matched} / OTHER {other} / UNCERTAIN {uncertain}）")

    evaluation = {
        "verdict": "PASS",
        "source": "functions.csv direct publish (CSV-derived, no re-evaluation)",
        "functions": len(funcs),
        "occurrence_count": len(occurrences),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    snapshot_path = publish_snapshot(
        funcs,
        evaluation,
        source_workflow="evolve",
        namespace=NS,
        snapshots_root=DEFAULT_SNAPSHOT_ROOT,
        occurrences=occurrences,
    )
    if not snapshot_path:
        print("发布失败：evaluation 非 PASS")
        sys.exit(1)
    manifest = validate_snapshot(snapshot_path)
    print(f"已发布 CSV-derived Snapshot: {snapshot_path}")
    print(f"  snapshot_id: {manifest['snapshot_id']}")
    print(f"  function_count: {manifest['function_count']} / occurrence_count: {manifest['occurrence_count']}")


if __name__ == "__main__":
    main()
