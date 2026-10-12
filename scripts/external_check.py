"""External HTTP client check against a live AML Tri-Memory server.

Usage:
    python scripts/external_check.py [base_url] [key]

Sends real HTTP requests (httpx) to a running uvicorn instance and
verifies the AML Add/Search contract end to end. Exits non-zero on failure.
"""

from __future__ import annotations

import sys
import time

import httpx

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures += 1


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8123"
    key = sys.argv[2] if len(sys.argv) > 2 else ""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    ts = int(time.time() * 1000)

    with httpx.Client(base_url=base, headers=headers, timeout=30.0) as client:
        r = client.get("/health")
        check("GET /health reachable", r.status_code == 200, r.text[:100])

        payload = {
            "request_id": "ext:run1:conv-0:chunk-0",
            "messages": [
                {"role": "user", "content": "I moved to Porto two weeks ago.", "timestamp": ts - 14 * 86400_000},
                {"role": "assistant", "content": "Porto is a lovely city!", "timestamp": ts - 14 * 86400_000 + 30_000},
                {"role": "user", "content": "I love port wine and I love hiking along the coast.", "timestamp": ts - 10 * 86400_000},
                {"role": "user", "content": "I love hiking, the coastal trails are beautiful.", "timestamp": ts - 3 * 86400_000},
                {"role": "user", "content": "The visa appointment is on November 3rd.", "timestamp": ts - 86400_000},
            ],
            "user_id": "ext:run1:user-a",
            "session_id": "ext:run1:sample:0",
        }
        r = client.post("/aml/add", json=payload)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        check(
            "POST /aml/add 200 + echoes contract fields",
            r.status_code == 200
            and body.get("success") is True
            and body.get("request_id") == payload["request_id"]
            and body.get("user_id") == payload["user_id"]
            and body.get("session_id") == payload["session_id"],
            f"http={r.status_code} body={r.text[:140]}",
        )

        r2 = client.post(
            "/aml/add",
            json={
                "request_id": "ext:run1:conv-9:chunk-0",
                "messages": [{"role": "user", "content": "My passport number is XK123456.", "timestamp": ts}],
                "user_id": "ext:run1:user-b",
                "session_id": "ext:run1:sample:9",
            },
        )
        check("second user ingested", r2.status_code == 200)

        def search(user_id: str, query: str, top_k: int = 10) -> list[dict]:
            r = client.post("/aml/search", json={"query": query, "user_id": user_id, "top_k": top_k})
            assert r.status_code == 200, f"search http={r.status_code}: {r.text[:200]}"
            return r.json()["data"]

        data = search("ext:run1:user-a", "What does the user love?")
        check("search surfaces persona/world evidence", any("hiking" in d["content"] for d in data))
        check("scores sorted desc", all(data[i]["score"] >= data[i + 1]["score"] for i in range(len(data) - 1)))
        check(
            "items expose id/content/score/created_at",
            data and all(set(d) == {"id", "content", "score", "created_at"} for d in data),
        )

        data = search("ext:run1:user-a", "When is the visa appointment?")
        check("world schedule record retrieved", any("November 3rd" in d["content"] for d in data))

        data = search("ext:run1:user-a", "Who wrote Hamlet?")
        check("abstention returns empty array", data == [])

        data = search("ext:run1:user-a", "passport number")
        check("user_id isolation (no passport leak)", all("XK123456" not in d["content"] for d in data))

        data_b = search("ext:run1:user-b", "passport number")
        check("owning user retrieves own memory", any("XK123456" in d["content"] for d in data_b))

        retry = client.post("/aml/add", json=payload)
        data = search("ext:run1:user-a", "moved to Porto", top_k=100)
        moved = [d for d in data if "moved to Porto" in d["content"]]
        check("idempotent retry, no duplicate ingest", retry.status_code == 200 and len(moved) == 1, f"hits={len(moved)}")

        noauth = httpx.Client(base_url=base, timeout=30.0)
        r = noauth.post("/aml/search", json={"query": "x", "user_id": "u", "top_k": 1})
        expected = 401 if key else 200
        check("auth enforced as configured", r.status_code == expected, f"http={r.status_code}, expected={expected}")
        noauth.close()

        r = client.get("/health")
        stats = r.json()
        check("health stats reflect ingestion", stats.get("users", 0) >= 2, r.text[:120])
    print()
    if failures:
        print(f"{failures} external check(s) FAILED")
        return 1
    print("All external HTTP checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
