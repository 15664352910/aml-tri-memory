"""Core governance behavior: guarded promotion, conflict supersede,
stale penalty, abstention, ordering, top_k."""

from __future__ import annotations

import time

from app.config import Settings
from app.core import TriMemoryCore
from app.store import MemoryStorage


def make_core(threshold: int = 2, min_score: float = 0.12) -> TriMemoryCore:
    settings = Settings(
        memory_system_key="",
        database_url="",
        abstention_min_score=min_score,
        persona_promotion_threshold=threshold,
        default_expert_role="reviewer",
        recency_half_life_ms=30 * 24 * 3600 * 1000,
        max_messages_per_add=200,
    )
    return TriMemoryCore("user_a", MemoryStorage(), settings)


def msg(content: str, role: str = "user", ts: float | None = None) -> dict:
    return {"role": role, "content": content, "timestamp": ts or time.time() * 1000}


def test_persona_promotion_requires_threshold() -> None:
    core = make_core(threshold=2)
    core.add_messages([msg("I love hiking in the mountains.")], "s1", "req-1")
    persona = core._load_persona()
    assert len(persona) == 1
    assert persona[0].status == "candidate"
    # not recalled while candidate (guarded write-back)
    hits = core.recall("What does the user love?", top_k=10)
    assert not any(h["id"].startswith("per_") for h in hits)

    core.add_messages([msg("I love hiking on weekends too.")], "s2", "req-2")
    persona = core._load_persona()
    total_support = sum(p.support_count for p in persona)
    assert total_support == 2  # trait-level support reaches threshold
    assert sum(1 for p in persona if p.status == "active") == 1  # only the winning value promotes
    hits = core.recall("What does the user love?", top_k=10)
    assert any(h["id"].startswith("per_") for h in hits)


def test_world_supersede_opens_conflict() -> None:
    core = make_core()
    core.add_messages([msg("The project deadline is Friday.")], "s1", "req-1")
    core.add_messages([msg("The project deadline is Monday.")], "s1", "req-2")

    world = core._load_world()
    assert len(world) == 2
    superseded = [w for w in world if w.status == "superseded"]
    active = [w for w in world if w.status == "active"]
    assert len(superseded) == 1 and superseded[0].value == "Friday"
    assert len(active) == 1 and active[0].value == "Monday"
    assert active[0].version == 2

    conflicts = core._load_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0].old_value == "Friday" and conflicts[0].new_value == "Monday"

    hits = core.recall("What is the project deadline?", top_k=10)
    assert not any(h["content"].endswith("Friday") for h in hits)
    assert any("Monday" in h["content"] for h in hits)


def test_abstention_returns_empty() -> None:
    core = make_core()
    core.add_messages([msg("I bought apples and oranges at the market.")], "s1", "req-1")
    assert core.recall("quantum chromodynamics", top_k=10) == []


def test_top_k_and_ordering() -> None:
    core = make_core()
    core.add_messages(
        [
            msg("The user loves jazz music and plays the saxophone."),
            msg("The meeting with the Berlin team is on Tuesday."),
            msg("Dogs are wonderful animals."),
        ],
        "s1",
        "req-1",
    )
    hits = core.recall("jazz saxophone music", top_k=1)
    assert len(hits) == 1
    assert "jazz" in hits[0]["content"]
    hits = core.recall("the meeting", top_k=10)
    assert all(hits[i]["score"] >= hits[i + 1]["score"] for i in range(len(hits) - 1))


def test_stale_world_penalized() -> None:
    core = make_core()
    core.add_messages([msg("The user lives in Berlin.")], "s1", "req-1")
    for record in core._load_world():
        if record.relation == "location":
            record.status = "stale"
            core.storage.put_record(core.user_id, "world", record.id, record.to_dict())
    hits = core.recall("Where does the user live?", top_k=10)
    stale = [h for h in hits if "Berlin" in h["content"]]
    assert stale  # reviewer policy includes stale with penalty
    fresh = [h for h in hits if h["id"].startswith("evt_")]
    assert stale[0]["score"] < 1.0
