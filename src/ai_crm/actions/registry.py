from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..config import settings
from ..domain import InvalidRequestError
from ..permissions import Permission
from ..schemas import ActivityCreate, ContactUpdate, TaskCreate


class ContactUpdateAction(BaseModel):
    contact_id: str = Field(min_length=1, max_length=36)
    expected_version: int = Field(ge=1)
    changes: ContactUpdate


class ContactAssignOwnerAction(BaseModel):
    contact_id: str = Field(min_length=1, max_length=36)
    expected_version: int = Field(ge=1)
    owner_id: str | None = Field(default=None, max_length=100)


class ApprovalRequestAction(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    assignee_id: str | None = Field(default=None, max_length=100)
    due_at: datetime | None = None
    source: str | None = Field(default="action.proposal", max_length=100)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class ExternalActivityAction(BaseModel):
    connection_id: str = Field(min_length=1, max_length=36)
    subject: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=10000)

    @field_validator("connection_id", "subject")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


@dataclass(frozen=True)
class ActionDefinition:
    action_type: str
    version: str
    required_permission: Permission
    risk_level: str
    requires_approval: bool
    payload_model: type[BaseModel]
    timeout_seconds: int
    max_attempts: int
    affected_resource_types: tuple[str, ...]
    executor_key: str
    expected_side_effects: tuple[str, ...]

    def validate(self, payload: dict[str, Any]) -> BaseModel:
        try:
            return self.payload_model.model_validate(payload)
        except ValueError as error:
            raise InvalidRequestError(f"Invalid payload for {self.action_type}: {error}") from error


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
