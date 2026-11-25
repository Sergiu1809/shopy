"""Access and refresh tokens (C-001, Q5, Q7, Q9, Q10, Q12).

Access: JWT HS256, 15 min, claims sub/iat/exp/type, no role (the role is read from
the DB on every request). Refresh: an opaque random token in an httpOnly cookie; the
DB keeps only its SHA-256 hex.
"""

import hashlib
import os
import secrets
import time
from datetime import UTC, datetime, timedelta

import jwt
from starlette.responses import Response

ACCESS_TTL_S = 15 * 60
REFRESH_TTL = timedelta(days=30)  # sliding: every rotation starts a new 30 days
REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"
_ALGORITHM = "HS256"
_MIN_SECRET_BYTES = 32


def jwt_secret() -> str:
    """JWT_SECRET from the env; at least 32 bytes in UTF-8, or the api won't start."""
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set")
    if len(secret.encode()) < _MIN_SECRET_BYTES:
        raise RuntimeError(f"JWT_SECRET must be at least {_MIN_SECRET_BYTES} bytes")
    return secret


def create_access_token(user_id: int) -> str:
    now = int(time.time())
    claims = {"sub": str(user_id), "iat": now, "exp": now + ACCESS_TTL_S}
    return jwt.encode({**claims, "type": "access"}, jwt_secret(), _ALGORITHM)


def decode_access_token(token: str) -> int:
    """The user ID of a valid access token; `jwt.InvalidTokenError` otherwise."""
    claims = jwt.decode(
        token,
        jwt_secret(),
        algorithms=[_ALGORITHM],
        options={"require": ["sub", "iat", "exp", "type"]},
    )
    sub = claims["sub"]
    if claims["type"] != "access" or not isinstance(sub, str) or not sub.isdigit():
        raise jwt.InvalidTokenError("not an access token")
    return int(sub)


def new_refresh_token() -> tuple[str, str]:
    """(raw token for the cookie, SHA-256 hex for the DB)."""
    raw = secrets.token_urlsafe(32)
    return raw, refresh_token_hash(raw)


def refresh_token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.now(UTC) + REFRESH_TTL


def set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=int(REFRESH_TTL.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )
