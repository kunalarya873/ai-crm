from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ...domain import InvalidRequestError
from ...permissions import Permission
from ...schemas import ContactUpdate

__all__ = [
    "ActionDefinition", "ApprovalRequestAction", "ContactAssignOwnerAction", "ContactUpdateAction",
    "ExternalActivityAction",
]


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
