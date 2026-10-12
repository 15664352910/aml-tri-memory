# AML Tri-Memory

A three-layer long-term memory service built for the **Agent Memory Leaderboard (AML) Cycle 2 — Textual Memory track, Open-source Methods division**. It exposes the platform's Add/Search contract and returns memory evidence only — the platform runs its own answer and eval pipeline.

The design ports the core ideas of the Tri-Memory research prototype — persona / episodic / world-model separation with typed governance — into a clean, dependency-light, competition-hardened service:

- **Typed layers, append-only evidence.** Raw conversation turns are stored as immutable episodic events; every derived record carries the ids of its source events (evidence chains).
- **Guarded write-back.** Persona traits promote to active memory only after threshold-many independent supporting events; rival values of the same trait stay visible as candidates instead of silently overwriting each other.
- **Conflict-aware world model.** A new value for the same (subject, relation) supersedes the old record (versioned) and opens a conflict record — contradictions are surfaced, never silently lost.
- **Stale/expired state.** Stale world records are hidden or penalized per role policy at recall.
- **Role-conditioned recall policies.** Layer weights and visibility differ per expert role; the AML adapter resolves each Search to the built-in `reviewer` policy because the platform contract does not carry roles.
- **Evidence-only Search with abstention.** Recall scores evidence with deterministic lexical + recency ranking; if nothing clears the abstention threshold, Search returns an empty `data` array instead of guessing.
- **Strict user_id isolation.** Every record is scoped by `user_id` at the storage layer; there is no cross-user retrieval path.
- **Synchronous, idempotent Add.** Records are fully stored and searchable before `success: true` is returned; retried `request_id`s return the stored response without re-ingesting.

## API

| Endpoint | Description |
| --- | --- |
| `POST /aml/add` | Ingest one chunk of messages for a `user_id`/`session_id`; idempotent by `request_id`. |
| `POST /aml/search` | Return up to `top_k` ranked memory evidence items for a `user_id`; empty array = abstention. |
| `GET /health` | Liveness and node stats (open). |

Contract fields follow the AML integration guide exactly (`request_id`, `messages[].role/content/timestamp`, `user_id`, `session_id`; `data[].id/content/score/created_at`). When `AML_MEMORY_SYSTEM_KEY` is set, `/aml/*` requires `Authorization: Bearer <key>`.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.api:app --reload        # open mode, in-memory storage
```

With auth and Postgres:

```bash
export AML_MEMORY_SYSTEM_KEY=...
export DATABASE_URL=postgresql://user:pass@localhost:5432/aml
uvicorn app.api:app
```

## Test and smoke

```bash
python -m pytest tests -q           # 15 tests: governance, isolation, contract
python scripts/smoke_platform.py    # simulated platform run incl. compliance checks
```

## Docker

```bash
docker build -t aml-tri-memory .
docker run -p 8000:8000 -e AML_MEMORY_SYSTEM_KEY=... [-e DATABASE_URL=...] aml-tri-memory
```

## Configuration

See [.env.example](.env.example). All tuning knobs (`ABSTENTION_MIN_SCORE`, `PERSONA_PROMOTION_THRESHOLD`, role defaults, recency half-life, chunk caps) are environment-driven; no retraining or external index is involved.

## Provenance and attribution

- Method lineage: Tri-Memory research prototype (persona / episodic / world-model layered memory with typed governance), re-implemented here for the AML contract.
- Scoring: deterministic BM25-style lexical saturation plus exponential recency decay; no LLM is called at Add or Search time.
- Extraction: rule-based typed extractor (`app/extractor.py`); no external datasets or pretrained models are used at serving time.

## Compliance notes

- Search never generates or composes answers; it only returns stored memory records as evidence.
- Retrieval isolation is enforced on `user_id` at the storage layer and covered by automated tests (`tests/test_isolation.py`).
- Evaluation data received during a run is used only for the evaluation and can be purged by deleting the storage tables/records; no request logging is performed by the service.
