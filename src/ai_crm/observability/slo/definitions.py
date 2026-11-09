from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from ...config import settings

__all__ = [
    "Comparison", "MAX_SLO_WINDOW", "SloDefinition", "_slo", "slo_definitions",
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


def _slo(
    key: str, description: str, unit: str, comparison: Comparison, target: float
) -> SloDefinition:
    return SloDefinition(key, description, unit, comparison, target)


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
        _slo(
            "api_availability",
            "Requests not answered with a 5xx (kill-switch 503s excluded)",
            "ratio",
            "gte",
            0.999,
        ),
        _slo(
            "api_latency_p95_ms",
            "API p95 latency, as the upper bound of its histogram bucket",
            "milliseconds",
            "lte",
            500,
        ),
        _slo("api_error_rate", "API 5xx error rate (4xx are not errors)", "ratio", "lte", 0.01),
    )
