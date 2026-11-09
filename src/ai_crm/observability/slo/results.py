from typing import Literal

from ...config import settings
from ...schemas import SloRead
from .definitions import SloDefinition

__all__ = [
    "_result", "_status",
]


def _status(
    definition: SloDefinition, value: float | None
) -> Literal["met", "breached", "no_data"]:
    if value is None:
        return "no_data"
    if definition.comparison == "lte":
        return "met" if value <= definition.target else "breached"
    return "met" if value >= definition.target else "breached"


def _result(
    definition: SloDefinition, value: float | None, detail: dict[str, object] | None = None
) -> SloRead:
    if not definition.measurable:
        status: Literal["met", "breached", "no_data", "not_measured"] = "not_measured"
        value = None
    else:
        status = _status(definition, value)
    return SloRead(
        key=definition.key,
        description=definition.description,
        unit=definition.unit,
        comparison=definition.comparison,
        target=definition.target,
        owner=settings.slo_owner,
        status=status,
        value=value,
        detail=detail or {},
        reason=definition.reason,
    )
