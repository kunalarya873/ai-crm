from ..domain import InvalidTransitionError

CAPABILITIES = frozenset({"read", "propose", "delegate", "escalate"})
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
AGENT_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "active": frozenset({"suspended", "retired"}),
    "suspended": frozenset({"active", "retired"}),
    "retired": frozenset(),
}
RUN_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "running": frozenset(
        {"paused", "waiting_human", "completed", "failed", "cancelled", "budget_exhausted"}
    ),
    "paused": frozenset({"running", "failed", "cancelled"}),
    "waiting_human": frozenset({"running", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "budget_exhausted": frozenset(),
}
TERMINAL_RUN_STATUSES = frozenset(
    status for status, targets in RUN_STATUS_TRANSITIONS.items() if not targets
)
ACTIVE_RUN_STATUSES = frozenset(RUN_STATUS_TRANSITIONS) - TERMINAL_RUN_STATUSES
FAILED_RUN_STATUSES = frozenset({"failed", "budget_exhausted"})
OPEN_PROPOSAL_STATUSES = frozenset({"proposed", "edited", "approved"})


def validate_run_transition(current: str, requested: str) -> None:
    if requested not in RUN_STATUS_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransitionError(f"Cannot transition agent run from {current} to {requested}")


def validate_agent_transition(current: str, requested: str) -> None:
    if requested != current and requested not in AGENT_STATUS_TRANSITIONS.get(
        current, frozenset()
    ):
        raise InvalidTransitionError(f"Cannot transition agent from {current} to {requested}")
