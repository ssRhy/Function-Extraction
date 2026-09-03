"""FunctionContract 状态词汇的确定性规范化。"""

import hashlib
import re
import unicodedata


_IDENTIFIER = re.compile(r"[A-Z][A-Z0-9_]*")
_KINDS = ("aspect", "state", "obligation_key")


def normalize_raw(value: object) -> str:
    """统一 Unicode、空白和 ASCII 标识符大小写，不推断语义同义词。"""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text.upper() if _IDENTIFIER.fullmatch(text) else text


def canonical_id(kind: str, value: object) -> str:
    if kind not in _KINDS:
        raise ValueError(f"未知 StateVocabulary 类型: {kind}")
    raw = normalize_raw(value)
    if not raw:
        raise ValueError(f"{kind} 不能为空")
    if kind in {"aspect", "obligation_key"} or _IDENTIFIER.fullmatch(raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12].upper()
    return f"STATE_{digest}"


class StateVocabulary:
    """由当前 Snapshot 合同确定性生成的规范词表。"""

    schema_version = 1

    def __init__(self, entries: list[dict]):
        self.entries = entries
        self._index = {
            (entry["kind"], alias): entry["canonical_id"]
            for entry in entries
            for alias in entry["aliases"]
        }

    @classmethod
    def from_contracts(cls, contracts: list[dict]) -> "StateVocabulary":
        raw_values = {kind: set() for kind in _KINDS}
        for contract in contracts:
            for item in contract.get("preconditions", []):
                raw_values["aspect"].add(item.get("aspect", ""))
                raw_values["state"].add(item.get("state", ""))
            for item in contract.get("effects", []):
                raw_values["aspect"].add(item.get("aspect", ""))
                raw_values["state"].update((item.get("before", ""), item.get("after", "")))
            for group in ("opens", "advances", "resolves"):
                for item in (contract.get("obligation_effects") or {}).get(group, []):
                    raw_values["obligation_key"].add(item.get("key", ""))

        entries = []
        for kind in _KINDS:
            grouped = {}
            for value in sorted(raw_values[kind]):
                raw = normalize_raw(value)
                if not raw:
                    continue
                cid = canonical_id(kind, raw)
                grouped.setdefault(cid, []).append(raw)
            for cid, aliases in sorted(grouped.items()):
                entries.append({
                    "kind": kind,
                    "canonical_id": cid,
                    "aliases": sorted(set(aliases)),
                    "raw_evidence": sorted(set(aliases)),
                })
        return cls(entries)

    def canonical(self, kind: str, value: object) -> str:
        raw = normalize_raw(value)
        return self._index.get((kind, raw), canonical_id(kind, raw))

    def to_dict(self) -> dict:
        return {"schema_version": self.schema_version, "entries": self.entries}

    @classmethod
    def from_dict(cls, data: dict) -> "StateVocabulary":
        if data.get("schema_version") != cls.schema_version:
            raise ValueError("不支持的 StateVocabulary schema_version")
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise ValueError("StateVocabulary entries 必须是数组")
        for entry in entries:
            if (
                entry.get("kind") not in _KINDS
                or not _IDENTIFIER.fullmatch(str(entry.get("canonical_id") or ""))
                or not entry.get("aliases")
                or not entry.get("raw_evidence")
            ):
                raise ValueError("StateVocabulary entry 格式无效")
        return cls(entries)
