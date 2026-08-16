"""RegistryStore（SQLite）单元测试：CRUD / 命名空间隔离 / 字段无损 / JSONL 往返。"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Agent.Registry.registry import RegistryStore


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
    assert loaded["version_history"] == []


def test_export_import_jsonl_roundtrip(tmp_path):
    db = str(tmp_path / "f.db")
    store = RegistryStore(db_path=db, namespace="ns1")
    funcs = [_func("F_A"), _func("F_B", extra_field="x")]
    store.replace_all(funcs)
    dst = str(tmp_path / "out.jsonl")
    store.export_jsonl(dst)

    imported = RegistryStore(db_path=db, namespace="ns2")
    n = imported.import_jsonl(dst, "ns2")
    assert n == 2
    assert imported.load_all() == funcs
    # 幂等：重复导入结果一致
    imported.import_jsonl(dst, "ns2")
    assert imported.count() == 2