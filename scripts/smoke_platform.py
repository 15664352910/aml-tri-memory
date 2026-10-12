"""Simulate the AML platform end-to-end against a local app instance.

Covers the same path the platform will exercise:
  1. Add chunks (multi-turn conversation) for two isolated users;
  2. Search questions per user;
  3. Compliance checks: cross-user isolation, idempotent retry, abstention
     (empty data array), evidence-only content, top_k, ordering.

Run:  python scripts/smoke_platform.py
Exits non-zero if any check fails.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures += 1


def main() -> int:
    settings = Settings(
        memory_system_key="smoke-key",
        database_url="",
        abstention_min_score=0.12,
        persona_promotion_threshold=2,
        default_expert_role="reviewer",
        recency_half_life_ms=30 * 24 * 3600 * 1000,
        max_messages_per_add=200,
    )
    client = TestClient(create_app(settings))
    headers = {"Authorization": "Bearer smoke-key"}
    ts = int(time.time() * 1000)

    # --- platform-style Adds -------------------------------------------------
    conv_a_chunks = [
        [
            {"role": "user", "content": "Hi! I just moved to Lisbon last month.", "timestamp": ts - 5 * 86400_000},
            {"role": "assistant", "content": "Welcome to Lisbon! How are you settling in?", "timestamp": ts - 5 * 86400_000 + 60_000},
            {"role": "user", "content": "I love surfing and I usually go to the beach every weekend.", "timestamp": ts - 4 * 86400_000},
        ],
        [
            {"role": "user", "content": "I love surfing, the waves near Cascais are amazing.", "timestamp": ts - 2 * 86400_000},
            {"role": "assistant", "content": "Sounds great. The project deadline is Friday this week.", "timestamp": ts - 2 * 86400_000 + 60_000},
            {"role": "user", "content": "Right, and the project deadline moved to Monday actually.", "timestamp": ts - 1 * 86400_000},
        ],
    ]
    for i, chunk in enumerate(conv_a_chunks):
        r = client.post(
            "/aml/add",
            json={
                "request_id": f"eval:run1:locomo_refined:conv-0:chunk-{i}",
                "messages": chunk,
                "user_id": "eval:run1:locomo:conv-0",
                "session_id": "eval:run1:sample:0",
            },
            headers=headers,
        )
        check(f"add chunk-{i} returns 200 + success", r.status_code == 200 and r.json()["success"], r.text[:120])

    client.post(
        "/aml/add",
        json={
            "request_id": "eval:run1:locomo_refined:conv-1:chunk-0",
            "messages": [
                {"role": "user", "content": "My secret codeword is BLUEBIRD.", "timestamp": ts},
                {"role": "user", "content": "I prefer quiet cafes for reading.", "timestamp": ts + 60_000},
            ],
            "user_id": "eval:run1:locomo:conv-1",
            "session_id": "eval:run1:sample:1",
        },
        headers=headers,
    )

    # --- Search: platform questions ------------------------------------------
    r = client.post(
        "/aml/search",
        json={"query": "What does the user love doing?", "user_id": "eval:run1:locomo:conv-0", "top_k": 10},
        headers=headers,
    )
    data = r.json()["data"]
    check("search finds surfing evidence", bool(data) and any("surfing" in d["content"] for d in data))
    check("scores ordered descending", all(data[i]["score"] >= data[i + 1]["score"] for i in range(len(data) - 1)))
    check("items carry id/content/score/created_at", all(set(d) == {"id", "content", "score", "created_at"} for d in data))

    r = client.post(
        "/aml/search",
        json={"query": "What is the project deadline?", "user_id": "eval:run1:locomo:conv-0", "top_k": 10},
        headers=headers,
    )
    data = r.json()["data"]
    check("superseded value (Friday) hidden", not any(d["content"].endswith("Friday") for d in data))
    check("current value (Monday) present", any("Monday" in d["content"] for d in data))

    # --- Compliance checks ----------------------------------------------------
    r = client.post(
        "/aml/search",
        json={"query": "What is the secret codeword?", "user_id": "eval:run1:locomo:conv-0", "top_k": 10},
        headers=headers,
    )
    check("cross-user isolation (no BLUEBIRD leak)", all("BLUEBIRD" not in d["content"] for d in r.json()["data"]))

    r = client.post(
        "/aml/search",
        json={"query": "Where does the user live?", "user_id": "eval:run1:locomo:conv-0", "top_k": 10},
        headers=headers,
    )
    check("cross-session merge within same user", any("Lisbon" in d["content"] for d in r.json()["data"]))

    r = client.post(
        "/aml/search",
        json={"query": "Who won the Nobel Prize in 1901?", "user_id": "eval:run1:locomo:conv-0", "top_k": 10},
        headers=headers,
    )
    check("abstention -> empty data array", r.json() == {"data": []})

    retry = client.post(
        "/aml/add",
        json={
            "request_id": "eval:run1:locomo_refined:conv-0:chunk-0",
            "messages": conv_a_chunks[0],
            "user_id": "eval:run1:locomo:conv-0",
            "session_id": "eval:run1:sample:0",
        },
        headers=headers,
    )
    r = client.post(
        "/aml/search",
        json={"query": "moved to Lisbon", "user_id": "eval:run1:locomo:conv-0", "top_k": 100},
        headers=headers,
    )
    moved_hits = [d for d in r.json()["data"] if "moved to Lisbon" in d["content"]]
    check("idempotent retry does not duplicate", retry.status_code == 200 and len(moved_hits) == 1, f"hits={len(moved_hits)}")

    r = client.post(
        "/aml/search",
        json={"query": "surfing", "user_id": "eval:run1:locomo:conv-0", "top_k": 2},
        headers=headers,
    )
    check("top_k respected", len(r.json()["data"]) <= 2)

    r = client.get("/health")
    check("health open", r.status_code == 200 and r.json()["status"] == "ok")

    unauth = client.post("/aml/search", json={"query": "x", "user_id": "u", "top_k": 1})
    check("unauthenticated search rejected", unauth.status_code == 401)

    print()
    if failures:
        print(f"{failures} check(s) FAILED")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
