"""OntologySnapshot 发布、加载与完整性校验。"""

import json
import os

import pytest

from Contracts import snapshot as snapshot_module
from Contracts.function_contract import definition_sha256
from Contracts.snapshot import (
    load_function_contracts,
    load_occurrences,
    load_snapshot,
    publish_snapshot,
    validate_snapshot,
)


def _functions() -> list[dict]:
    return [{
        "function_id": "F_TEST001",
        "function_name": "RESOURCE_ACQUISITION",
        "definition": "角色获得推动后续行动的关键资源",
        "realization_patterns": ["获得资源"],
        "supporting_obs_ids": ["story_1_obs_001"],
    }]


def _evaluation(verdict: str = "PASS") -> dict:
    return {"verdict": verdict, "passed_dimensions": ["coverage"]}


def _occurrences() -> list[dict]:
    return [{
        "occurrence_id": "story_1_obs_001",
        "obs_id": "story_1_obs_001",
        "observation_version_id": "OV_story_1_obs_001",
        "story_id": "story_1",
        "status": "MATCHED",
        "function_id": "F_TEST001",
        "function_name": "RESOURCE_ACQUISITION",
        "participant_ids": ["P1"],
        "role_bindings": {
            "actor": ["P1"], "affected": [], "information_provider": [],
            "resource_provider": [], "beneficiary": [], "obstacle": [],
        },
        "relationship_deltas": [],
        "source_sentence_indices": [0],
    }]


def _profiles() -> list[dict]:
    return [{
        "story_id": "story_1",
        "story_version_id": "SV_story_1",
        "profile": {
            "world_setting": "测试世界",
            "protagonist_id": "P1",
            "characters": [{
                "id": "P1", "label": "主角", "structural_role": "protagonist",
                "long_term_goal": "获得资源", "motivation": "解决危机",
            }],
            "relationships": [],
            "core_conflict": "资源不足",
            "ending_state": "资源可用",
        },
    }]


def _contracts() -> list[dict]:
    return [{
        "function_id": "F_TEST001",
        "function_name": "RESOURCE_ACQUISITION",
        "definition_sha256": definition_sha256(_functions()[0]),
        "evidence_refs": ["story_1_obs_001"],
        "role_slots": ["actor"],
        "preconditions": [{"role_slots": ["actor"], "aspect": "RESOURCE", "state": "INSUFFICIENT"}],
        "effects": [{
            "role_slots": ["actor"], "aspect": "RESOURCE",
            "before": "INSUFFICIENT", "after": "AVAILABLE",
        }],
        "obligation_effects": {"opens": [], "advances": [], "resolves": []},
    }]


def test_publish_load_and_validate(tmp_path):
    path = publish_snapshot(
        _functions(), _evaluation(), "bootstrap", "test", str(tmp_path), _occurrences(),
        story_profiles=_profiles(),
    )
    assert path is not None
    assert sorted(os.listdir(path)) == [
        "evaluation.json", "functions.jsonl", "manifest.json", "occurrences.jsonl",
        "story_profiles.jsonl",
    ]

    manifest, functions, evaluation = load_snapshot(path)
    assert manifest == validate_snapshot(path)
    assert manifest["schema_version"] == 5
    assert manifest["function_count"] == 1
    assert manifest["occurrence_count"] == 1
    assert manifest["parent_snapshot_id"] is None
    assert functions == _functions()
    assert evaluation == _evaluation()
    occurrences = load_occurrences(path)
    assert occurrences[0]["snapshot_id"] == manifest["snapshot_id"]
    assert occurrences[0]["function_id"] == "F_TEST001"


def test_fail_does_not_publish(tmp_path):
    root = tmp_path / "snapshots"
    assert publish_snapshot(_functions(), _evaluation("FAIL"), "evolve", "test", str(root)) is None
    assert not root.exists()


