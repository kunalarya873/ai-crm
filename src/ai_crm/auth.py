from datetime import UTC, datetime, timedelta

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from .config import settings


class AuthenticationError(ValueError):
    """Raised when a bearer token cannot be trusted."""


def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(UTC)
    expires_at = now + (expires_delta or timedelta(minutes=settings.auth_token_ttl_minutes))
    payload = {
        "sub": user_id,
        "iss": settings.auth_issuer,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.auth_secret_key,
            algorithms=["HS256"],
            issuer=settings.auth_issuer,
            options={"require": ["sub", "iss", "iat", "exp"]},
        )
    except ExpiredSignatureError as error:
        raise AuthenticationError("token expired") from error
    except InvalidTokenError as error:
        raise AuthenticationError("invalid token") from error

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id.strip():
        raise AuthenticationError("token subject is invalid")
    return user_id
