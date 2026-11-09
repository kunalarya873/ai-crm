from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from ...domain import InvalidRequestError
from .escalate import _Escalation

__all__ = [
    "_Outcome", "_budget_exhausted", "_denial", "_parse", "_reject",
]


@dataclass
class _Outcome:
    status: str = "completed"
    output: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    action_proposal_id: str | None = None
    child_run_id: str | None = None
    context_assembly_id: str | None = None
    side_effects: int = 0
    token_reserve: int = 0
    charge: bool = True
    escalation: _Escalation | None = None
    run_status: str | None = None
    terminal_reason: str | None = None
    reject: str | None = None


def _denial(code: str, summary: str) -> _Outcome:
    return _Outcome(
        status="escalated",
        error_code=code,
        output={"detail": summary},
        escalation=_Escalation(
            reason="policy_denial",
            summary=summary,
            evidence=[{"code": code}],
            next_steps=["Decide whether the agent's registered scope should change."],
        ),
    )


def _budget_exhausted(what: str) -> _Outcome:
    return _Outcome(
        status="escalated",
        error_code="budget_exhausted",
        output={"detail": f"{what} budget exhausted"},
        charge=False,
        escalation=_Escalation(
            reason="budget_exhausted",
            summary=f"The run exhausted its {what} budget.",
            next_steps=["Review the partial results and start a new run with a larger budget."],
            run_status="budget_exhausted",
        ),
    )


def _parse[T: BaseModel](model: type[T], raw: dict[str, Any], step_type: str) -> T:
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        raise InvalidRequestError(f"Invalid {step_type} input: {error}") from error


def _reject(code: str, detail: str) -> _Outcome:
    return _Outcome(status="rejected", error_code=code, reject=detail, output={"detail": detail})
