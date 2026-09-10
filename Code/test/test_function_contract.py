"""FunctionContract：证据选择、生成、缓存复用与一致性校验。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from FunctionExtract_Agent.Contract import contract as contract_module
from Contracts.function_contract import (
    FunctionContractBody,
    ObligationEffects,
    ObligationTemplate,
    StateCondition,
    StateEffect,
    validate_function_contracts,
)


def _function(definition="角色获得关键资源"):
    return {
        "function_id": "F_TEST001",
        "function_name": "RESOURCE_ACQUISITION",
        "definition": definition,
        "supporting_obs_ids": ["s1_obs_001"],
    }


def _observation():
    return {
        "obs_id": "s1_obs_001",
        "story_id": "s1",
        "participants": ["行动者"],
        "before_state": "行动者缺少关键资源",
        "after_state": "行动者获得资源并能继续行动",
        "affected_aspect": "资源",
    }


def _body():
    obligation = ObligationTemplate(
        key="RESOURCE_REQUIREMENT", role_slots=["actor"],
        description="行动缺少资源", satisfied_when="行动者取得足够资源",
    )
    return FunctionContractBody(
            role_slots=["actor"],
            preconditions=[StateCondition(role_slots=["actor"], aspect="RESOURCE", state="INSUFFICIENT")],
        effects=[StateEffect(
                role_slots=["actor"], aspect="RESOURCE", before="INSUFFICIENT", after="AVAILABLE",
        )],
        obligation_effects=ObligationEffects(resolves=[obligation]),
    )


def test_build_and_reuse_contract(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        contract_module, "chat_structured",
        lambda messages, schema: calls.append(messages) or _body(),
    )
    functions = [_function()]
    observations = [_observation()]
    first = contract_module.build_function_contracts(functions, observations, str(tmp_path))
    second = contract_module.build_function_contracts(functions, observations, str(tmp_path))
    assert first == second
    assert len(calls) == 1
    assert first[0]["evidence_refs"] == ["s1_obs_001"]
    assert os.path.exists(tmp_path / "function_contracts.jsonl")


def test_definition_change_invalidates_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        contract_module, "chat_structured",
        lambda messages, schema: calls.append(messages) or _body(),
    )
    observations = [_observation()]
    contract_module.build_function_contracts([_function()], observations, str(tmp_path))
    contract_module.build_function_contracts([_function("角色取得推进目标所需资源")], observations, str(tmp_path))
    assert len(calls) == 2


def test_reuses_inherited_contract(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        contract_module, "chat_structured",
        lambda messages, schema: calls.append(messages) or _body(),
    )
    functions = [_function()]
    observations = [_observation()]
    inherited = contract_module.build_function_contracts(functions, observations, str(tmp_path / "parent"))
    reused = contract_module.build_function_contracts(
        functions, observations, str(tmp_path / "child"), existing_contracts=inherited,
    )
    assert reused == inherited
    assert len(calls) == 1


def test_contract_requires_resident_evidence(tmp_path):
    with pytest.raises(ValueError, match="没有可驻留证据"):
        contract_module.build_function_contracts([_function()], [], str(tmp_path))


def test_contract_rejects_undeclared_role_slot(monkeypatch):
    function = _function()
    contract = {
        "function_id": function["function_id"],
        "function_name": function["function_name"],
        "definition_sha256": contract_module.definition_sha256(function),
        "evidence_refs": ["s1_obs_001"],
        **_body().model_dump(),
    }
    contract["effects"][0]["role_slots"] = ["未声明角色"]
    with pytest.raises(ValueError, match="未声明角色槽位"):
        validate_function_contracts([function], [contract])


def test_contract_rejects_non_supporting_evidence():
    function = _function()
    contract = {
        "function_id": function["function_id"],
        "function_name": function["function_name"],
        "definition_sha256": contract_module.definition_sha256(function),
        "evidence_refs": ["unknown_obs"],
        **_body().model_dump(),
    }
    with pytest.raises(ValueError, match="非 supporting evidence"):
        validate_function_contracts([function], [contract])


def test_contract_requires_two_role_slots_for_relationship_effect():
    function = _function()
    contract = {
        "function_id": function["function_id"],
        "function_name": function["function_name"],
        "definition_sha256": contract_module.definition_sha256(function),
        "evidence_refs": ["s1_obs_001"],
        **_body().model_dump(),
    }
    contract["effects"][0].update({
        "aspect": "RELATIONSHIP_STATUS",
        "role_slots": ["actor"],
    })
    with pytest.raises(ValueError, match="两个不同角色槽位"):
        validate_function_contracts([function], [contract])


def test_inherited_legacy_relationship_effect_is_dropped():
    function = _function()
    contract = {
        "function_id": function["function_id"],
        "function_name": function["function_name"],
        "definition_sha256": contract_module.definition_sha256(function),
        "evidence_refs": ["s1_obs_001"],
        **_body().model_dump(),
    }
    contract["effects"].append({
        "aspect": "RELATIONSHIP_STATUS",
        "before": "敌对",
        "after": "决裂",
        "role_slots": ["actor"],
    })
    sanitized = contract_module._sanitize_legacy_contract(contract)
    validate_function_contracts([function], [sanitized])
    assert all(item["aspect"] != "RELATIONSHIP_STATUS" for item in sanitized["effects"])


def test_inherited_only_legacy_relationship_effect_is_downgraded():
    function = _function()
    contract = {
        "function_id": function["function_id"],
        "function_name": function["function_name"],
        "definition_sha256": contract_module.definition_sha256(function),
        "evidence_refs": ["s1_obs_001"],
        **_body().model_dump(),
    }
    contract["effects"] = [{
        "aspect": "RELATIONSHIP_STATUS",
        "before": "敌对",
        "after": "决裂",
        "role_slots": ["actor"],
    }]
    sanitized = contract_module._sanitize_legacy_contract(contract)
    validate_function_contracts([function], [sanitized])
    assert sanitized["effects"][0]["aspect"] == "FUNCTION_STATE"


def test_prunes_unreferenced_roles():
    contract = {
        "function_id": "F_TEST001",
        "function_name": "EMPOWERMENT_GAIN",
        "role_slots": [
            "actor", "affected", "resource_provider", "beneficiary", "obstacle", "information_provider",
        ],
        "preconditions": [
            {"role_slots": ["actor"], "aspect": "RESOURCE", "state": "AVAILABLE"},
            {"role_slots": ["affected"], "aspect": "NEED", "state": "PRESENT"},
        ],
        "effects": [
            {"role_slots": ["affected"], "aspect": "RESOURCE", "before": "MISSING", "after": "AVAILABLE"},
        ],
        "obligation_effects": {"opens": [], "advances": [], "resolves": []},
    }
    sanitized = contract_module._prune_optional_role_slots(contract)
    assert sanitized["role_slots"] == ["actor", "affected"]
