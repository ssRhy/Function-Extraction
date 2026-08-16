"""
RegistryStore - Function Registry 持久化存储（SQLite，命名空间隔离）

每批（题材）写入独立 namespace，互不清除；payload 整存完整 JSON（字段无损，
未来加 function_id/status/version_history 无需迁移存储层）。JSONL 仍是快照/交换格式，
由 export_jsonl / import_jsonl 负责与 run_bootstrap.py 快照/导入对接。
"""

import json
import os
import sqlite3
from contextlib import closing

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "registry", "functions.db"
)


class RegistryStore:
    """SQLite 后端 Registry：load/replace/clear/count/list/export/import，均按 namespace 隔离。"""

    def __init__(self, db_path: str | None = None, namespace: str = "default"):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.namespace = namespace
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    # ---------- 连接与建表 ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS functions (
                    namespace     TEXT NOT NULL,
                    function_name TEXT NOT NULL,
                    definition    TEXT NOT NULL,
                    payload       TEXT NOT NULL,
                    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (namespace, function_name)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_functions_namespace ON functions(namespace)"
            )

    def _insert_rows(self, namespace: str, funcs: list[dict]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM functions WHERE namespace=?", (namespace,))
            conn.executemany(
                "INSERT OR REPLACE INTO functions (namespace, function_name, definition, payload) VALUES (?,?,?,?)",
                [
                    (
                        namespace,
                        f.get("function_name", ""),
                        f.get("definition", ""),
                        json.dumps(f, ensure_ascii=False),
                    )
                    for f in funcs
                ],
            )

    # ---------- 读写 API ----------

    def load_all(self) -> list[dict]:
        """返回当前 namespace 全部函数（保持写入序）。"""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload FROM functions WHERE namespace=? ORDER BY rowid",
                (self.namespace,),
            ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def replace_all(self, funcs: list[dict]) -> None:
        """事务：清空当前 namespace 后全量写入（等价旧整文件重写）。"""
        self._insert_rows(self.namespace, funcs)

    def count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM functions WHERE namespace=?",
                (self.namespace,),
            ).fetchone()
        return int(row["n"])

    def clear(self) -> None:
        """仅清空当前 namespace，其他批次保留。"""
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM functions WHERE namespace=?", (self.namespace,))

    def list_namespaces(self) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT DISTINCT namespace FROM functions ORDER BY namespace"
            ).fetchall()
        return [r["namespace"] for r in rows]

    # ---------- JSONL 快照/交换 ----------

    def export_jsonl(self, dst_path: str) -> None:
        """导出当前 namespace 为 JSONL（供 run_bootstrap.py 快照等使用）。"""
        os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)
        funcs = self.load_all()
        with open(dst_path, "w", encoding="utf-8") as f:
            for func in funcs:
                f.write(json.dumps(func, ensure_ascii=False) + "\n")

    def import_jsonl(self, src_path: str, namespace: str) -> int:
        """把 JSONL 快照导入指定 namespace（幂等 replace），返回导入条数。"""
        funcs = []
        with open(src_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    funcs.append(json.loads(line))
        self._insert_rows(namespace, funcs)
        return len(funcs)


# ---------- 模块级活跃 store（run_bootstrap.py 启动时 set，Inducer/Evaluator/Revise 读写） ----------

_active_store: RegistryStore | None = None


def get_active_store() -> RegistryStore:
    global _active_store
    if _active_store is None:
        _active_store = RegistryStore()
    return _active_store


def set_active_store(store: RegistryStore | None) -> None:
    global _active_store
    _active_store = store
