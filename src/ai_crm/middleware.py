import asyncio
import logging
import re
import time
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import settings
from .models import utc_now
from .observability.requests import request_recorder

logger = logging.getLogger(__name__)
# Column limits: a value longer than these would make every later flush fail on PostgreSQL.
ROUTE_MAX_LENGTH = 200
HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


def parse_traceparent(value: str | None) -> str | None:
    """Return the W3C trace id, or None so a fresh trace starts (invalid headers are ignored)."""
    match = _TRACEPARENT.match(value.strip().lower()) if value else None
    if match is None or set(match.group(1)) == {"0"} or set(match.group(2)) == {"0"}:
        return None
    return match.group(1)


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
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except asyncio.CancelledError:
        _record(request, 499, started)  # client went away: slow requests must stay in the p95
        raise
    except Exception:
        _record(request, 500, started)
        raise
    _record(request, response.status_code, started)
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["traceparent"] = f"00-{trace_id}-{uuid4().hex[:16]}-01"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _record(request: Request, status_code: int, started: float) -> None:
    """Count the request for the API SLOs; never raises into the request path. Routes are
    recorded by template so ids stay out of labels; kill-switch 503s are an operator choice,
    not an outage, so they get their own class."""
    if not settings.request_metrics_enabled:
        return
    try:
        route = getattr(request.scope.get("route"), "path", None)
        exempt = getattr(request.state, "slo_exempt", False)
        request_recorder.record(
            now=utc_now(),
            tenant_id=getattr(request.state, "tenant_id", ""),
            route=(route or "unmatched")[:ROUTE_MAX_LENGTH],
            method=request.method if request.method in HTTP_METHODS else "OTHER",
            status_class="disabled" if exempt else f"{status_code // 100}xx",
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    except Exception:  # telemetry must not break a request
        logger.exception("could not record request metrics")
