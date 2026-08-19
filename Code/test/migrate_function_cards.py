"""一次性迁移：给现有 O_0 补 Function Card 字段（function_id/status/version_history）并同步快照。

用法（Code/ 下）：
    python -X utf8 test/migrate_function_cards.py [namespace] [snapshot]
默认 namespace=bootstrap、snapshot=data/bootstrap/functions_bootstrap.jsonl。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.Registry.registry import RegistryStore


def main() -> None:
    ns = sys.argv[1] if len(sys.argv) > 1 else "bootstrap"
    snapshot = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(__file__), "..", "data", "bootstrap", f"functions_{ns}.jsonl"
    )
    store = RegistryStore(namespace=ns)
    funcs = store.load_all()
    store.replace_all(funcs)  # replace_all 内幂等 enrich
    after = store.load_all()
    missing = sum(
        1 for f in after
        if not f.get("function_id") or not f.get("status") or not f.get("version_history")
    )
    print(f"namespace={ns}: {len(funcs)} -> {len(after)} functions, missing_card_fields={missing}")
    for f in after[:3]:
        print(f"  - {f.get('function_name')} id={f.get('function_id')} "
              f"status={f.get('status')} v={len(f.get('version_history', []))}")
    if os.path.exists(snapshot):
        store.export_jsonl(snapshot)
        print(f"  已同步快照 -> {snapshot}")
    if missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
