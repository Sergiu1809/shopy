"""Who is calling and what they may do (C-001, PATTERN-007, Q2, Q9).

The access token carries only the user ID; the user, and so the role, is loaded
from the DB on every request.
"""

from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import decode_access_token
from app.db import get_session
from app.errors import ApiError
from app.models import User


def _unauthorized() -> ApiError:
    return ApiError(
        401,
        "unauthorized",
        "Not authenticated.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request, db: Annotated[AsyncSession, Depends(get_session)]
) -> User:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    try:
        user_id = decode_access_token(token.strip())
    except jwt.InvalidTokenError:
        raise _unauthorized() from None
    user = await db.get(User, user_id)
    if user is None:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise ApiError(403, "forbidden", "Admin access required.")
    return user
