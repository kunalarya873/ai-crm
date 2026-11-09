from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...models import ActionExecution, DurableJob, IntegrationConnection

__all__ = ["failed_action_rules", "failed_job_rules", "reauth_connection_rules"]


async def reauth_connection_rules(
    session: AsyncSession, context: RequestContext, now: Any
) -> list[dict[str, Any]]:
    reauth_connections = list(
        await session.scalars(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == context.tenant_id,
                IntegrationConnection.status == "needs_reauth",
            )
        )
    )
    return [
        dict(
            rule_key="connection_needs_reauth",
            alert_type="system",
            severity="warning",
            title=f"Integration needs re-authorisation: {connection.external_account_id}",
            description="Token refresh failed permanently; syncs and writes are paused.",
            related_type="integration_connection",
            related_id=connection.id,
            evidence=[{"field": "last_error_code", "value": connection.last_error_code}],
        )
        for connection in reauth_connections
    ]


async def failed_job_rules(
    session: AsyncSession, context: RequestContext, now: Any
) -> list[dict[str, Any]]:
    failed_jobs = list(
        await session.scalars(
            select(DurableJob).where(
                DurableJob.tenant_id == context.tenant_id,
                DurableJob.status.in_({"failed", "dead_letter"}),
            )
        )
    )
    return [
        dict(
            rule_key="failed_job",
            alert_type="system",
            severity="high",
            title=f"Failed job: {job.job_type}",
            description=job.error_detail or "A durable job requires operator review.",
            related_type="durable_job",
            related_id=job.id,
            evidence=[{"field": "error_code", "value": job.error_code}],
        )
        for job in failed_jobs
    ]


async def failed_action_rules(
    session: AsyncSession, context: RequestContext, now: Any
) -> list[dict[str, Any]]:
    failed_actions = list(
        await session.scalars(
            select(ActionExecution).where(
                ActionExecution.tenant_id == context.tenant_id,
                ActionExecution.status.in_({"failed", "recoverable", "uncertain"}),
            )
        )
    )
    return [
        dict(
            rule_key="failed_action",
            alert_type="system",
            severity="high",
            title=f"Action requires review: {execution.action_type}",
            description=execution.error_detail or "An action execution requires operator review.",
            related_type="action_execution",
            related_id=execution.id,
            evidence=[
                {"field": "status", "value": execution.status},
                {"field": "error_code", "value": execution.error_code},
            ],
        )
        for execution in failed_actions
    ]
