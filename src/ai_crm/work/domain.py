from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..domain import InvalidRequestError, InvalidTransitionError

WORK_ITEM_TYPES = frozenset(
    {"task", "commitment", "handoff", "approval", "reminder", "escalation"}
)
WORK_ITEM_STATUSES = frozenset({"open", "in_progress", "blocked", "completed", "cancelled"})
WORK_ITEM_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"in_progress", "blocked", "cancelled"}),
    "in_progress": frozenset({"open", "blocked", "completed", "cancelled"}),
    "blocked": frozenset({"open", "in_progress", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}
JOB_TYPES = frozenset(
    {
        "reminder.dispatch",
        "workflow.step",
        "integration.sync",
        "integration.webhook",
        "knowledge.index",
        "notification.send",
    }
)
JOB_STATUSES = frozenset(
    {"queued", "running", "retryable", "succeeded", "failed", "dead_letter", "cancelled"}
)
WORKFLOW_DEFINITIONS: dict[str, tuple[str, ...]] = {
    "customer_follow_up": (
        "review_context",
        "create_commitment",
        "await_approval",
        "complete",
    ),
}


def validate_work_item_type(item_type: str) -> None:
    if item_type not in WORK_ITEM_TYPES:
        raise InvalidRequestError(f"Unsupported work item type: {item_type}")


def validate_work_item_status(status: str) -> None:
    if status not in WORK_ITEM_STATUSES:
        raise InvalidRequestError(f"Unsupported work item status: {status}")


def validate_work_item_transition(current: str, requested: str) -> None:
    validate_work_item_status(requested)
    if requested != current and requested not in WORK_ITEM_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransitionError(f"Cannot transition work item from {current} to {requested}")


def validate_timezone(value: str) -> str:
    cleaned = value.strip()
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError as error:
        raise InvalidRequestError(f"Unknown timezone: {cleaned}") from error
    return cleaned


def require_aware_datetime(value: datetime | None, field_name: str) -> None:
    if value is not None and value.tzinfo is None:
        raise InvalidRequestError(f"{field_name} must include a timezone")


def workflow_steps(workflow_key: str) -> tuple[str, ...]:
    steps = WORKFLOW_DEFINITIONS.get(workflow_key)
    if steps is None:
        raise InvalidRequestError(f"Unsupported workflow: {workflow_key}")
    return steps
