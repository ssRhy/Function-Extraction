"""跨 Agent 共享的 FunctionContract schema 与一致性校验。"""

import hashlib
import re

from pydantic import BaseModel, Field, model_validator
from Contracts.story_profile import ROLE_POSITION_SET, ROLE_POSITIONS


STANDARD_ROLE_POSITIONS = ROLE_POSITIONS
RELATIONSHIP_ASPECTS = frozenset({"RELATIONSHIP_STATUS", "RELATIONSHIP"})


class StateCondition(BaseModel):
    role_slots: list[str]
    aspect: str = Field(pattern=r"[A-Z][A-Z0-9_]*")
    state: str


class StateEffect(BaseModel):
    role_slots: list[str]
    aspect: str = Field(pattern=r"[A-Z][A-Z0-9_]*")
    before: str
    after: str


class ObligationTemplate(BaseModel):
    key: str = Field(pattern=r"[A-Z][A-Z0-9_]*")
    role_slots: list[str]
    description: str
    satisfied_when: str


class ObligationEffects(BaseModel):
    opens: list[ObligationTemplate] = Field(default_factory=list)
    advances: list[ObligationTemplate] = Field(default_factory=list)
    resolves: list[ObligationTemplate] = Field(default_factory=list)


class FunctionContractBody(BaseModel):
    role_slots: list[str]
    preconditions: list[StateCondition]
    effects: list[StateEffect]
    obligation_effects: ObligationEffects

    @model_validator(mode="after")
    def validate_role_references(self):
        if not self.role_slots or not self.preconditions or not self.effects:
            raise ValueError("FunctionContract 缺少角色、前置或效果")
        unknown = set(self.role_slots) - ROLE_POSITION_SET
        if unknown:
            raise ValueError(f"FunctionContract 使用了非标准角色位置: {', '.join(sorted(unknown))}")
        if len(set(self.role_slots)) != len(self.role_slots):
            raise ValueError("FunctionContract 角色槽位重复")
        referenced = []
        referenced.extend(slot for item in self.preconditions for slot in item.role_slots)
        referenced.extend(slot for item in self.effects for slot in item.role_slots)
        for group in (self.obligation_effects.opens, self.obligation_effects.advances,
                      self.obligation_effects.resolves):
            referenced.extend(slot for item in group for slot in item.role_slots)
        if not set(referenced).issubset(set(self.role_slots)):
            raise ValueError("FunctionContract 使用了未声明角色槽位")
        for effect in self.effects:
            if effect.aspect in RELATIONSHIP_ASPECTS and (
                len(effect.role_slots) != 2 or len(set(effect.role_slots)) != 2
            ):
                raise ValueError("关系状态效果必须明确覆盖两个不同角色槽位")
        return self


def relationship_effects(contract: dict) -> list[dict]:
    """返回能授权一条二元关系边的有效 Contract effects。"""
    return [
        effect for effect in contract.get("effects", [])
        if effect.get("aspect") in RELATIONSHIP_ASPECTS
        and len(effect.get("role_slots", [])) == 2
        and len(set(effect.get("role_slots", []))) == 2
        and set(effect.get("role_slots", [])).issubset(ROLE_POSITION_SET)
        and set(effect.get("role_slots", [])).issubset(set(contract.get("role_slots", [])))
    ]


def definition_sha256(function: dict) -> str:
    definition = str(function.get("definition") or "").strip()
    return hashlib.sha256(definition.encode("utf-8")).hexdigest()


def validate_function_contracts(functions: list[dict], contracts: list[dict]) -> None:
    by_id = {function.get("function_id"): function for function in functions}
    if len(contracts) != len(functions):
        raise ValueError("FunctionContract 数量必须与 Function 数量一致")
    seen = set()
    for contract in contracts:
        function_id = contract.get("function_id")
        function = by_id.get(function_id)
        if function is None or contract.get("function_name") != function.get("function_name"):
            raise ValueError("FunctionContract 引用了未知 Function")
        if function_id in seen:
            raise ValueError(f"重复 FunctionContract: {function_id}")
        if contract.get("definition_sha256") != definition_sha256(function):
            raise ValueError(f"FunctionContract 定义哈希失效: {function.get('function_name')}")
        body = FunctionContractBody.model_validate(contract)
        evidence_refs = contract.get("evidence_refs") or []
        if not evidence_refs:
            raise ValueError(f"FunctionContract 缺少证据引用: {function.get('function_name')}")
        if not set(evidence_refs).issubset(set(function.get("supporting_obs_ids") or [])):
            raise ValueError(f"FunctionContract 引用了非 supporting evidence: {function.get('function_name')}")
        identifiers = [item.aspect for item in body.preconditions]
        identifiers.extend(item.aspect for item in body.effects)
        for group in (body.obligation_effects.opens, body.obligation_effects.advances,
                      body.obligation_effects.resolves):
            identifiers.extend(item.key for item in group)
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", value or "") for value in identifiers):
            raise ValueError(f"FunctionContract 状态维度或债务键格式无效: {function.get('function_name')}")
        seen.add(function_id)
