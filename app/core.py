"""Tri-Memory core: typed layers with governance, scoped to one user.

Ported from the Tri-Memory research prototype, competition-hardened:

- append-only episodic events as evidence;
- persona promotion only after N independent supporting events
  (guarded write-back against single-utterance pollution);
- world-model versioning: a new value for the same (subject, relation)
  supersedes the old record and opens a conflict instead of silently
  overwriting;
- stale/expired world records are hidden or penalized at recall;
- recall returns scored evidence across layers, never a composed answer;
- when nothing clears the abstention threshold, recall returns [].
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Optional

from . import extractor, texttools
from .config import Settings
from .models import (
    CONFLICT_OPEN,
    LAYER_EPISODIC,
    LAYER_PERSONA,
    LAYER_WORLD,
    PERSONA_ACTIVE,
    PERSONA_CANDIDATE,
    PERSONA_SUPERSEDED,
    ROLE_POLICIES,
    WORLD_ACTIVE,
    WORLD_CONFLICT_OPEN,
    WORLD_STALE,
    WORLD_SUPERSEDED,
    ConflictRecord,
    EventRecord,
    PersonaRecord,
    WorldRecord,
)
from .store import KIND_CONFLICT, KIND_EVENT, KIND_PERSONA, KIND_WORLD, Storage


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _policy(role: str) -> dict[str, Any]:
    return ROLE_POLICIES.get(role) or ROLE_POLICIES["reviewer"]


class TriMemoryCore:
    """All state for exactly one user_id."""

    def __init__(self, user_id: str, storage: Storage, settings: Settings) -> None:
        self.user_id = user_id
        self.storage = storage
        self.settings = settings

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------
    def _load_events(self) -> list[EventRecord]:
        return [EventRecord.from_dict(d) for d in self.storage.list_records(self.user_id, KIND_EVENT)]

    def _load_persona(self) -> list[PersonaRecord]:
        return [PersonaRecord.from_dict(d) for d in self.storage.list_records(self.user_id, KIND_PERSONA)]

    def _load_world(self) -> list[WorldRecord]:
        return [WorldRecord.from_dict(d) for d in self.storage.list_records(self.user_id, KIND_WORLD)]

    def _load_conflicts(self) -> list[ConflictRecord]:
        return [ConflictRecord.from_dict(d) for d in self.storage.list_records(self.user_id, KIND_CONFLICT)]

    # ------------------------------------------------------------------
    # ingestion (Add path) — fully synchronous
    # ------------------------------------------------------------------
    def add_messages(
        self,
        messages: list[dict[str, Any]],
        session_id: str,
        request_id: str,
    ) -> dict[str, int]:
        counts = {"events": 0, "persona_candidates": 0, "persona_promoted": 0, "world_written": 0, "conflicts_opened": 0}
        now = time.time() * 1000

        for index, message in enumerate(messages):
            content = (message.get("content") or "").strip()
            if not content:
                continue
            created_at = float(message.get("timestamp") or now)
            event = EventRecord(
                id=_new_id("evt"),
                content=content,
                role=message.get("role", "user"),
                session_id=session_id,
                created_at=created_at,
                request_id=request_id,
            )
            self.storage.put_record(self.user_id, KIND_EVENT, event.id, event.to_dict())
            counts["events"] += 1

            extraction = extractor.extract(content, speaker="user" if event.role == "user" else event.role)
            speaker = "user" if event.role == "user" else event.role

            for trait_type, subject, value in extraction.persona_candidates:
                subject = speaker if subject == "user" else subject
                promoted = self._upsert_persona_candidate(subject, trait_type, value, event, now)
                counts["persona_candidates"] += 1
                if promoted:
                    counts["persona_promoted"] += 1

            for relation, subject, value in extraction.world_statements:
                opened = self._upsert_world_statement(subject, relation, value, event, now)
                counts["world_written"] += 1
                if opened:
                    counts["conflicts_opened"] += 1

        return counts

    def _upsert_persona_candidate(self, subject: str, trait_type: str, value: str, event: EventRecord, now: float) -> bool:
        key = hashlib.sha1(f"{subject}|{trait_type}|{value}".lower().encode()).hexdigest()[:16]
        record_id = f"per_{key}"
        existing_payload = self.storage.get_record(self.user_id, KIND_PERSONA, record_id)

        if existing_payload is None:
            record = PersonaRecord(
                id=record_id,
                subject=subject,
                trait_type=trait_type,
                value=value,
                status=PERSONA_CANDIDATE,
                evidence=[event.id],
                support_count=1,
                created_at=now,
                updated_at=now,
            )
            self.storage.put_record(self.user_id, KIND_PERSONA, record_id, record.to_dict())
            return self._reconcile_trait(subject, trait_type, now)

        record = PersonaRecord.from_dict(existing_payload)
        if event.id not in record.evidence:
            record.evidence.append(event.id)
            record.support_count += 1
        record.updated_at = now
        self.storage.put_record(self.user_id, KIND_PERSONA, record_id, record.to_dict())
        return self._reconcile_trait(subject, trait_type, now)

    def _reconcile_trait(self, subject: str, trait_type: str, now: float) -> bool:
        """Trait-level promotion with contradiction awareness.

        A trait (subject, trait_type) promotes only when the total number
        of independent supporting events across its value variants reaches
        the threshold; the value with the most evidence becomes active and
        rival values stay candidates, so contradictions remain visible
        instead of silently promoting both sides.
        """
        group = [
            r
            for r in self._load_persona()
            if r.subject == subject and r.trait_type == trait_type
        ]
        if not group:
            return False
        threshold = self.settings.persona_promotion_threshold
        trait_support = sum(r.support_count for r in group)
        winner = max(group, key=lambda r: (r.support_count, -group.index(r)))
        promoted_now = False
        for record in group:
            new_status = PERSONA_ACTIVE if (trait_support >= threshold and record.id == winner.id) else PERSONA_CANDIDATE
            if new_status == PERSONA_ACTIVE and record.status != PERSONA_ACTIVE:
                promoted_now = True
            if record.status != new_status:
                record.status = new_status
                record.updated_at = now
                self.storage.put_record(self.user_id, KIND_PERSONA, record.id, record.to_dict())
        return promoted_now

    def _upsert_world_statement(self, subject: str, relation: str, value: str, event: EventRecord, now: float) -> bool:
        key = hashlib.sha1(f"{subject}|{relation}".lower().encode()).hexdigest()[:16]
        record_id = f"wor_{key}"
        existing_payload = self.storage.get_record(self.user_id, KIND_WORLD, record_id)
        opened_conflict = False

        if existing_payload is None:
            record = WorldRecord(
                id=record_id,
                subject=subject,
                relation=relation,
                value=value,
                status=WORLD_ACTIVE,
                evidence=[event.id],
                version=1,
                valid_from=event.created_at,
                created_at=now,
                updated_at=now,
            )
            self.storage.put_record(self.user_id, KIND_WORLD, record_id, record.to_dict())
            return False

        record = WorldRecord.from_dict(existing_payload)
        if record.value.strip().lower() == value.strip().lower():
            if event.id not in record.evidence:
                record.evidence.append(event.id)
            record.updated_at = now
            self.storage.put_record(self.user_id, KIND_WORLD, record_id, record.to_dict())
            return False

        # Contradicting new value: versioned supersede + conflict visibility.
        previous_status = record.status
        record.status = WORLD_SUPERSEDED
        record.updated_at = now
        self.storage.put_record(self.user_id, KIND_WORLD, record_id, record.to_dict())

        conflict = ConflictRecord(
            id=_new_id("cnf"),
            kind="world_supersede",
            subject=subject,
            relation=relation,
            old_value=record.value,
            new_value=value,
            status=CONFLICT_OPEN,
            created_at=now,
        )
        self.storage.put_record(self.user_id, KIND_CONFLICT, conflict.id, conflict.to_dict())
        opened_conflict = True

        new_record = WorldRecord(
            id=_new_id("wor"),
            subject=subject,
            relation=relation,
            value=value,
            status=WORLD_CONFLICT_OPEN if previous_status != WORLD_ACTIVE else WORLD_ACTIVE,
            evidence=[event.id],
            version=record.version + 1,
            valid_from=event.created_at,
            created_at=now,
            updated_at=now,
        )
        self.storage.put_record(self.user_id, KIND_WORLD, new_record.id, new_record.to_dict())
        return opened_conflict

    # ------------------------------------------------------------------
    # recall (Search path) — evidence only, never a composed answer
    # ------------------------------------------------------------------
    def recall(self, query: str, top_k: int, expert_role: Optional[str] = None, now_ms: Optional[float] = None) -> list[dict[str, Any]]:
        role = expert_role or self.settings.default_expert_role
        policy = _policy(role)
        if now_ms is None:
            now_ms = time.time() * 1000

        query_counts = texttools.term_counts(query)
        if not query_counts:
            return []

        events = self._load_events()
        event_content = {e.id: e.content for e in events}
        weights = policy["layer_weights"]
        half_life = self.settings.recency_half_life_ms
        results: list[dict[str, Any]] = []

        def add_item(record_id: str, content: str, created_at: float, lex: float, layer: str, evidence_bonus: float, stale_penalty: float) -> None:
            if lex <= 0:
                return  # no lexical grounding at all -> abstain
            recency = texttools.recency_factor(created_at, half_life, now_ms)
            score = weights.get(layer, 1.0) * lex * (0.6 + 0.4 * recency) * evidence_bonus * stale_penalty
            if score < self.settings.abstention_min_score:
                return
            results.append(
                {
                    "id": record_id,
                    "content": content,
                    "score": round(score, 6),
                    "created_at": texttools.iso_from_ms(created_at),
                }
            )

        for event in events:
            lex = texttools.lexical_score(query_counts, texttools.term_counts(event.content))
            add_item(event.id, event.content, event.created_at, lex, LAYER_EPISODIC, 1.0, 1.0)

        def evidence_grounded_lex(evidence_ids: list[str], own_text: str) -> float:
            # Evidence chains: persona/world records are also scored through
            # the content of their source events, so paraphrased questions
            # ("What does the user love?") can still surface the governed
            # record via its raw evidence.
            own = texttools.lexical_score(query_counts, texttools.term_counts(own_text))
            via_evidence = 0.0
            for eid in evidence_ids:
                content = event_content.get(eid)
                if content:
                    via_evidence = max(via_evidence, texttools.lexical_score(query_counts, texttools.term_counts(content)))
            return max(own, 0.9 * via_evidence)

        for persona in self._load_persona():
            if persona.status == PERSONA_SUPERSEDED:
                continue
            if persona.status == PERSONA_CANDIDATE:
                continue  # un-promoted candidates are not recalled (guarded write-back)
            if persona.visibility == "private" and not policy["include_private_persona"]:
                continue
            lex = evidence_grounded_lex(persona.evidence, persona.content_text)
            bonus = 1.0 + 0.05 * min(len(persona.evidence), 4)
            add_item(persona.id, persona.content_text, persona.updated_at, lex, LAYER_PERSONA, bonus, 1.0)

        for world in self._load_world():
            if world.status == WORLD_SUPERSEDED:
                continue
            stale_penalty = 1.0
            if world.status == WORLD_STALE or world.is_expired(now_ms):
                if not policy["include_stale_world"]:
                    continue
                stale_penalty = 0.5
            lex = evidence_grounded_lex(world.evidence, world.content_text)
            bonus = 1.0 + 0.05 * min(len(world.evidence), 4)
            add_item(world.id, world.content_text, world.updated_at, lex, LAYER_WORLD, bonus, stale_penalty)

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]

    # ------------------------------------------------------------------
    # introspection (not part of the AML contract; ops/debug only)
    # ------------------------------------------------------------------
    def stats(self) -> dict[str, int]:
        return {
            "events": len(self._load_events()),
            "persona": len(self._load_persona()),
            "persona_active": sum(1 for p in self._load_persona() if p.status == PERSONA_ACTIVE),
            "world": len(self._load_world()),
            "conflicts": len(self._load_conflicts()),
        }
