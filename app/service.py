"""User-scoped service layer: one TriMemoryCore per user_id, plus
idempotent Add handling keyed by request_id."""

from __future__ import annotations

import threading
from typing import Any, Optional

from .config import Settings
from .core import TriMemoryCore
from .store import Storage


class MemoryService:
    def __init__(self, storage: Storage, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings
        self._lock = threading.RLock()
        self._cores: dict[str, TriMemoryCore] = {}

    def core_for(self, user_id: str) -> TriMemoryCore:
        with self._lock:
            core = self._cores.get(user_id)
            if core is None:
                core = TriMemoryCore(user_id, self.storage, self.settings)
                self._cores[user_id] = core
            return core

    # ------------------------------------------------------------------
    # Add with idempotency: a repeated request_id returns the stored
    # response and never re-ingests (safe under platform retries).
    # ------------------------------------------------------------------
    def add(self, request_id: str, user_id: str, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if not messages:
            raise ValueError("messages must not be empty")
        if len(messages) > self.settings.max_messages_per_add:
            raise ValueError(f"too many messages in one Add (max {self.settings.max_messages_per_add})")

        cached = self.storage.get_idempotent_response(request_id)
        if cached is not None:
            return cached

        core = self.core_for(user_id)
        counts = core.add_messages(messages, session_id=session_id, request_id=request_id)
        response = {
            "success": True,
            "request_id": request_id,
            "user_id": user_id,
            "session_id": session_id,
            "counts": counts,
        }
        self.storage.put_idempotent_response(request_id, user_id, response)
        return response

    def search(self, user_id: str, query: str, top_k: int, options: Optional[list[str]] = None) -> list[dict[str, Any]]:
        if options:
            query = query + "\nOptions: " + " | ".join(options)
        core = self.core_for(user_id)
        return core.recall(query=query, top_k=top_k)

    def stats(self, user_id: Optional[str] = None) -> dict[str, Any]:
        if user_id:
            return self.core_for(user_id).stats()
        with self._lock:
            return {"users": len(self._cores)}