def test_publish_v4_with_function_contracts(tmp_path):
    path = publish_snapshot(
        _functions(), _evaluation(), "bootstrap", "test", str(tmp_path),
        _occurrences(), _contracts(), story_profiles=_profiles(),
    )
    manifest = validate_snapshot(path)
    assert manifest["schema_version"] == 5
    assert manifest["function_contract_count"] == 1
    assert load_function_contracts(path) == _contracts()
    assert "function_contracts.jsonl" in os.listdir(path)
    vocabulary = json.load(open(os.path.join(path, "state_vocabulary.json"), encoding="utf-8"))
    assert vocabulary["schema_version"] == 1
    assert any(item["canonical_id"] == "RESOURCE" for item in vocabulary["entries"])


def test_function_contract_tampering_is_detected(tmp_path):
    path = publish_snapshot(
        _functions(), _evaluation(), "bootstrap", "test", str(tmp_path),
        _occurrences(), _contracts(), story_profiles=_profiles(),
    )
    with open(os.path.join(path, "function_contracts.jsonl"), "a", encoding="utf-8") as f:
        f.write("{}\n")
    with pytest.raises(ValueError, match="function_contracts.jsonl SHA-256"):
        validate_snapshot(path)


@pytest.mark.parametrize("functions", [
    [{"function_name": "A", "definition": "定义"}],
    [
        {"function_id": "F_1", "function_name": "A", "definition": "定义"},
        {"function_id": "F_1", "function_name": "B", "definition": "定义"},
    ],
    [
        {"function_id": "F_1", "function_name": "A", "definition": "定义"},
        {"function_id": "F_2", "function_name": "A", "definition": "定义"},
    ],
    [{"function_id": "F_1", "function_name": "A", "definition": "  "}],
])
def test_invalid_functions_rejected(tmp_path, functions):
    with pytest.raises(ValueError):
        publish_snapshot(functions, _evaluation(), "bootstrap", "test", str(tmp_path))


def test_tampering_is_detected(tmp_path):
    path = publish_snapshot(_functions(), _evaluation(), "bootstrap", "test", str(tmp_path), story_profiles=_profiles())
    with open(os.path.join(path, "functions.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(_functions()[0], ensure_ascii=False) + "\n")
    with pytest.raises(ValueError, match="SHA-256"):
        validate_snapshot(path)


def test_occurrence_tampering_is_detected(tmp_path):
    path = publish_snapshot(
        _functions(), _evaluation(), "evolve", "test", str(tmp_path), _occurrences(), story_profiles=_profiles(),
    )
    with open(os.path.join(path, "occurrences.jsonl"), "a", encoding="utf-8") as f:
        f.write("{}\n")
    with pytest.raises(ValueError, match="occurrences.jsonl SHA-256"):
        validate_snapshot(path)


def test_unknown_occurrence_function_rejected(tmp_path):
    occurrence = _occurrences()[0]
    occurrence["function_id"] = "F_UNKNOWN"
    with pytest.raises(ValueError, match="未知 Function"):
        publish_snapshot(
            _functions(), _evaluation(), "evolve", "test", str(tmp_path), [occurrence], story_profiles=_profiles(),
        )


def test_identical_publish_is_idempotent(tmp_path):
    first = publish_snapshot(_functions(), _evaluation(), "evolve", "test", str(tmp_path), story_profiles=_profiles())
    second = publish_snapshot(_functions(), _evaluation(), "evolve", "test", str(tmp_path), story_profiles=_profiles())
    assert second == first
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 1


def test_same_id_with_different_content_is_rejected(tmp_path, monkeypatch):
    real_datetime = snapshot_module.datetime

    class FixedDatetime:
        @classmethod
        def now(cls, _timezone):
            return real_datetime(2026, 8, 20, 1, 2, 3, 456789, tzinfo=snapshot_module.timezone.utc)

    monkeypatch.setattr(snapshot_module, "datetime", FixedDatetime)
    publish_snapshot(_functions(), _evaluation(), "bootstrap", "test", str(tmp_path), story_profiles=_profiles())
    changed_evaluation = {"verdict": "PASS", "passed_dimensions": ["cohesion"]}
    with pytest.raises(FileExistsError):
        publish_snapshot(_functions(), changed_evaluation, "bootstrap", "test", str(tmp_path), story_profiles=_profiles())
