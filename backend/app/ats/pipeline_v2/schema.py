"""Pipeline v2 data shapes for keyword ledger + hard insert."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Decision = Literal["Claim", "Bridge", "Omit", "Flag"]
Priority = Literal["must_have", "nice_to_have", "inferred"]


@dataclass
class EvidenceHit:
    source: str = "base_cv"
    snippet: str = ""
    match_via: str = ""
    char_start: int = -1
    char_end: int = -1


@dataclass
class TermPlacements:
    skills: bool = True
    summary: bool = False
    bullets_min: int = 0
    bullets_max: int = 2


@dataclass
class SurfaceForms:
    write_as: str = ""
    skills_as: str = ""
    allowed_extra: list[str] = field(default_factory=list)


@dataclass
class TermStatus:
    in_draft_skills: bool = False
    in_draft_summary: bool = False
    in_draft_bullets: int = 0
    hard_insert_applied: bool = False


@dataclass
class KeywordTerm:
    id: str
    jd_term: str
    priority: Priority
    aliases: list[str]
    decision: Decision
    confidence: float = 0.0
    evidence: EvidenceHit = field(default_factory=EvidenceHit)
    bridge_phrase: str | None = None
    omit_reason: str | None = None
    placements: TermPlacements = field(default_factory=TermPlacements)
    surface_forms: SurfaceForms = field(default_factory=SurfaceForms)
    status: TermStatus = field(default_factory=TermStatus)
    skills_category: str | None = None  # preferred existing category for hard-insert

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KeywordLedger:
    version: str = "2.0"
    job: dict[str, str] = field(default_factory=dict)
    generated_at: str = ""
    source: dict[str, Any] = field(default_factory=dict)
    terms: list[KeywordTerm] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    placement_plan: dict[str, Any] = field(default_factory=dict)
    insert_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "job": self.job,
            "generated_at": self.generated_at,
            "source": self.source,
            "terms": [t.to_dict() for t in self.terms],
            "summary": self.summary,
            "placement_plan": self.placement_plan,
            "insert_log": self.insert_log,
        }

    def scored_write_as(self) -> list[str]:
        """Claim + Bridge surfaces only (Omit never scored)."""
        out: list[str] = []
        seen: set[str] = set()
        for t in self.terms:
            if t.decision not in ("Claim", "Bridge"):
                continue
            surface = (t.surface_forms.write_as or t.jd_term).strip()
            if not surface:
                continue
            key = surface.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(surface)
        return out

    def claim_must_haves(self) -> list[KeywordTerm]:
        return [
            t
            for t in self.terms
            if t.decision == "Claim" and t.priority == "must_have"
        ]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def term_id(jd_term: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in jd_term.lower()).strip("_")
    return f"kw_{slug[:48] or 'term'}"
