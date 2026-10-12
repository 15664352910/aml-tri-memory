"""AML Add/Search contract schemas.

Field names and semantics follow the AML integration guide:
<https://agentmemoryleaderboard.ai/api-guide>
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AddMessage(BaseModel):
    role: str = Field(..., description="Message role: user or assistant.")
    content: str = Field(..., description="Original message text.")
    timestamp: Optional[int] = Field(default=None, description="Unix milliseconds.")


class AddRequest(BaseModel):
    request_id: str
    messages: list[AddMessage]
    user_id: str
    session_id: str


class AddResponse(BaseModel):
    success: bool
    request_id: str
    user_id: str
    session_id: str


class SearchRequest(BaseModel):
    query: str
    options: Optional[list[str]] = None
    user_id: str
    top_k: int = Field(default=100, ge=0, le=500)


class SearchResultItem(BaseModel):
    id: str
    content: str
    score: Optional[float] = None
    created_at: Optional[str] = None  # ISO 8601


class SearchResponse(BaseModel):
    data: list[SearchResultItem]
