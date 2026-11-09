import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...config import settings
from ...domain import InvalidRequestError, NotFoundError
from ...models import (
    ActionExecution,
    ActionProposal,
    utc_now,
)
from ..registry import ActionDefinition, get_action_definition
from .common import EXECUTION_STATUSES, PROPOSAL_STATUSES, _aware, _hash_payload

__all__ = [
    "_expiry", "_resource_refs", "_side_effects", "describe_proposal", "get_execution",
    "get_proposal", "list_executions", "list_proposals",
]


async def get_proposal(
    session: AsyncSession,
    context: RequestContext,
    proposal_id: str,
) -> ActionProposal:
    proposal = await session.scalar(
        select(ActionProposal).where(
            ActionProposal.id == proposal_id,
            ActionProposal.tenant_id == context.tenant_id,
        )
    )
    if proposal is None:
        raise NotFoundError("Action proposal not found")
    return proposal


async def get_execution(
    session: AsyncSession,
    context: RequestContext,
    execution_id: str,
) -> ActionExecution:
    execution = await session.scalar(
        select(ActionExecution).where(
            ActionExecution.id == execution_id,
            ActionExecution.tenant_id == context.tenant_id,
        )
    )
    if execution is None:
        raise NotFoundError("Action execution not found")
    return execution


def _expiry(expires_at: datetime | None) -> datetime:
    value = _aware(expires_at)
    if value is None:
        value = utc_now() + timedelta(hours=settings.action_default_expiration_hours)
    if value <= utc_now():
        raise InvalidRequestError("Action proposal expiration must be in the future")
    return value


def _resource_refs(action_type: str, payload: dict[str, object]) -> list[dict[str, object]]:
    keys = {
        "contact_id": "contact",
        "company_id": "company",
        "opportunity_id": "opportunity",
        "connection_id": "integration_connection",
    }
    refs: list[dict[str, object]] = []
    for key, resource_type in keys.items():
        value = payload.get(key)
        if isinstance(value, str) and value:
            refs.append({"resource_type": resource_type, "resource_id": value})
    if action_type == "contact.update" and isinstance(payload.get("contact_id"), str):
        refs.append({"resource_type": "contact", "resource_id": payload["contact_id"]})
    if action_type == "contact.assign_owner" and isinstance(payload.get("contact_id"), str):
        refs.append({"resource_type": "contact", "resource_id": payload["contact_id"]})
    return list({json.dumps(item, sort_keys=True): item for item in refs}.values())


def describe_proposal(
    action_type: str, payload: dict[str, object]
) -> tuple[list[dict[str, object]], str]:
    """Affected-resource refs and request hash a proposal of this shape would get."""
    definition = get_action_definition(action_type)
    normalized = definition.validate(payload).model_dump(mode="json", exclude_unset=True)
    return _resource_refs(action_type, normalized), _hash_payload(action_type, normalized)


def _side_effects(definition: ActionDefinition, supplied: list[str]) -> list[str]:
    return supplied or list(definition.expected_side_effects)


async def list_proposals(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    action_type: str | None = None,
    proposal_status: str | None = None,
) -> list[ActionProposal]:
    statement = select(ActionProposal).where(ActionProposal.tenant_id == context.tenant_id)
    if action_type:
        statement = statement.where(ActionProposal.action_type == action_type)
    if proposal_status:
        if proposal_status not in PROPOSAL_STATUSES:
            raise InvalidRequestError(f"Unsupported proposal status: {proposal_status}")
        statement = statement.where(ActionProposal.status == proposal_status)
    result = await session.scalars(
        statement.order_by(ActionProposal.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)


async def list_executions(
    session: AsyncSession,
    context: RequestContext,
    *,
    limit: int,
    offset: int,
    execution_status: str | None = None,
) -> list[ActionExecution]:
    statement = select(ActionExecution).where(ActionExecution.tenant_id == context.tenant_id)
    if execution_status:
        if execution_status not in EXECUTION_STATUSES:
            raise InvalidRequestError(f"Unsupported execution status: {execution_status}")
        statement = statement.where(ActionExecution.status == execution_status)
    result = await session.scalars(
        statement.order_by(ActionExecution.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result)
