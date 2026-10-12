"""FastAPI surface exposing the AML Add/Search contract.

- POST /aml/add    — synchronous ingestion, idempotent by request_id
- POST /aml/search — evidence-only retrieval; empty array = abstention
- GET  /health     — liveness + per-node stats (open, for ops)

Authentication: when AML_MEMORY_SYSTEM_KEY is set, every /aml/* request
must carry the Memory System Key in the Authorization header (any scheme:
`Bearer <key>` or `Token <key>` are both accepted; only the credential is
compared). The key never leaves server configuration.
"""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import FastAPI, HTTPException, Request

from .config import Settings, load_settings
from .schemas import AddRequest, AddResponse, SearchRequest, SearchResponse, SearchResultItem
from .service import MemoryService
from .store import build_storage



def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings()
    storage = build_storage(settings.database_url)
    service = MemoryService(storage, settings)

    app = FastAPI(title="AML Tri-Memory", version="0.1.0")

    def authorize(request: Request) -> None:
        if not settings.memory_system_key:
            return  # local/test mode: authentication disabled
        # Accept any auth scheme (Bearer / Token / none) and compare only the
        # credential, so the hosted API works with however the platform
        # chooses to send the Memory System Key.
        header = request.headers.get("Authorization", "")
        parts = header.split(None, 1)
        token = parts[1].strip() if len(parts) == 2 else ""
        if not token or not secrets.compare_digest(token, settings.memory_system_key):
            raise HTTPException(status_code=401, detail="invalid memory system key")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", **service.stats()}

    @app.post("/aml/add", response_model=AddResponse)
    def aml_add(
        payload: AddRequest,
        request: Request,
    ) -> AddResponse:
        authorize(request)
        try:
            result = service.add(
                request_id=payload.request_id,
                user_id=payload.user_id,
                session_id=payload.session_id,
                messages=[m.model_dump() for m in payload.messages],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return AddResponse(**{k: result[k] for k in ("success", "request_id", "user_id", "session_id")})

    @app.post("/aml/search", response_model=SearchResponse)
    def aml_search(
        payload: SearchRequest,
        request: Request,
    ) -> SearchResponse:
        authorize(request)
        data = service.search(
            user_id=payload.user_id,
            query=payload.query,
            top_k=payload.top_k,
            options=payload.options,
        )
        return SearchResponse(data=[SearchResultItem(**item) for item in data])

    return app


app = create_app()
