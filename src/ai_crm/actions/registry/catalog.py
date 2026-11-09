from ...config import settings
from ...domain import InvalidRequestError
from ...permissions import Permission
from ...schemas import ActivityCreate, TaskCreate
from .models import (
    ActionDefinition,
    ApprovalRequestAction,
    ContactAssignOwnerAction,
    ContactUpdateAction,
    ExternalActivityAction,
)

__all__ = [
    "ACTION_REGISTRY", "get_action_definition",
]


ACTION_REGISTRY: dict[str, ActionDefinition] = {
    "task.create": ActionDefinition(
        action_type="task.create",
        version="v1",
        required_permission=Permission.TASKS_CREATE,
        risk_level="low",
        requires_approval=True,
        payload_model=TaskCreate,
        timeout_seconds=settings.action_timeout_seconds,
        max_attempts=settings.action_max_attempts,
        affected_resource_types=("task", "contact", "opportunity"),
        executor_key="task.create",
        expected_side_effects=("create_task", "write_audit_event", "publish_outbox_event"),
    ),
    "contact.update": ActionDefinition(
        action_type="contact.update",
        version="v1",
        required_permission=Permission.CONTACTS_UPDATE,
        risk_level="medium",
        requires_approval=True,
        payload_model=ContactUpdateAction,
        timeout_seconds=settings.action_timeout_seconds,
        max_attempts=settings.action_max_attempts,
        affected_resource_types=("contact",),
        executor_key="contact.update",
        expected_side_effects=("update_contact", "write_audit_event", "publish_outbox_event"),
    ),
    "contact.assign_owner": ActionDefinition(
        action_type="contact.assign_owner",
        version="v1",
        required_permission=Permission.CONTACTS_UPDATE,
        risk_level="low",
        requires_approval=True,
        payload_model=ContactAssignOwnerAction,
        timeout_seconds=settings.action_timeout_seconds,
        max_attempts=settings.action_max_attempts,
        affected_resource_types=("contact",),
        executor_key="contact.assign_owner",
        expected_side_effects=("update_contact_owner", "write_audit_event", "publish_outbox_event"),
    ),
    "activity.create": ActionDefinition(
        action_type="activity.create",
        version="v1",
        required_permission=Permission.ACTIVITIES_CREATE,
        risk_level="low",
        requires_approval=True,
        payload_model=ActivityCreate,
        timeout_seconds=settings.action_timeout_seconds,
        max_attempts=settings.action_max_attempts,
        affected_resource_types=("activity", "contact", "company", "opportunity"),
        executor_key="activity.create",
        expected_side_effects=("create_activity", "write_audit_event", "publish_outbox_event"),
    ),
    "approval.request": ActionDefinition(
        action_type="approval.request",
        version="v1",
        required_permission=Permission.WORK_MANAGE,
        risk_level="low",
        requires_approval=True,
        payload_model=ApprovalRequestAction,
        timeout_seconds=settings.action_timeout_seconds,
        max_attempts=settings.action_max_attempts,
        affected_resource_types=("work_item",),
        executor_key="approval.request",
        expected_side_effects=(
            "create_approval_work_item",
            "write_audit_event",
            "publish_outbox_event",
        ),
    ),
    "integration.activity.create": ActionDefinition(
        action_type="integration.activity.create",
        version="v1",
        required_permission=Permission.INTEGRATIONS_WRITE,
        risk_level="high",
        requires_approval=True,
        payload_model=ExternalActivityAction,
        timeout_seconds=settings.action_timeout_seconds,
        max_attempts=settings.action_max_attempts,
        affected_resource_types=("integration_connection", "external_write"),
        executor_key="integration.activity.create",
        expected_side_effects=(
            "external_activity_create",
            "write_audit_event",
            "publish_outbox_event",
        ),
    ),
}


def get_action_definition(action_type: str) -> ActionDefinition:
    definition = ACTION_REGISTRY.get(action_type)
    if definition is None:
        raise InvalidRequestError(f"Unsupported action type: {action_type}")
    return definition
