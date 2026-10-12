"""Typed memory records.

Three layers, each append-only at the event level and governed at the
record level:

- episodic: raw conversation events (evidence);
- persona: stable user traits, promoted only after repeated independent
  evidence (guarded write-back);
- world: entities / relations / state with versioning; a new value for
  the same (subject, relation) supersedes the old one and opens a
  conflict record instead of silently overwriting (conflict visibility).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

LAYER_EPISODIC = "episodic"
LAYER_PERSONA = "persona"
LAYER_WORLD = "world"

PERSONA_CANDIDATE = "candidate"
PERSONA_ACTIVE = "active"
PERSONA_SUPERSEDED = "superseded"

WORLD_ACTIVE = "active"
WORLD_SUPERSEDED = "superseded"
WORLD_STALE = "stale"
WORLD_CONFLICT_OPEN = "conflict_open"

CONFLICT_OPEN = "open"
CONFLICT_RESOLVED = "resolved"


@dataclass
class EventRecord:
    id: str
    content: str
    role: str
    session_id: str
    created_at: float  # ms
    salience: float = 1.0
    request_id: str = ""
    kind: str = LAYER_EPISODIC

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "role": self.role,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "salience": self.salience,
            "request_id": self.request_id,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "EventRecord":
        return EventRecord(**d)


@dataclass
class PersonaRecord:
    id: str
    subject: str
    trait_type: str
    value: str
    status: str = PERSONA_CANDIDATE
    evidence: list[str] = field(default_factory=list)
    support_count: int = 0
    visibility: str = "shared"
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def content_text(self) -> str:
        return f"{self.subject} {self.trait_type}: {self.value}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "trait_type": self.trait_type,
            "value": self.value,
            "status": self.status,
            "evidence": list(self.evidence),
            "support_count": self.support_count,
            "visibility": self.visibility,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "PersonaRecord":
        return PersonaRecord(**d)


@dataclass
class WorldRecord:
    id: str
    subject: str
    relation: str
    value: str
    status: str = WORLD_ACTIVE
    evidence: list[str] = field(default_factory=list)
    version: int = 1
    valid_from: float = 0.0
    stale_after_ms: Optional[float] = None
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def content_text(self) -> str:
        return f"{self.subject} {self.relation} {self.value}"

    def is_expired(self, now_ms: float) -> bool:
        return self.stale_after_ms is not None and now_ms > self.valid_from + self.stale_after_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "relation": self.relation,
            "value": self.value,
            "status": self.status,
            "evidence": list(self.evidence),
            "version": self.version,
            "valid_from": self.valid_from,
            "stale_after_ms": self.stale_after_ms,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "WorldRecord":
        return WorldRecord(**d)


@dataclass
class ConflictRecord:
    id: str
    kind: str  # "world_supersede" | "persona_contradiction"
    subject: str
    relation: str
    old_value: str
    new_value: str
    status: str = CONFLICT_OPEN
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "subject": self.subject,
            "relation": self.relation,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "status": self.status,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ConflictRecord":
        return ConflictRecord(**d)


# Role-conditioned recall policies: which layers are visible and how
# strongly each layer is weighted. The hosted AML adapter resolves every
# Search to `default_expert_role`; the policies remain because they are
# the routing core of the method.
ROLE_POLICIES: dict[str, dict[str, Any]] = {
    "reviewer": {
        "layer_weights": {LAYER_PERSONA: 1.0, LAYER_EPISODIC: 1.0, LAYER_WORLD: 0.9},
        "include_private_persona": False,
        "include_stale_world": True,
    },
    "planner": {
        "layer_weights": {LAYER_PERSONA: 0.6, LAYER_EPISODIC: 0.7, LAYER_WORLD: 1.0},
        "include_private_persona": False,
        "include_stale_world": False,
    },
    "communicator": {
        "layer_weights": {LAYER_PERSONA: 1.0, LAYER_EPISODIC: 0.8, LAYER_WORLD: 0.5},
        "include_private_persona": True,
        "include_stale_world": False,
    },
}
