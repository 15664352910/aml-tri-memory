"""AML compliance boundary: strict user_id isolation."""

from __future__ import annotations

import time

from app.config import Settings
from app.service import MemoryService
from app.store import MemoryStorage


def make_service() -> MemoryService:
    settings = Settings(
        memory_system_key="",
        database_url="",
        abstention_min_score=0.12,
        persona_promotion_threshold=2,
        default_expert_role="reviewer",
        recency_half_life_ms=30 * 24 * 3600 * 1000,
        max_messages_per_add=200,
    )
    return MemoryService(MemoryStorage(), settings)


def msg(content: str) -> dict:
    return {"role": "user", "content": content, "timestamp": time.time() * 1000}


def test_users_cannot_see_each_other_memory() -> None:
    service = make_service()
    service.add("req-a1", "user_a", "conv-a", [msg("My secret codeword is BLUEBIRD.")])
    service.add("req-b1", "user_b", "conv-b", [msg("I prefer tea over coffee.")])

    hits_a = service.search("user_a", "codeword", top_k=10)
    hits_b = service.search("user_b", "codeword", top_k=10)

    assert hits_a and "BLUEBIRD" in hits_a[0]["content"]
    assert hits_b == []  # user_b must never retrieve user_a's memory


def test_same_user_multiple_sessions_merge() -> None:
    service = make_service()
    service.add("req-1", "user_a", "conv-1", [msg("I love jazz.")])
    service.add("req-2", "user_a", "conv-2", [msg("I love jazz a lot, it is my passion.")])
    hits = service.search("user_a", "jazz", top_k=10)
    assert hits


def test_stats_are_per_user() -> None:
    service = make_service()
    service.add("req-1", "user_a", "conv-1", [msg("I like pasta.")])
    service.add("req-2", "user_b", "conv-1", [msg("I like ramen.")])
    assert service.stats("user_a")["events"] == 1
    assert service.stats("user_b")["events"] == 1
