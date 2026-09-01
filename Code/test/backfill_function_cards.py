"""一次性补全：为冻结快照的 62 个 Function 生成旁挂 Function Card。

证据口径：evidence(f) = supporting_obs_ids(f) ∩ Bank（occurrences 里的
candidate_functions 有旧状态残留，不作为多支持判定依据）；多支持 obs 按函数
各自计入；dangling = declared - resident；不从旧 Bank 回收证据。
产物绑定快照（data/function_cards/<snapshot_id>/），快照/Registry/Bank 只读。

用法（Code/ 下）：
    python -X utf8 test/backfill_function_cards.py [snapshot_dir] [bank_file] [out_dir]
"""

import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pydantic import BaseModel, Field

from Agent.llm import chat_structured


_DEFAULT_SNAPSHOT = os.path.join(
    os.path.dirname(__file__), "..", "data", "ontology_snapshots",
    "evolve_250_20260822T063550401096Z_13b1bbda248f",
)
_DEFAULT_BANK = os.path.join(
    os.path.dirname(__file__), "..", "data", "evolve_250", "bank_evolve_250.jsonl",
)


# ---------- 确定性聚合 ----------

def collect_evidence(func: dict, bank: dict) -> list[str]:
    """evidence(f) = supporting_obs_ids(f) ∩ Bank，保持声明顺序。"""
    return [oid for oid in func.get("supporting_obs_ids", []) if oid in bank]


