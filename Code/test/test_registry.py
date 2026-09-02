"""RegistryStore（SQLite）单元测试：CRUD / 命名空间隔离 / 字段无损 / JSONL 往返。"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from FunctionExtract_Agent.Registry.registry import RegistryStore


def _func(name="F_A", definition="测试定义", **extra):
    f = {
        "schema_version": 2,
        "function_name": name,
        "definition": definition,
        "realization_patterns": ["模式1"],
        "supporting_obs_ids": ["s1_obs1"],
        "confidence": 0.6,
    }
    f.update(extra)
    return f


def test_crud_roundtrip(tmp_path):
    store = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="ns1")
    assert store.count() == 0
    store.replace_all([_func(), _func("F_B")])
    assert store.count() == 2
    loaded = store.load_all()
    assert [f["function_name"] for f in loaded] == ["F_A", "F_B"]
    assert loaded[0]["definition"] == "测试定义"
    store.clear()
    assert store.count() == 0


def test_replace_all_is_transactional(tmp_path):
    store = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="ns1")
    store.replace_all([_func("F_A"), _func("F_B")])
    store.replace_all([_func("F_C")])
    loaded = store.load_all()
    assert [f["function_name"] for f in loaded] == ["F_C"]  # 旧行被整批替换
    assert store.count() == 1


def test_namespace_isolation(tmp_path):
    db = str(tmp_path / "f.db")
    a = RegistryStore(db_path=db, namespace="genre_a")
    b = RegistryStore(db_path=db, namespace="genre_b")
    a.replace_all([_func("TRUST_BETRAYAL")])
    b.replace_all([_func("TRUST_BETRAYAL"), _func("REVENGE")])  # 同名跨批共存
    assert a.count() == 1
    assert b.count() == 2
    assert sorted(RegistryStore(db_path=db).list_namespaces()) == ["genre_a", "genre_b"]
    a.clear()
    assert a.count() == 0
    assert b.count() == 2  # 只清本批
    assert sorted(RegistryStore(db_path=db).list_namespaces()) == ["genre_b"]


def test_payload_preserves_unknown_fields(tmp_path):
    store = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="ns1")
    store.replace_all([_func(function_id="F-001", status="provisional", version_history=[])])
    loaded = store.load_all()[0]
    assert loaded["function_id"] == "F-001"
    assert loaded["status"] == "provisional"
    assert loaded["version_history"] == []  # 显式空列表不被覆盖


def test_export_import_jsonl_roundtrip(tmp_path):
    db = str(tmp_path / "f.db")
    store = RegistryStore(db_path=db, namespace="ns1")
    funcs = [_func("F_A"), _func("F_B", extra_field="x")]
    store.replace_all(funcs)
    stored = store.load_all()  # replace_all 后（含 enrich 字段）
    dst = str(tmp_path / "out.jsonl")
    store.export_jsonl(dst)

    imported = RegistryStore(db_path=db, namespace="ns2")
    n = imported.import_jsonl(dst, "ns2")
    assert n == 2
    assert imported.load_all() == stored
    # 幂等：重复导入结果一致
    imported.import_jsonl(dst, "ns2")
    assert imported.count() == 2


def test_replace_all_enriches_card_fields(tmp_path):
    """replace_all 写入时幂等补齐 function_id / status / version_history。"""
    store = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="ns1")
    store.replace_all([_func("F_A")])
    f = store.load_all()[0]
    assert f["function_id"].startswith("F_") and len(f["function_id"]) == 10
    assert f["status"] == "provisional"
    assert f["version_history"][0]["version"] == 1 and f["version_history"][0]["action"] == "CREATE"


def test_enrich_idempotent_and_deterministic(tmp_path):
    """已有字段不覆盖；同名 Function 改定义仍保留相同 function_id。"""
    db = str(tmp_path / "f.db")
    store = RegistryStore(db_path=db, namespace="ns1")
    store.replace_all([_func("F_A")])
    first = store.load_all()[0]
    store.replace_all([_func("F_A")])
    second = store.load_all()[0]
    assert first["function_id"] == second["function_id"]
    assert second["function_id"] == first["function_id"]
    store.replace_all([_func("F_A", function_id="CUSTOM", status="stable")])
    kept = store.load_all()[0]
    assert kept["function_id"] == "CUSTOM" and kept["status"] == "stable"  # 不覆盖已有字段
    assert len(kept["version_history"]) == 1  # 已有 v1 不重复追加


def test_same_function_name_keeps_id_when_definition_changes(tmp_path):
    store = RegistryStore(db_path=str(tmp_path / "f.db"), namespace="ns1")
    store.replace_all([_func("F_A", definition="旧定义")])
    old_id = store.load_all()[0]["function_id"]

    store.replace_all([_func("F_A", definition="修订后的定义")])

    current = store.load_all()[0]
    assert current["function_id"] == old_id
    assert current["version_history"][0]["action"] == "CREATE"
