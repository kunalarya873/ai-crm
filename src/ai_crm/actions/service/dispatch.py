from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import InvalidRequestError
from ...models import ActionExecution
from ..registry import ActionDefinition
from .effects_activity import _create_activity, _create_approval_work_item
from .effects_contacts import _assign_contact_owner, _update_contact
from .effects_external import _create_external_activity
from .effects_tasks import _create_task

__all__ = [
    "_execute_effect",
]


async def _execute_effect(
    session: AsyncSession,
    context: RequestContext,
    definition: ActionDefinition,
    raw_payload: dict[str, object],
    execution: ActionExecution,
) -> dict[str, object]:
    payload = definition.validate(raw_payload)
    if definition.executor_key == "task.create":
        return await _create_task(session, context, payload)
    if definition.executor_key == "contact.update":
        return await _update_contact(session, context, payload)
    if definition.executor_key == "contact.assign_owner":
        return await _assign_contact_owner(session, context, payload)
    if definition.executor_key == "activity.create":
        return await _create_activity(session, context, payload)
    if definition.executor_key == "approval.request":
        return await _create_approval_work_item(session, context, payload)
    if definition.executor_key == "integration.activity.create":
        return await _create_external_activity(session, context, payload, execution)
    raise InvalidRequestError(f"No executor registered for {definition.action_type}")
