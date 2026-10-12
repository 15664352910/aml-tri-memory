"""HTTP contract tests against the AML Add/Search API surface."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings


def make_client(key: str = "") -> TestClient:
    settings = Settings(
        memory_system_key=key,
        database_url="",
        abstention_min_score=0.12,
        persona_promotion_threshold=2,
        default_expert_role="reviewer",
        recency_half_life_ms=30 * 24 * 3600 * 1000,
        max_messages_per_add=200,
    )
    return TestClient(create_app(settings))


def add_payload(request_id: str, user_id: str, content: str) -> dict:
    return {
        "request_id": request_id,
        "messages": [{"role": "user", "content": content, "timestamp": int(time.time() * 1000)}],
        "user_id": user_id,
        "session_id": "conv-0",
    }


def test_add_response_echoes_contract_fields() -> None:
    client = make_client()
    r = client.post("/aml/add", json=add_payload("eval:run1:chunk-0", "eval:run1:user", "I love cycling."))
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "success": True,
        "request_id": "eval:run1:chunk-0",
        "user_id": "eval:run1:user",
        "session_id": "conv-0",
    }


def test_search_response_shape_and_ordering() -> None:
    client = make_client()
    client.post("/aml/add", json=add_payload("c1", "u1", "The user loves cycling and owns a road bike."))
    client.post("/aml/add", json=add_payload("c2", "u1", "Dogs are loyal animals."))
    r = client.post("/aml/search", json={"query": "cycling bike", "user_id": "u1", "top_k": 100})
    assert r.status_code == 200
    data = r.json()["data"]
    assert isinstance(data, list)
    assert data[0]["content"]
    for item in data:
        assert set(item) == {"id", "content", "score", "created_at"}
    assert all(data[i]["score"] >= data[i + 1]["score"] for i in range(len(data) - 1))


def test_search_empty_array_on_no_evidence() -> None:
    client = make_client()
    client.post("/aml/add", json=add_payload("c1", "u1", "I like apples."))
    r = client.post("/aml/search", json={"query": "nuclear physics", "user_id": "u1", "top_k": 100})
    assert r.json() == {"data": []}


def test_top_k_is_respected() -> None:
    client = make_client()
    messages = [{"role": "user", "content": f"I enjoy activity number {i}.", "timestamp": int(time.time() * 1000)} for i in range(5)]
    r = client.post("/aml/add", json={"request_id": "c1", "messages": messages, "user_id": "u1", "session_id": "s"})
    assert r.status_code == 200
    r = client.post("/aml/search", json={"query": "activity", "user_id": "u1", "top_k": 2})
    assert len(r.json()["data"]) <= 2


def test_idempotent_add_does_not_duplicate() -> None:
    client = make_client()
    payload = add_payload("dup-1", "u1", "I love kayaking.")
    first = client.post("/aml/add", json=payload)
    second = client.post("/aml/add", json=payload)
    assert first.json() == second.json()
    r = client.post("/aml/search", json={"query": "kayaking", "user_id": "u1", "top_k": 100})
    kayaking_hits = [d for d in r.json()["data"] if "kayaking" in d["content"]]
    assert len(kayaking_hits) == 1  # exactly one stored event


def test_auth_required_when_key_configured() -> None:
    client = make_client(key="secret-key")
    assert client.post("/aml/add", json=add_payload("c1", "u1", "hello")).status_code == 401
    headers = {"Authorization": "Bearer secret-key"}
    assert client.post("/aml/add", json=add_payload("c1", "u1", "hello"), headers=headers).status_code == 200
    assert client.post("/aml/search", json={"query": "hello", "user_id": "u1", "top_k": 5}, headers=headers).status_code == 200
    assert client.post("/aml/search", json={"query": "hello", "user_id": "u1", "top_k": 5}, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_auth_accepts_token_scheme() -> None:
    client = make_client(key="secret-key")
    headers = {"Authorization": "Token secret-key"}
    assert client.post("/aml/add", json=add_payload("c1", "u1", "hello"), headers=headers).status_code == 200
    assert client.post("/aml/search", json={"query": "hello", "user_id": "u1", "top_k": 5}, headers=headers).status_code == 200


def test_health_is_open() -> None:
    client = make_client(key="secret-key")
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
