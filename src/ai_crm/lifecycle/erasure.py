from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..domain import ConflictError, NotFoundError
from ..models import ErasureRecord, utc_now
from ..schemas import ErasureRequest
from .fields import ERASABLE
from .holds import require_no_hold

__all__ = ["ensure_not_erased", "erase_record"]


async def _existing(
    session: AsyncSession, tenant_id: str, resource: str, record_id: str
) -> ErasureRecord | None:
    return await session.scalar(
        select(ErasureRecord).where(
            ErasureRecord.tenant_id == tenant_id,
            ErasureRecord.resource_type == resource,
            ErasureRecord.record_id == record_id,
        )
    )


async def ensure_not_erased(
    session: AsyncSession, context: RequestContext, resource: str, record_id: str
) -> None:
    """Erased records stay retired: edits (including un-archiving) are refused."""
    if await _existing(session, context.tenant_id, resource, record_id) is not None:
        raise ConflictError("Record was erased and cannot be modified")


async def erase_record(
    session: AsyncSession,
    context: RequestContext,
    resource: str,
    record_id: str,
    payload: ErasureRequest,
) -> ErasureRecord:
    """Overwrite a record's personal fields in place and retire it. The row, its id and the
    links that point at it stay, so nothing is orphaned. Repeating the call is a no-op."""
    spec = ERASABLE.get(resource)
    if spec is None:
        raise NotFoundError("Unsupported resource")
    done = await _existing(session, context.tenant_id, resource, record_id)
    if done is not None:
        return done
    row = await session.scalar(
        select(spec.model).where(
            spec.model.id == record_id, spec.model.tenant_id == context.tenant_id
        )
    )
    if row is None:
        raise NotFoundError("Record not found")
    await require_no_hold(session, context, "record.erase", resource, record_id)
    for name, value in spec.fields.items():
        setattr(row, name, value(row) if callable(value) else value)
    if hasattr(row, "archived_at"):
        row.archived_at = row.archived_at or utc_now()
    if hasattr(row, "version"):
        row.version = row.version + 1
    erasure = ErasureRecord(
        tenant_id=context.tenant_id,
        resource_type=resource,
        record_id=record_id,
        erased_by=context.actor_id,
        reason=payload.reason.strip(),
    )
    session.add(erasure)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raced = await _existing(session, context.tenant_id, resource, record_id)
        if raced is None:
            raise
        return raced
    # Ids and the reason only: personal values must not reach the audit trail or the outbox.
    details = {"resource_type": resource, "record_id": record_id}
    await record_audit(
        session, context, "record.erased", resource, record_id,
        reason=erasure.reason, details=details,
    )
    await record_outbox_event(session, context, "record.erased", resource, record_id, details)
    await session.commit()
    await session.refresh(erasure)
    return erasure
