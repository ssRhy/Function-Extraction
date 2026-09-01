"""Story / Observation 不可变版本 ID。"""

import hashlib
import json
import re


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def story_version_id(story_id: str, text: str) -> str:
    return "SV_" + _digest(f"{story_id}|{text}")[:24]


def observation_version_id(story_version: str, observation: dict) -> str:
    payload = {
        key: value for key, value in observation.items()
        if key not in {
            "obs_id", "observation_version_id", "observation_order",
            "source_sentence_indices", "story_version_id", "ts",
        }
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "OV_" + _digest(f"{story_version}|{canonical}")[:24]


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _semantic_anchor(observation: dict) -> dict:
    return {
        "before_state": _normalize_text(observation.get("before_state")),
        "event": _normalize_text(observation.get("event")),
        "after_state": _normalize_text(observation.get("after_state")),
        "affected_aspect": _normalize_text(observation.get("affected_aspect")),
        "narrative_effect": _normalize_text(observation.get("narrative_effect")),
        "surface_form": _normalize_text(observation.get("surface_form")),
        "participants": sorted(
            _normalize_text(item) for item in (observation.get("participants") or [])
        ),
    }


def observation_id(story_id: str, observation: dict) -> str:
    """生成与抽取顺序、句子下标无关的 Observation 逻辑 ID。"""
    source_text = _normalize_text(observation.get("source_text"))
    if source_text:
        # 原文锚点区分“同一故事中的同一事件”；语义角色用于区分
        # 同一组句子承载多个不同结构变化的情况。
        anchor = {
            "source_text": source_text,
            "affected_aspect": _normalize_text(observation.get("affected_aspect")),
            "participants": sorted(
                _normalize_text(item)
                for item in (observation.get("participants") or [])
            ),
        }
    else:
        anchor = _semantic_anchor(observation)
    canonical = json.dumps(anchor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = _digest(f"{story_id}|{canonical}")[:12]
    return f"{story_id}_obs_{digest}"
