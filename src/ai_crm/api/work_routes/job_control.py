from typing import Annotated

from fastapi import Header

from ...schemas import (
    JobClaimRequest,
    JobCompleteRequest,
    JobFailureRequest,
    JobRead,
)
from ...work import (
    cancel_job,
    complete_job,
    fail_job,
    get_job,
    heartbeat_job,
    retry_job,
)
from .base import JobsManageContext, JobsReadContext, SessionDependency, router

__all__ = [
    "cancel_job_endpoint", "complete_job_endpoint", "fail_job_endpoint", "get_job_endpoint",
    "heartbeat_job_endpoint", "retry_job_endpoint",
]


@router.get("/jobs/{job_id}", response_model=JobRead, tags=["jobs"])
async def get_job_endpoint(
    job_id: str,
    session: SessionDependency,
    context: JobsReadContext,
) -> JobRead:
    return JobRead.model_validate(await get_job(session, context, job_id))


@router.post("/jobs/{job_id}/heartbeat", response_model=JobRead, tags=["jobs"])
async def heartbeat_job_endpoint(
    job_id: str,
    payload: JobClaimRequest,
    session: SessionDependency,
    context: JobsManageContext,
) -> JobRead:
    job = await heartbeat_job(
        session,
        context,
        job_id,
        payload.worker_id,
        payload.lease_seconds,
    )
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/complete", response_model=JobRead, tags=["jobs"])
async def complete_job_endpoint(
    job_id: str,
    payload: JobCompleteRequest,
    session: SessionDependency,
    context: JobsManageContext,
    worker_id: Annotated[str | None, Header(alias="X-Worker-ID")] = None,
) -> JobRead:
    job = await complete_job(session, context, job_id, worker_id or "", payload.result)
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/fail", response_model=JobRead, tags=["jobs"])
async def fail_job_endpoint(
    job_id: str,
    payload: JobFailureRequest,
    session: SessionDependency,
    context: JobsManageContext,
    worker_id: Annotated[str | None, Header(alias="X-Worker-ID")] = None,
) -> JobRead:
    job = await fail_job(session, context, job_id, worker_id or "", payload)
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/retry", response_model=JobRead, tags=["jobs"])
async def retry_job_endpoint(
    job_id: str,
    session: SessionDependency,
    context: JobsManageContext,
) -> JobRead:
    return JobRead.model_validate(await retry_job(session, context, job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobRead, tags=["jobs"])
async def cancel_job_endpoint(
    job_id: str,
    session: SessionDependency,
    context: JobsManageContext,
) -> JobRead:
    return JobRead.model_validate(await cancel_job(session, context, job_id))
