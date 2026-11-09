from typing import Annotated

from fastapi import Header, Query, status

from ...schemas import (
    JobClaimRequest,
    JobCreate,
    JobRead,
)
from ...work import (
    claim_next_job,
    create_job,
    list_jobs,
    reconcile_expired_jobs,
)
from .base import JobsManageContext, JobsReadContext, SessionDependency, router

__all__ = [
    "claim_next_job_endpoint", "create_job_endpoint", "list_jobs_endpoint",
    "reconcile_expired_jobs_endpoint",
]


@router.post(
    "/jobs",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    tags=["jobs"],
)
async def create_job_endpoint(
    payload: JobCreate,
    session: SessionDependency,
    context: JobsManageContext,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobRead:
    job = await create_job(session, context, payload, idempotency_key or "")
    return JobRead.model_validate(job)


@router.get("/jobs", response_model=list[JobRead], tags=["jobs"])
async def list_jobs_endpoint(
    session: SessionDependency,
    context: JobsReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    queue: str | None = None,
    job_status: str | None = Query(default=None, alias="status"),
) -> list[JobRead]:
    jobs = await list_jobs(
        session,
        context,
        limit=limit,
        offset=offset,
        queue=queue,
        job_status=job_status,
    )
    return [JobRead.model_validate(job) for job in jobs]


@router.post("/jobs/reconcile-expired", response_model=list[JobRead], tags=["jobs"])
async def reconcile_expired_jobs_endpoint(
    session: SessionDependency,
    context: JobsManageContext,
) -> list[JobRead]:
    jobs = await reconcile_expired_jobs(session, context)
    return [JobRead.model_validate(job) for job in jobs]


@router.post("/jobs/claim-next", response_model=JobRead | None, tags=["jobs"])
async def claim_next_job_endpoint(
    payload: JobClaimRequest,
    session: SessionDependency,
    context: JobsManageContext,
    queue: str = "default",
) -> JobRead | None:
    job = await claim_next_job(
        session,
        context,
        queue=queue,
        worker_id=payload.worker_id,
        lease_seconds=payload.lease_seconds,
    )
    return JobRead.model_validate(job) if job else None
