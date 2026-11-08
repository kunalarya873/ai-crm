import base64
import json
from typing import Any

from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .api.deps import RequestContext
from .audit import record_audit
from .domain import NotFoundError
from .models import Activity, Company, Contact, Opportunity, Task
from .pagination import decode_cursor
from .schemas import ActivityRead, CompanyRead, ContactRead, OpportunityRead, TaskRead

EXPORTABLE: dict[str, tuple[Any, type[BaseModel]]] = {
    "contacts": (Contact, ContactRead),
    "companies": (Company, CompanyRead),
    "opportunities": (Opportunity, OpportunityRead),
    "activities": (Activity, ActivityRead),
    "tasks": (Task, TaskRead),
}


def _order_column(model: Any) -> Any:
    """Activities have no created_at; their immutable ingestion time orders the export."""
    return model.ingested_at if model is Activity else model.created_at


def _encode(model: Any, row: Any) -> str:
    raw = json.dumps(
        {"t": getattr(row, _order_column(model).key).isoformat(), "i": row.id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


async def export_rows(
    session: AsyncSession,
    context: RequestContext,
    resource: str,
    *,
    limit: int,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """One page of a tenant's records, archived ones included, plus the next-page cursor."""
    if resource not in EXPORTABLE:
        raise NotFoundError(f"Unknown export resource: {resource}")
    model, schema = EXPORTABLE[resource]
    order = _order_column(model)
    statement = select(model).where(model.tenant_id == context.tenant_id)
    if cursor is not None:
        moment, item_id = decode_cursor(cursor)
        statement = statement.where(or_(order < moment, and_(order == moment, model.id < item_id)))
    rows = (
        await session.scalars(statement.order_by(order.desc(), model.id.desc()).limit(limit + 1))
    ).all()
    items = rows[:limit]
    await record_audit(
        session,
        context,
        "export.read",
        "export",
        resource,
        details={"resource": resource, "rows": len(items)},
    )
    await session.commit()
    next_cursor = _encode(model, items[-1]) if len(rows) > limit else None
    return [schema.model_validate(row).model_dump(mode="json") for row in items], next_cursor
