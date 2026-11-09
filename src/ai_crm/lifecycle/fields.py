from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..models import Activity, Company, Contact, Opportunity, Task

__all__ = ["ERASED", "ERASABLE", "Erasable"]

ERASED = "[erased]"

Value = Any | Callable[[Any], Any]


@dataclass(frozen=True)
class Erasable:
    """Which columns are overwritten when a record is erased, and how it is retired."""

    model: Any
    fields: dict[str, Value] = field(default_factory=dict)


ERASABLE: dict[str, Erasable] = {
    "contacts": Erasable(
        Contact,
        {"first_name": ERASED, "last_name": ERASED, "email": None, "company_name": None},
    ),
    # The name is unique per tenant, so the replacement is derived from the id.
    "companies": Erasable(
        Company, {"name": ERASED, "normalized_name": lambda row: f"erased:{row.id}"}
    ),
    "opportunities": Erasable(
        Opportunity, {"name": ERASED, "next_step": None, "win_loss_reason": None}
    ),
    "activities": Erasable(Activity, {"subject": ERASED, "body": None}),
    "tasks": Erasable(Task, {"title": ERASED, "description": None, "completion_evidence": None}),
}
