from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...ai.use_cases import AIUseCaseService
from ...api.deps import RequestContext, require_permission
from ...db import get_session
from ...permissions import Permission

__all__ = [
    "AIFeedbackContext", "AIReadContext", "AIUseContext", "SessionDependency", "_key",
    "current_service", "router",
]


router = APIRouter()


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


AIUseContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.AI_USE)),
]


AIReadContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.AI_READ)),
]


AIFeedbackContext = Annotated[
    RequestContext,
    Depends(require_permission(Permission.AI_FEEDBACK)),
]


def current_service() -> AIUseCaseService:
    # Resolved per call so a replacement assigned to ai_routes.service takes effect.
    from .. import ai_routes

    return ai_routes.service


def _key(value: str | None, context: RequestContext, use_case: str) -> str:
    cleaned = value.strip() if value else ""
    return cleaned or f"request:{context.correlation_id}:{use_case}"
