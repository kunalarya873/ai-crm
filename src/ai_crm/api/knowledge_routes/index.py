from fastapi import Query, status

from ...knowledge import (
    list_index_jobs,
    queue_index_job,
    run_index_job,
)
from ...schemas import KnowledgeIndexJobRead
from .base import ManageContext, SessionDependency, router

__all__ = [
    "list_index_jobs_endpoint", "queue_index_endpoint", "run_index_job_endpoint",
]


@router.post(
    "/knowledge/sources/{source_id}/index",
    response_model=KnowledgeIndexJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["knowledge"],
)
async def queue_index_endpoint(
    source_id: str,
    session: SessionDependency,
    context: ManageContext,
) -> KnowledgeIndexJobRead:
    job = await queue_index_job(session, context, source_id)
    return KnowledgeIndexJobRead.model_validate(job)


@router.get(
    "/knowledge/index-jobs",
    response_model=list[KnowledgeIndexJobRead],
    tags=["knowledge"],
)
async def list_index_jobs_endpoint(
    session: SessionDependency,
    context: ManageContext,
    job_status: str | None = Query(default=None, alias="status"),
) -> list[KnowledgeIndexJobRead]:
    jobs = await list_index_jobs(session, context, status=job_status)
    return [KnowledgeIndexJobRead.model_validate(job) for job in jobs]


@router.post(
    "/knowledge/index-jobs/{job_id}/run",
    response_model=KnowledgeIndexJobRead,
    tags=["knowledge"],
)
async def run_index_job_endpoint(
    job_id: str,
    session: SessionDependency,
    context: ManageContext,
) -> KnowledgeIndexJobRead:
    job = await run_index_job(session, context, job_id)
    return KnowledgeIndexJobRead.model_validate(job)
