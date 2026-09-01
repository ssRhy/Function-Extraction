"""Story / Observation 版本 ID 测试。"""

from Contracts.versioning import observation_id, observation_version_id


def test_observation_id_uses_source_text_not_sentence_indices_or_order():
    first = {
        "event": "旧事件描述",
        "source_sentence_indices": [4, 5],
        "source_text": "英雄夺得宝剑。",
    }
    changed = {
        "event": "更新后的事件描述",
        "source_sentence_indices": [9],
        "source_text": "英雄夺得宝剑。",
    }

    assert observation_id("story_1", first) == observation_id("story_1", changed)


def test_observation_id_is_order_independent_for_inserted_observation():
    first = {"event": "事件 A", "source_text": "事件 A。"}
    inserted = {"event": "事件 X", "source_text": "事件 X。"}
    moved = {"event": "事件 A", "source_text": "事件 A。"}

    assert observation_id("story_1", first) == observation_id("story_1", moved)
    assert observation_id("story_1", first) != observation_id("story_1", inserted)


def test_observation_id_falls_back_to_normalized_semantics():
    first = {"event": "事件", "participants": ["受害者", "英雄"]}
    reordered = {"event": "事件", "participants": ["英雄", "受害者"]}

    assert observation_id("story_1", first) == observation_id("story_1", reordered)


def test_observation_version_ignores_order_and_sentence_indices():
    story_version = "SV_story"
    first = {
        "obs_id": "story_obs_a",
        "observation_order": 1,
        "source_sentence_indices": [0],
        "source_text": "事件。",
        "event": "事件",
    }
    moved = {**first, "obs_id": "story_obs_b", "observation_order": 2,
             "source_sentence_indices": [4, 5]}

    assert observation_version_id(story_version, first) == observation_version_id(story_version, moved)
