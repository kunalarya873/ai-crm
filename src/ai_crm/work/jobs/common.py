import hashlib
import json
from datetime import UTC, datetime

from ...domain import ConflictError, InvalidRequestError
from ...models import DurableJob, utc_now
from ..domain import JOB_TYPES

__all__ = [
    "_aware", "_ensure_worker", "_hash_request", "_validate_job_request",
]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _hash_request(
    *,
    job_type: str,
    queue: str,
    priority: int,
    payload: dict[str, object],
    run_at: datetime,
    max_attempts: int,
    backoff_seconds: int,
    timeout_seconds: int,
) -> str:
    value = {
        "job_type": job_type,
        "queue": queue,
        "priority": priority,
        "payload": payload,
        "run_at": run_at.isoformat(),
        "max_attempts": max_attempts,
        "backoff_seconds": backoff_seconds,
        "timeout_seconds": timeout_seconds,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _validate_job_request(job_type: str, run_at: datetime) -> None:
    if job_type not in JOB_TYPES:
        raise InvalidRequestError(f"Unsupported job type: {job_type}")
    if run_at.tzinfo is None:
        raise InvalidRequestError("run_at must include a timezone")


def _ensure_worker(job: DurableJob, worker_id: str) -> None:
    if job.status != "running":
        raise ConflictError(f"Job is not running: {job.status}")
    if job.lease_owner != worker_id:
        raise ConflictError("Job is leased by another worker")
    lease_expires_at = _aware(job.lease_expires_at)
    if lease_expires_at is not None and lease_expires_at <= utc_now():
        raise ConflictError("Job lease has expired")
