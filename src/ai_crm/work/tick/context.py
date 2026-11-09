from datetime import UTC, datetime
from uuid import uuid4

from ...api.deps import RequestContext
from ...permissions import Permission

ACTOR_ID = "system:worker"
WORKER_ID = f"worker-{uuid4().hex[:12]}"
QUEUE = "default"
LEASE_GRACE_SECONDS = 30
CONNECTOR_JOB_TYPES = frozenset({"integration.sync", "integration.webhook"})
CONTROL = frozenset({Permission.JOBS_MANAGE})


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def make_context(
    tenant_id: str, permissions: frozenset[Permission], trace_id: str | None = None
) -> RequestContext:
    return RequestContext(
        tenant_id=tenant_id,
        actor_id=ACTOR_ID,
        role="system",
        correlation_id=str(uuid4()),
        permissions=permissions,
        trace_id=trace_id,
    )
