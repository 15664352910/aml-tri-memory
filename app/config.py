"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Authentication: the Memory System Key issued by the participant.
    # When empty, endpoints are open (only acceptable for local testing).
    memory_system_key: str
    # Persistent backend. Empty -> per-process in-memory storage.
    database_url: str
    # Abstention: search results below this normalized score are dropped;
    # if nothing survives, Search returns {"data": []}.
    abstention_min_score: float
    # Guarded write-back: persona candidates need this many independent
    # supporting events before promotion to active memory.
    persona_promotion_threshold: int
    # Default recall role. The AML contract does not send expert roles, so
    # the hosted adapter resolves every Search to this built-in policy.
    default_expert_role: str
    # Recency half-life in milliseconds for the recall-time decay term.
    recency_half_life_ms: float
    # Hard cap on a single Add chunk to bound ingestion latency.
    max_messages_per_add: int


def load_settings() -> Settings:
    return Settings(
        memory_system_key=os.getenv("AML_MEMORY_SYSTEM_KEY", ""),
        database_url=os.getenv("DATABASE_URL", ""),
        abstention_min_score=float(os.getenv("ABSTENTION_MIN_SCORE", "0.12")),
        persona_promotion_threshold=int(os.getenv("PERSONA_PROMOTION_THRESHOLD", "2")),
        default_expert_role=os.getenv("DEFAULT_EXPERT_ROLE", "reviewer"),
        recency_half_life_ms=float(os.getenv("RECENCY_HALF_LIFE_MS", str(30 * 24 * 3600 * 1000))),
        max_messages_per_add=int(os.getenv("MAX_MESSAGES_PER_ADD", "200")),
    )
