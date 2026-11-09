from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from ...config import settings

__all__ = [
    "Comparison", "MAX_SLO_WINDOW", "NO_REQUEST_TELEMETRY", "SloDefinition", "_slo", "_unmeasured",
    "slo_definitions",
]


MAX_SLO_WINDOW = timedelta(days=31)


Comparison = Literal["lte", "gte"]


@dataclass(frozen=True)
class SloDefinition:
    key: str
    description: str
    unit: str
    comparison: Comparison
    target: float
    measurable: bool = True
    reason: str | None = None


NO_REQUEST_TELEMETRY = (
    "The backend does not persist per-request telemetry, so this cannot be measured yet."
)


def _slo(
    key: str, description: str, unit: str, comparison: Comparison, target: float
) -> SloDefinition:
    return SloDefinition(key, description, unit, comparison, target)


def _unmeasured(
    key: str, description: str, unit: str, comparison: Comparison, target: float
) -> SloDefinition:
    return SloDefinition(key, description, unit, comparison, target, False, NO_REQUEST_TELEMETRY)


def slo_definitions() -> tuple[SloDefinition, ...]:
    return (
        _slo("queue_age_seconds", "Oldest ready job waiting in the queue", "seconds", "lte", 300),
        _slo("job_success_rate", "Finished jobs that succeeded", "ratio", "gte", 0.99),
        _slo(
            "sync_freshness_seconds",
            "Worst time since the last successful sync of a connected connection",
            "seconds",
            "lte",
            2.0 * settings.integration_sync_interval_seconds,
        ),
        _slo(
            "search_freshness_ratio",
            "Searchable sources past their fresh-until date",
            "ratio",
            "lte",
            0.2,
        ),
        _slo(
            "action_completion_rate",
            "Action executions that completed successfully",
            "ratio",
            "gte",
            0.95,
        ),
        _slo("ai_fallback_rate", "AI runs that fell back to a safe response", "ratio", "lte", 0.05),
        _slo("ai_avg_latency_ms", "Average AI response time", "milliseconds", "lte", 2000),
        _slo("agent_overdue_runs", "Agent runs past their deadline", "count", "lte", 0),
        _unmeasured("api_availability", "API availability", "ratio", "gte", 0.999),
        _unmeasured("api_latency_p95_ms", "API p95 latency", "milliseconds", "lte", 500),
        _unmeasured("api_error_rate", "API 5xx error rate", "ratio", "lte", 0.01),
    )
