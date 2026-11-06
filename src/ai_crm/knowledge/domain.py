import re
from dataclasses import dataclass
from datetime import datetime

from ..api.deps import RequestContext
from ..config import settings
from ..domain import InvalidRequestError
from ..models import KnowledgeChunk, KnowledgeContextAssembly, KnowledgeSource, utc_now
from ..permissions import Permission

SOURCE_TYPES = frozenset(
    {"crm_record", "activity", "document", "procedure", "template", "imported"}
)
VISIBILITIES = frozenset({"tenant", "owner", "restricted"})
SENSITIVITIES = frozenset({"normal", "sensitive"})


@dataclass(frozen=True)
class KnowledgeHit:
    chunk: KnowledgeChunk
    source: KnowledgeSource
    score: float
    freshness: str


@dataclass(frozen=True)
class ContextItem:
    chunk_id: str
    text: str
    title: str
    score: float
    freshness: str
    citation: dict[str, object]


@dataclass(frozen=True)
class ContextResult:
    assembly: KnowledgeContextAssembly
    items: list[ContextItem]


def validate_source_fields(
    source_type: str,
    visibility: str,
    sensitivity: str,
) -> None:
    if source_type not in SOURCE_TYPES:
        raise InvalidRequestError(f"Unsupported knowledge source type: {source_type}")
    if visibility not in VISIBILITIES:
        raise InvalidRequestError(f"Unsupported knowledge visibility: {visibility}")
    if sensitivity not in SENSITIVITIES:
        raise InvalidRequestError(f"Unsupported knowledge sensitivity: {sensitivity}")


def source_visible(source: KnowledgeSource, context: RequestContext) -> bool:
    if (
        source.sensitivity == "sensitive"
        and Permission.KNOWLEDGE_SENSITIVE not in context.permissions
    ):
        return False
    if source.visibility == "tenant":
        return True
    if source.visibility == "owner":
        return source.owner_id == context.actor_id
    if source.visibility == "restricted":
        return context.actor_id in (source.allowed_user_ids or [])
    return False


def freshness(source: KnowledgeSource, now: datetime | None = None) -> str:
    if source.fresh_until is None:
        return "unknown"
    freshness_now = now or utc_now()
    fresh_until = source.fresh_until
    if fresh_until.tzinfo is None:
        fresh_until = fresh_until.replace(tzinfo=freshness_now.tzinfo)
    return "fresh" if freshness_now <= fresh_until else "stale"


def tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", value.casefold())


def chunk_content(content: str) -> list[str]:
    normalized = " ".join(content.split())
    if not normalized:
        return []
    chunks: list[str] = []
    remaining = normalized
    while remaining:
        if len(remaining) <= settings.knowledge_chunk_size:
            chunks.append(remaining)
            break
        boundary = remaining.rfind(" ", 0, settings.knowledge_chunk_size + 1)
        if boundary < 1:
            boundary = settings.knowledge_chunk_size
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    return chunks


def citation(source: KnowledgeSource, chunk: KnowledgeChunk) -> dict[str, object]:
    return {
        "source_id": source.id,
        "source_type": source.source_type,
        "source_record_id": source.source_record_id,
        "source_version": source.version,
        "source_url": source.source_url,
        "title": source.title,
        "chunk_index": chunk.chunk_index,
        "effective_at": source.effective_at.isoformat() if source.effective_at else None,
        "fresh_until": source.fresh_until.isoformat() if source.fresh_until else None,
    }
