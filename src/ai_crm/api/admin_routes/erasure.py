from typing import Annotated

from fastapi import Depends, Path

from ...api.deps import RequestContext, require_permission
from ...lifecycle import erase_record
from ...permissions import Permission
from ...schemas import ErasureRead, ErasureRequest
from .base import SessionDependency, router

__all__ = ["ErasureContext", "erase_record_endpoint"]

ErasureContext = Annotated[RequestContext, Depends(require_permission(Permission.ADMIN_ERASURE))]


@router.post("/admin/erasure/{resource}/{record_id}", response_model=ErasureRead, tags=["admin"])
async def erase_record_endpoint(
    resource: Annotated[str, Path(max_length=30)],
    record_id: Annotated[str, Path(max_length=36)],
    payload: ErasureRequest,
    session: SessionDependency,
    context: ErasureContext,
) -> ErasureRead:
    return ErasureRead.model_validate(
        await erase_record(session, context, resource, record_id, payload)
    )
