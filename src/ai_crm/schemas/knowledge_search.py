from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "KnowledgeContextItem", "KnowledgeContextRequest", "KnowledgeContextResponse",
    "KnowledgeSearchResponse", "KnowledgeSearchResult",
]


class KnowledgeSearchResult(BaseModel):
    chunk_id: str
    text: str
    title: str
    score: float
    freshness: str
    source_id: str
    source_type: str
    source_record_id: str
    source_url: str | None
    source_version: int
    chunk_index: int
    owner_id: str | None
    effective_at: datetime | None
    fresh_until: datetime | None
    citation: dict[str, object]


class KnowledgeSearchResponse(BaseModel):
    query: str
    items: list[KnowledgeSearchResult]
    limit: int
    offset: int
    next_offset: int | None
    insufficient_evidence: bool
    evidence_reason: str | None


class KnowledgeContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=500)
    customer_id: str | None = Field(default=None, max_length=100)
    workflow_id: str | None = Field(default=None, max_length=100)
    task_id: str | None = Field(default=None, max_length=100)
    action_type: str | None = Field(default=None, max_length=100)
    source_types: list[str] = Field(default_factory=list, max_length=20)
    max_items: int = Field(default=8, ge=1, le=50)
    max_chars: int = Field(default=12000, ge=100, le=50000)
    include_stale: bool = False

    @field_validator("query", "customer_id", "workflow_id", "task_id", "action_type")
    @classmethod
    def strip_context_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class KnowledgeContextItem(BaseModel):
    chunk_id: str
    text: str
    title: str
    score: float
    freshness: str
    citation: dict[str, object]


class KnowledgeContextResponse(BaseModel):
    assembly_id: str
    query: str
    items: list[KnowledgeContextItem]
    used_chars: int
    max_items: int
    max_chars: int
    truncated: bool
    insufficient_evidence: bool
