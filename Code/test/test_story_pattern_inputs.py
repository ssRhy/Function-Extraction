"""Story Pattern Agent 数据库输入节点测试。"""

import pytest

from story_pattern_loader import inputs as inputs_module


def _functions():
    return [
        {"function_id": "F_1", "function_name": "FUNCTION_A", "definition": "结构作用 A"},
        {"function_id": "F_2", "function_name": "FUNCTION_B", "definition": "结构作用 B"},
    ]


def _obs(obs_id, story_id, **changes):
    row = {
        "obs_id": obs_id,
        "story_id": story_id,
        "event": "发生事件",
        "before_state": "事件前",
        "after_state": "事件后",
    }
    row.update(changes)
    return row


def _source(functions=None, observations=None, contracts=None, metadata=None):
    return {
        "manifest": {"snapshot_id": "snapshot_test", "schema_version": 3 if contracts else 2},
        "functions": functions or _functions(),
        "contracts": contracts or [],
        "story_metadata": metadata or [
            {"story_id": "s2", "story_type": "题材二"},
            {"story_id": "s1", "story_type": "题材一"},
        ],
        "observations": observations or [
            _obs("s1_obs_bbbbbbbbbbbb", "s1"),
            _obs("s2_obs_cccccccccccc", "s2"),
            _obs("s1_obs_aaaaaaaaaaaa", "s1"),
        ],
        "occurrences": [],
    }


def _load(monkeypatch, source):
    monkeypatch.setattr(
        inputs_module.StoryKnowledgeStore,
        "load_story_pattern_inputs",
        lambda _self, snapshot_id: source,
    )
    return inputs_module.load_inputs({
        "knowledge_db": "knowledge.db",
        "snapshot_id": "snapshot_test",
        "out_dir": "out",
    })


def test_load_inputs_reads_function_contracts(monkeypatch):
    contracts = [
        {"function_id": "F_1", "function_name": "FUNCTION_A"},
        {"function_id": "F_2", "function_name": "FUNCTION_B"},
    ]
    result = _load(monkeypatch, _source(contracts=contracts))

    assert [item["function_id"] for item in result["function_contracts"]] == ["F_1", "F_2"]
    assert result["function_contract_by_id"]["F_1"]["function_name"] == "FUNCTION_A"


@pytest.mark.parametrize("observations, message", [
    ([_obs("s1_obs_aaaaaaaaaaaa", "s1"), _obs("s1_obs_aaaaaaaaaaaa", "s1")], "重复 obs_id"),
    ([_obs("s3_obs_aaaaaaaaaaaa", "s3")], "不在 manifest"),
    ([_obs("s1_obs_001", "s1")], "非法 obs_id"),
    ([_obs("wrong-id", "s1")], "非法 obs_id"),
])
def test_invalid_observations_rejected(monkeypatch, observations, message):
    with pytest.raises(ValueError, match=message):
        _load(monkeypatch, _source(observations=observations))


def test_stable_hashed_observation_ids_are_sorted_by_observation_order(monkeypatch):
    observations = [
        _obs("s1_obs_bbbbbbbbbbbb", "s1", observation_order=2),
        _obs("s1_obs_aaaaaaaaaaaa", "s1", observation_order=1),
    ]

    result = _load(monkeypatch, _source(observations=observations))

    assert [item["obs_id"] for item in result["observations_by_story"]["s1"]] == [
        "s1_obs_aaaaaaaaaaaa", "s1_obs_bbbbbbbbbbbb",
    ]


def test_load_inputs_keeps_stories_without_observations(monkeypatch):
    source = _source()
    source["observations"] = [_obs("s1_obs_aaaaaaaaaaaa", "s1")]

    result = _load(monkeypatch, source)

    assert result["story_ids"] == ["s2", "s1"]
    assert result["story_metadata"] == {
        "s2": {"story_id": "s2", "story_type": "题材二"},
        "s1": {"story_id": "s1", "story_type": "题材一"},
    }
    assert result["observations_by_story"]["s2"] == []


@pytest.mark.parametrize("field", ["obs_id", "story_id", "event", "before_state", "after_state"])
def test_missing_required_observation_field_rejected(monkeypatch, field):
    observation = _obs("s1_obs_aaaaaaaaaaaa", "s1")
    observation.pop(field)
    with pytest.raises(ValueError, match="缺少必要字段"):
        _load(monkeypatch, _source(observations=[observation]))


@pytest.mark.parametrize("functions, message", [
    ([
        {"function_id": "F_1", "function_name": "A", "definition": "A"},
        {"function_id": "F_2", "function_name": "A", "definition": "B"},
    ], "重复 function_name"),
    ([
        {"function_id": "F_1", "function_name": "A", "definition": "A"},
        {"function_id": "F_1", "function_name": "B", "definition": "B"},
    ], "重复 function_id"),
])
def test_duplicate_function_index_rejected(monkeypatch, functions, message):
    with pytest.raises(ValueError, match=message):
        _load(monkeypatch, _source(functions=functions))


def test_missing_snapshot_is_reported(monkeypatch):
    def missing(_self, _snapshot_id):
        raise ValueError("知识库中不存在 Snapshot")

    monkeypatch.setattr(inputs_module.StoryKnowledgeStore, "load_story_pattern_inputs", missing)
    with pytest.raises(ValueError, match="不存在 Snapshot"):
        inputs_module.load_inputs({
            "knowledge_db": "knowledge.db", "snapshot_id": "missing", "out_dir": "out",
        })