def aggregate_evidence(func: dict, bank: dict) -> dict:
    evidence_ids = collect_evidence(func, bank)
    obs_list = [bank[oid] for oid in evidence_ids]
    participants = Counter()
    for obs in obs_list:
        participants.update(p for p in obs.get("participants", []) if p)
    aspects = Counter(obs.get("affected_aspect", "") for obs in obs_list)
    declared = len(func.get("supporting_obs_ids", []))
    return {
        "declared_supporting_count": declared,
        "bank_resident_count": len(evidence_ids),
        "dangling_count": declared - len(evidence_ids),
        "support_story_count": len({obs.get("story_id", "") for obs in obs_list}),
        "participant_labels": [
            {"label": label, "count": n}
            for label, n in sorted(participants.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "common_affected_aspects": [
            {"value": value, "count": n}
            for value, n in sorted(aspects.items(), key=lambda kv: (-kv[1], kv[0]))
        ][:3],
        "evidence_refs": evidence_ids,
    }


# ---------- LLM 抽象 ----------

class StateTransition(BaseModel):
    before: str = Field(description="跨故事抽象的前置状态（去实例化、去专名）")
    after: str = Field(description="跨故事抽象的后置状态（去实例化、去专名）")


class FunctionAbstraction(BaseModel):
    preconditions: list[str] = Field(description="事件发生前必须成立的结构性前置条件（1-3条）")
    role_slots: list[str] = Field(
        description="该 Function 需要的角色位置标签（谁发起/谁受影响/谁提供信息或资源/谁受益/谁阻碍）"
    )
    state_transition: StateTransition = Field(description="事件造成的跨故事状态变化")


_SYSTEM_PROMPT = """你是叙事结构分析专家。给定一个 Function 及其跨故事支持证据（Observation 摘要），归纳该 Function 的"可生成结构约束"。只依据提供的证据归纳，不增加证据中不存在的机制。

请以 JSON 格式输出，字段与 schema 一致：preconditions（字符串数组）、role_slots（字符串数组）、state_transition（对象，含 before 和 after 两个字符串字段）。

输出要求（全部去具体人物名、道具和题材表层词，用结构化自然语言）：
1. preconditions：事件发生前必须成立的结构性前置条件，如"存在尚未公开的信息、隐瞒者和不知情者"。
2. role_slots：该 Function 需要的角色位置标签，覆盖"谁发起行动、谁受到影响、谁提供信息或资源、谁受益、谁形成阻碍"，如"隐瞒者、发现者、受到影响者"。
3. state_transition.before / after：跨故事抽象的状态变化，如 before="秘密处于隐藏状态"、after="秘密被关键人物知晓，人物关系、目标或行动策略改变"。"""


def _format_evidence(obs_list: list[dict]) -> str:
    lines = []
    for obs in obs_list:
        lines.append(
            f"- story_id: {obs.get('story_id', '')}\n"
            f"  participants: {obs.get('participants', [])}\n"
            f"  before_state: {obs.get('before_state', '')}\n"
            f"  after_state: {obs.get('after_state', '')}\n"
            f"  affected_aspect: {obs.get('affected_aspect', '')}"
        )
    return "\n".join(lines)


def abstract_function(func: dict, evidence_ids: list[str], bank: dict) -> dict:
    """一次 LLM 抽象：只喂紧凑字段（不含 event/surface_form/narrative_effect）。"""
    obs_list = [bank[oid] for oid in evidence_ids]
    user = (
        f"Function: {func['function_name']}\n"
        f"定义: {func.get('definition', '')}\n\n"
        f"支持证据（{len(obs_list)} 条 Observation，"
        f"跨 {len({obs.get('story_id') for obs in obs_list})} 个故事）：\n"
        f"{_format_evidence(obs_list)}"
    )
    result = chat_structured(
        [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": user}],
        FunctionAbstraction,
    )
    return result.model_dump()


# ---------- 主流程 ----------

def _load_functions(snapshot_dir: str) -> list[dict]:
    with open(os.path.join(snapshot_dir, "functions.jsonl"), "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_bank(bank_path: str) -> dict:
    bank = {}
    with open(bank_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obs = json.loads(line)
                bank[obs["obs_id"]] = obs
    return bank


def _load_done(out_path: str) -> dict[str, dict]:
    """重跑续跑：跳过已成功（llm.ok=True）的卡片。"""
    done = {}
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                card = json.loads(line)
                if card.get("llm", {}).get("ok"):
                    done[card["function_id"]] = card
    return done


def main() -> None:
    snapshot_dir = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_SNAPSHOT
    bank_path = sys.argv[2] if len(sys.argv) > 2 else _DEFAULT_BANK
    out_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        os.path.dirname(__file__), "..", "data", "function_cards",
        os.path.basename(snapshot_dir),
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "function_cards.jsonl")

    funcs = _load_functions(snapshot_dir)
    bank = _load_bank(bank_path)
    done = _load_done(out_path)

    cards = []
    failures = []
    for index, func in enumerate(funcs, 1):
        card = done.get(func["function_id"])
        if card is not None:
            print(f"[{index}/{len(funcs)}] {func['function_name']}: 复用")
        else:
            card = {
                "snapshot_id": os.path.basename(snapshot_dir),
                "function_id": func["function_id"],
                "function_name": func["function_name"],
                "definition": func.get("definition", ""),
            }
            card["evidence"] = aggregate_evidence(func, bank)
            try:
                card["abstraction"] = abstract_function(
                    func, card["evidence"]["evidence_refs"], bank,
                )
                card["llm"] = {"ok": True, "error": None}
                print(f"[{index}/{len(funcs)}] {func['function_name']}: OK")
            except Exception as e:
                card["abstraction"] = None
                card["llm"] = {"ok": False, "error": str(e)[:300]}
                failures.append(func["function_name"])
                print(f"[{index}/{len(funcs)}] {func['function_name']}: FAIL - {e}")
        cards.append(card)

    with open(out_path, "w", encoding="utf-8") as f:
        for card in cards:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")

    total_declared = sum(card["evidence"]["declared_supporting_count"] for card in cards)
    total_resident = sum(card["evidence"]["bank_resident_count"] for card in cards)
    summary = {
        "snapshot_id": os.path.basename(snapshot_dir),
        "bank_file": bank_path,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_functions": len(cards),
        "llm_ok": len(cards) - len(failures),
        "llm_failed": len(failures),
        "failed_function_names": failures,
        "evidence_totals": {
            "declared_supporting_count": total_declared,
            "bank_resident_count": total_resident,
            "dangling_count": total_declared - total_resident,
        },
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
