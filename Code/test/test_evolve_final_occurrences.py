"""Evolve 最终 FunctionOccurrence 对齐的状态传递测试。"""

from Contracts.occurrence import align_occurrences
from FunctionExtract_Agent.evolve import _merge_observation_labels


OBS_ID = "story_1_obs_abcdef123456"


def _observation(role_bindings=None):
    return {
        "obs_id": OBS_ID,
        "story_id": "story_1",
        "event": "事件",
        "before_state": "之前",
        "after_state": "之后",
        "role_bindings": role_bindings or {},
    }


def _align(label, functions=None, contracts=None, role_bindings=None):
    observations = _merge_observation_labels(
        [_observation(role_bindings)],
        [{"obs_id": OBS_ID, "label": label}],
    )
    return align_occurrences(functions or [], observations, contracts=contracts)[0]


def test_novel_without_function_support_becomes_other():
    occurrence = _align("NOVEL")

    assert occurrence["status"] == "OTHER"
    assert occurrence["function_name"] == "OTHER"


def test_uncertain_or_resolved_without_function_support_stays_uncertain():
    assert _align("UNCERTAIN")["status"] == "UNCERTAIN"
    assert _align("RESOLVED")["status"] == "UNCERTAIN"


def test_match_with_contract_roles_becomes_matched():
    occurrence = _align(
        "MATCH",
        functions=[{
            "function_id": "F_FINAL",
            "function_name": "FINAL_FUNCTION",
            "supporting_obs_ids": [OBS_ID],
        }],
        contracts=[{"function_name": "FINAL_FUNCTION", "role_slots": ["actor"]}],
        role_bindings={"actor": ["P1"]},
    )

    assert occurrence["status"] == "MATCHED"


def test_match_missing_contract_role_becomes_uncertain():
    occurrence = _align(
        "MATCH",
        functions=[{
            "function_id": "F_FINAL",
            "function_name": "FINAL_FUNCTION",
            "supporting_obs_ids": [OBS_ID],
        }],
        contracts=[{"function_name": "FINAL_FUNCTION", "role_slots": ["actor"]}],
    )

    assert occurrence["status"] == "UNCERTAIN"
