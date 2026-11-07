from enum import StrEnum


class DomainError(ValueError):
    """Base class for expected application-level domain errors."""


class NotFoundError(DomainError):
    pass


class PreconditionRequiredError(DomainError):
    pass


class VersionConflictError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class InvalidRequestError(DomainError):
    pass


class InvalidTransitionError(DomainError):
    pass


class SeparationOfDutiesError(DomainError):
    pass


class PermissionDeniedError(DomainError):
    pass


class CapabilityDisabledError(DomainError):
    pass


class ContactStatus(StrEnum):
    LEAD = "lead"
    QUALIFIED = "qualified"
    CUSTOMER = "customer"
    LOST = "lost"


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OpportunityStage(StrEnum):
    QUALIFICATION = "qualification"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class OpportunityStatus(StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


ALLOWED_CONTACT_TRANSITIONS: dict[str, frozenset[str]] = {
    ContactStatus.LEAD: frozenset({ContactStatus.QUALIFIED, ContactStatus.LOST}),
    ContactStatus.QUALIFIED: frozenset({ContactStatus.CUSTOMER, ContactStatus.LOST}),
    ContactStatus.CUSTOMER: frozenset({ContactStatus.LOST}),
    ContactStatus.LOST: frozenset(),
}
ALLOWED_TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    TaskStatus.OPEN: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.CANCELLED}
    ),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.COMPLETED, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}
ALLOWED_OPPORTUNITY_STAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    OpportunityStage.QUALIFICATION: frozenset(
        {OpportunityStage.PROPOSAL, OpportunityStage.CLOSED_LOST}
    ),
    OpportunityStage.PROPOSAL: frozenset(
        {OpportunityStage.NEGOTIATION, OpportunityStage.CLOSED_LOST}
    ),
    OpportunityStage.NEGOTIATION: frozenset(
        {OpportunityStage.CLOSED_WON, OpportunityStage.CLOSED_LOST}
    ),
    OpportunityStage.CLOSED_WON: frozenset(),
    OpportunityStage.CLOSED_LOST: frozenset(),
}


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def validate_transition(
    current: str,
    requested: str,
    allowed: dict[str, frozenset[str]],
) -> None:
    if current == requested:
        return
    if requested not in allowed.get(current, frozenset()):
        raise InvalidTransitionError(f"Cannot transition from {current} to {requested}")
