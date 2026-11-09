import os
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from ...config import settings

__all__ = [
    "LATENCY_BOUNDS_MS", "OVERFLOW_ROUTE", "PROCESS_ID", "Bucket", "BucketKey", "RequestRecorder",
    "request_recorder",
]

LATENCY_BOUNDS_MS = (25, 50, 100, 250, 500, 1000, 2500, 5000)
OVERFLOW_ROUTE = "other"
PROCESS_ID = f"{os.getpid()}-{uuid4().hex[:8]}"

BucketKey = tuple[datetime, str, str, str, str]  # minute, tenant, route, method, status class


@dataclass
class Bucket:
    count: int = 0
    latency_sum_ms: float = 0.0
    latency_counts: list[int] = field(default_factory=lambda: [0] * (len(LATENCY_BOUNDS_MS) + 1))

    def add(self, other: "Bucket") -> None:
        self.count += other.count
        self.latency_sum_ms += other.latency_sum_ms
        self.latency_counts = [a + b for a, b in zip(self.latency_counts, other.latency_counts)]


class RequestRecorder:
    """In-memory per-minute request aggregation; a background task flushes it to the database,
    so a request never waits on a write. Distinct keys are capped so labels cannot grow memory."""

    def __init__(self, max_keys: int) -> None:
        self.max_keys = max_keys
        self.dropped = 0
        self._buckets: dict[BucketKey, Bucket] = {}

    def record(
        self,
        *,
        now: datetime,
        tenant_id: str,
        route: str,
        method: str,
        status_class: str,
        latency_ms: float,
    ) -> None:
        minute = now.replace(second=0, microsecond=0)
        key = (minute, tenant_id, route, method, status_class)
        if key not in self._buckets and len(self._buckets) >= self.max_keys:
            key = (minute, tenant_id, OVERFLOW_ROUTE, "-", status_class)
            if key not in self._buckets and len(self._buckets) >= self.max_keys * 2:
                self.dropped += 1
                return
        bucket = self._buckets.setdefault(key, Bucket())
        bucket.count += 1
        bucket.latency_sum_ms += latency_ms
        index = next((i for i, bound in enumerate(LATENCY_BOUNDS_MS) if latency_ms <= bound), None)
        bucket.latency_counts[len(LATENCY_BOUNDS_MS) if index is None else index] += 1

    def drain(self) -> dict[BucketKey, Bucket]:
        drained, self._buckets = self._buckets, {}
        return drained

    def restore(self, drained: dict[BucketKey, Bucket]) -> None:
        """Merge buckets back after a failed flush, so counts are retried rather than lost."""
        for key, bucket in drained.items():
            if key in self._buckets or len(self._buckets) < self.max_keys * 2:
                self._buckets.setdefault(key, Bucket()).add(bucket)
            else:
                self.dropped += bucket.count


request_recorder = RequestRecorder(settings.request_metrics_max_keys)
