from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_audit
from ..auth import AuthenticationError, decode_access_token
from ..db import get_session
from ..models import Membership, User
from ..permissions import Permission, permissions_for_role


@dataclass(frozen=True)
class RequestContext:
    """Verified request identity and tenant membership."""

    tenant_id: str
    actor_id: str
    role: str
    correlation_id: str
    permissions: frozenset[Permission]


async def get_request_context(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> RequestContext:
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID header is required",
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:].strip()
    try:
        actor_id = decode_access_token(token)
    except AuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    user = await session.scalar(
        select(User).where(User.id == actor_id, User.is_active.is_(True))
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenant_id = x_tenant_id.strip()
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == actor_id,
            Membership.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this tenant",
        )

    return RequestContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        role=membership.role,
        correlation_id=request.state.correlation_id,
        permissions=permissions_for_role(membership.role),
    )


def require_permission(permission: Permission):
    async def dependency(
        request: Request,
        session: Annotated[AsyncSession, Depends(get_session)],
        context: Annotated[RequestContext, Depends(get_request_context)],
    ) -> RequestContext:
        if permission not in context.permissions:
            await record_audit(
                session=session,
                context=context,
                action="authorization.denied",
                entity_type="permission",
                entity_id=permission.value,
                outcome="denied",
                reason="permission_denied",
                details={"method": request.method, "path": request.url.path},
            )
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )
        return context

    return dependency
