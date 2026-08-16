"""导入 JSONL 快照到 RegistryStore 指定命名空间（幂等 replace）。

用法（在 Code/ 下）:
    python test/import_registry.py --registry data/evaluation/union_functions.jsonl --namespace union
    python test/import_registry.py --registry x.jsonl --namespace 01_悬疑惊悚 --db data/tmp.db
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.Registry.registry import RegistryStore


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 JSONL 快照到 Registry 命名空间")
    parser.add_argument("--registry", required=True, help="函数 JSONL 路径")
    parser.add_argument("--namespace", required=True, help="目标命名空间（幂等 replace）")
    parser.add_argument("--db", default=None, help="DB 路径（缺省 = 默认 functions.db）")
    args = parser.parse_args()

    store = RegistryStore(db_path=args.db)
    n = store.import_jsonl(args.registry, args.namespace)
    print(f"[import_registry] 导入 {n} 个函数 → 命名空间 {args.namespace}（DB: {store.db_path}）")
    print(f"[import_registry] 现有命名空间: {store.list_namespaces()}")


if __name__ == "__main__":
    main()