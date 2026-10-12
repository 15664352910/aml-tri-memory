"""Storage backends, strictly scoped by user_id.

Every read and write carries a user_id; there is no global cross-user
view anywhere in the storage layer. This is an AML compliance boundary:
retrieval isolation is based on user_id.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Optional, Protocol

from .models import ConflictRecord, EventRecord, PersonaRecord, WorldRecord

KIND_EVENT = "event"
KIND_PERSONA = "persona"
KIND_WORLD = "world"
KIND_CONFLICT = "conflict"


class Storage(Protocol):
    def put_record(self, user_id: str, kind: str, record_id: str, payload: dict[str, Any]) -> None: ...
    def get_record(self, user_id: str, kind: str, record_id: str) -> Optional[dict[str, Any]]: ...
    def list_records(self, user_id: str, kind: str) -> list[dict[str, Any]]: ...
    def put_idempotent_response(self, request_id: str, user_id: str, payload: dict[str, Any]) -> None: ...
    def get_idempotent_response(self, request_id: str) -> Optional[dict[str, Any]]: ...


class MemoryStorage:
    """Process-local storage. Default for tests and single-node hosting."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._idempotent: dict[str, tuple[str, dict[str, Any]]] = {}

    def put_record(self, user_id: str, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._records[(user_id, kind, record_id)] = json.loads(json.dumps(payload))

    def get_record(self, user_id: str, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            payload = self._records.get((user_id, kind, record_id))
            return json.loads(json.dumps(payload)) if payload is not None else None

    def list_records(self, user_id: str, kind: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                json.loads(json.dumps(v))
                for (uid, k, _), v in self._records.items()
                if uid == user_id and k == kind
            ]

    def put_idempotent_response(self, request_id: str, user_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._idempotent[request_id] = (user_id, json.loads(json.dumps(payload)))

    def get_idempotent_response(self, request_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            entry = self._idempotent.get(request_id)
            return json.loads(json.dumps(entry[1])) if entry is not None else None


class PostgresStorage:
    """PostgreSQL backend (psycopg 3). Records live in one table keyed by
    (user_id, kind, id); idempotent Add responses are keyed by request_id."""

    def __init__(self, database_url: str) -> None:
        import psycopg  # imported lazily: optional dependency

        self._psycopg = psycopg
        self._dsn = database_url
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(self._dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    PRIMARY KEY (user_id, kind, record_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotent_responses (
                    request_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    payload JSONB NOT NULL
                )
                """
            )
            conn.commit()

    def put_record(self, user_id: str, kind: str, record_id: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_records (user_id, kind, record_id, payload)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (user_id, kind, record_id) DO UPDATE SET payload = EXCLUDED.payload
                """,
                (user_id, kind, record_id, json.dumps(payload)),
            )
            conn.commit()

    def get_record(self, user_id: str, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM memory_records WHERE user_id=%s AND kind=%s AND record_id=%s",
                (user_id, kind, record_id),
            ).fetchone()
            return dict(row[0]) if row else None

    def list_records(self, user_id: str, kind: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM memory_records WHERE user_id=%s AND kind=%s",
                (user_id, kind),
            ).fetchall()
            return [dict(row[0]) for row in rows]

    def put_idempotent_response(self, request_id: str, user_id: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO idempotent_responses (request_id, user_id, payload)
                VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (request_id) DO NOTHING
                """,
                (request_id, user_id, json.dumps(payload)),
            )
            conn.commit()

    def get_idempotent_response(self, request_id: str) -> Optional[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM idempotent_responses WHERE request_id=%s",
                (request_id,),
            ).fetchone()
            return dict(row[0]) if row else None


def build_storage(database_url: str) -> Storage:
    if database_url:
        return PostgresStorage(database_url)
    return MemoryStorage()
