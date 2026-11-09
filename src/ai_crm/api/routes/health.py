from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from ...config import settings
from ...db import check_database
from ...schemas import (
    HealthResponse,
)
from .base import router

__all__ = [
    "health", "readiness",
]


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, version=settings.app_version)


@router.get("/readiness", tags=["system"])
async def readiness() -> dict[str, str]:
    try:
        await check_database()
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready",
        ) from error
    return {"status": "ready", "database": "ok"}
