from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import InvalidRequestError, PreconditionRequiredError, VersionConflictError
from ...models import KnowledgeSource, utc_now
from ...schemas import KnowledgeSourceUpdate
from ..domain import validate_source_fields
from .read import get_source_for_tenant, queue_index_job_in_session

__all__ = [
    "update_source",
]


async def update_source(
    session: AsyncSession,
    context: RequestContext,
    source_id: str,
    payload: KnowledgeSourceUpdate,
    expected_version: int | None,
) -> KnowledgeSource:
    if expected_version is None:
        raise PreconditionRequiredError("If-Match header is required")
    if expected_version < 1:
        raise InvalidRequestError("If-Match must contain a positive integer version")
    source = await get_source_for_tenant(session, context, source_id)
    if source.version != expected_version:
        raise VersionConflictError("record_version_conflict")
    changes = payload.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    if not changes and archived is None:
        raise InvalidRequestError("At least one field is required")
    visibility = changes.get("visibility", source.visibility)
    sensitivity = changes.get("sensitivity", source.sensitivity)
    validate_source_fields(source.source_type, visibility, sensitivity)
    if visibility == "restricted" and not changes.get(
        "allowed_user_ids", source.allowed_user_ids
    ):
        raise InvalidRequestError("Restricted knowledge sources require allowed_user_ids")
    for key, value in changes.items():
        setattr(source, key, value)
    if visibility == "owner" and source.owner_id is None:
        source.owner_id = context.actor_id
    if archived is not None:
        source.archived_at = utc_now() if archived else None
        source.status = "archived" if archived else "active"
        source.searchable = not archived
    source.version = expected_version + 1
    source.source_updated_at = utc_now()
    await session.flush()
    job = await queue_index_job_in_session(session, source)
    await record_audit(
        session,
        context,
        "knowledge.source.updated",
        "knowledge_source",
        source.id,
        details={"version": source.version, "index_job_id": job.id},
    )
    await record_outbox_event(
        session,
        context,
        "knowledge.source.updated",
        "knowledge_source",
        source.id,
        {"version": source.version, "index_job_id": job.id},
    )
    await session.commit()
    await session.refresh(source)
    return source
