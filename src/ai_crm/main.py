import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .api.action_routes import router as action_router
from .api.admin_routes import router as admin_router
from .api.agent_eval_routes import router as agent_eval_router
from .api.agent_routes import router as agent_router
from .api.ai_routes import router as ai_router
from .api.integration_routes import router as integration_router
from .api.knowledge_routes import router as knowledge_router
from .api.observability_routes import router as observability_router
from .api.routes import router
from .api.work_routes import router as work_router
from .config import settings
from .db import SessionFactory, close_database, create_tables, seed_local_identity
from .domain import (
    CapabilityDisabledError,
    ConflictError,
    DomainError,
    InvalidRequestError,
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
    PreconditionRequiredError,
    SeparationOfDutiesError,
    VersionConflictError,
)
from .integrations import WebhookSignatureError
from .work.runner import run_forever


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.auto_create_tables:
        await create_tables()
    if settings.debug and settings.seed_demo_data:
        await seed_local_identity()
    stop_event = asyncio.Event()
    worker_task = None
    if settings.worker_enabled:
        worker_task = asyncio.create_task(run_forever(SessionFactory, stop_event))
    yield
    stop_event.set()
    if worker_task is not None:
        try:
            await asyncio.wait_for(worker_task, timeout=10)
        except TimeoutError:
            worker_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await worker_task
    await close_database()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend foundation for an AI-first CRM and business automation platform.",
    lifespan=lifespan,
)
app.include_router(router, prefix=settings.api_v1_prefix)
app.include_router(integration_router, prefix=settings.api_v1_prefix)
app.include_router(ai_router, prefix=settings.api_v1_prefix)
app.include_router(action_router, prefix=settings.api_v1_prefix)
app.include_router(knowledge_router, prefix=settings.api_v1_prefix)
app.include_router(work_router, prefix=settings.api_v1_prefix)
app.include_router(observability_router, prefix=settings.api_v1_prefix)
app.include_router(admin_router, prefix=settings.api_v1_prefix)
app.include_router(agent_router, prefix=settings.api_v1_prefix)
app.include_router(agent_eval_router, prefix=settings.api_v1_prefix)


_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


def parse_traceparent(value: str | None) -> str | None:
    """Return the W3C trace id, or None so a fresh trace starts (invalid headers are ignored)."""
    match = _TRACEPARENT.match(value.strip().lower()) if value else None
    if match is None or set(match.group(1)) == {"0"} or set(match.group(2)) == {"0"}:
        return None
    return match.group(1)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    supplied_id = request.headers.get("X-Correlation-ID")
    correlation_id = supplied_id or str(uuid4())
    try:
        UUID(correlation_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "X-Correlation-ID must be a valid UUID"},
        )

    request.state.correlation_id = correlation_id
    trace_id = parse_traceparent(request.headers.get("traceparent")) or uuid4().hex
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["traceparent"] = f"00-{trace_id}-{uuid4().hex[:16]}-01"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, _: SQLAlchemyError) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", None)
    response = JSONResponse(
        status_code=503,
        content={
            "detail": "Database operation failed",
            "correlation_id": correlation_id,
        },
    )
    if correlation_id:
        response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
    status_code = 422
    code = "domain_error"
    if isinstance(error, NotFoundError):
        status_code, code = 404, "not_found"
    elif isinstance(error, PreconditionRequiredError):
        status_code, code = 428, "precondition_required"
    elif isinstance(error, VersionConflictError):
        status_code, code = 409, "record_version_conflict"
    elif isinstance(error, ConflictError):
        status_code, code = 409, "conflict"
    elif isinstance(error, InvalidTransitionError):
        status_code, code = 409, "invalid_transition"
    elif isinstance(error, CapabilityDisabledError):
        status_code, code = 503, "capability_disabled"
    elif isinstance(error, PermissionDeniedError):
        status_code, code = 403, "permission_denied"
    elif isinstance(error, SeparationOfDutiesError):
        status_code, code = 403, "separation_of_duties"
    elif isinstance(error, InvalidRequestError):
        status_code, code = 422, "invalid_request"
    elif isinstance(error, WebhookSignatureError):
        status_code, code = 401, "invalid_webhook_signature"

    correlation_id = getattr(request.state, "correlation_id", None)
    response = JSONResponse(
        status_code=status_code,
        content={"code": code, "detail": str(error), "correlation_id": correlation_id},
    )
    if correlation_id:
        response.headers["X-Correlation-ID"] = correlation_id
    return response
