import re
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

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
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["traceparent"] = f"00-{trace_id}-{uuid4().hex[:16]}-01"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
