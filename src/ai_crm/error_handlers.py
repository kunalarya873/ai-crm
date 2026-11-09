from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .domain import (
    BackpressureError,
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

BACKPRESSURE_RETRY_AFTER_SECONDS = 30


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
        request.state.slo_exempt = True
    elif isinstance(error, BackpressureError):
        status_code, code = 429, "backpressure"
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
    if isinstance(error, BackpressureError):
        response.headers["Retry-After"] = str(BACKPRESSURE_RETRY_AFTER_SECONDS)
    if correlation_id:
        response.headers["X-Correlation-ID"] = correlation_id
    return response
