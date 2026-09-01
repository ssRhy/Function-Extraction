"""build_transition_index 测试：邻接折叠/排序/计数、机制去重/悬空跳过。"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import build_transition_index as bi


def _occ(story, n, fn):
    return {"obs_id": f"{story}_obs_{n}", "story_id": story, "status": "MATCHED", "function_name": fn}


def test_transitions_collapse_and_count():
    occ = [
        _occ("s1", 1, "A"), _occ("s1", 2, "A"), _occ("s1", 3, "B"),
        _occ("s2", 1, "A"), _occ("s2", 2, "B"),
        {"obs_id": "s3_obs_1", "story_id": "s3", "status": "UNCERTAIN", "function_name": None},
    ]
    t = bi.build_transitions(occ)
    ab = next(x for x in t if x["from"] == "A" and x["to"] == "B")
    assert ab["count"] == 2 and ab["support_stories"] == 2
    assert len(t) == 1


def test_transitions_ordered_by_obs_index():
    occ = [_occ("s1", 2, "B"), _occ("s1", 1, "A")]
    t = bi.build_transitions(occ)
    assert t == [{"from": "A", "to": "B", "count": 1, "support_stories": 1}]


def test_mechanisms_dedup_and_skip_dangling():
    functions = [{"function_id": "F1", "function_name": "A", "supporting_obs_ids": ["x", "y", "z", "empty"]}]
    bank = {
        "x": {"obs_id": "x", "surface_form": "枪击", "event": "e1"},
        "y": {"obs_id": "y", "surface_form": "枪击", "event": "e1"},
        "z": {"obs_id": "z", "surface_form": "对峙", "event": "e2"},
        "empty": {"obs_id": "empty", "surface_form": "", "event": "e3"},
    }
    mech = bi.build_mechanisms(functions, bank)["A"]["mechanisms"]
    assert mech[0] == {"surface_form": "枪击", "count": 2, "sample_event": "e1"}
    assert mech[1] == {"surface_form": "对峙", "count": 1, "sample_event": "e2"}
    assert len(mech) == 2
