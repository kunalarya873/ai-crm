import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
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
    DomainError,
)
from .error_handlers import database_error_handler, domain_error_handler
from .middleware import correlation_id_middleware, parse_traceparent  # noqa: F401
from .observability.requests import request_metrics_loop
from .work.runner import run_forever


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.auto_create_tables:
        await create_tables()
    if settings.debug and settings.seed_demo_data:
        await seed_local_identity()
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []
    if settings.worker_enabled:
        tasks.append(asyncio.create_task(run_forever(SessionFactory, stop_event)))
    if settings.request_metrics_enabled:
        tasks.append(asyncio.create_task(request_metrics_loop(SessionFactory, stop_event)))
    yield
    stop_event.set()
    for task in tasks:
        try:
            await asyncio.wait_for(task, timeout=10)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
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


app.middleware("http")(correlation_id_middleware)
app.exception_handler(SQLAlchemyError)(database_error_handler)
app.exception_handler(DomainError)(domain_error_handler)
