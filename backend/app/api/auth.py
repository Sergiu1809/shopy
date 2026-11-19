"""`/auth`: register, login, refresh, logout (C-001; GH-4 gate A Q3–Q13).

Register and login answer with the access token body and set the refresh cookie.
Refresh rotates the cookie on every use; a revoked token presented again logs the
user out everywhere. Logout needs only the cookie and always answers 204.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from app.auth import rate_limit
from app.auth.passwords import (
    hash_password,
    needs_rehash,
    verify_dummy,
    verify_password,
)
from app.auth.rate_limit import limit_by_ip
from app.auth.tokens import (
    ACCESS_TTL_S,
    REFRESH_COOKIE,
    clear_refresh_cookie,
    create_access_token,
    new_refresh_token,
    refresh_expiry,
    refresh_token_hash,
    set_refresh_cookie,
)
from app.db import get_session
from app.errors import ApiError, error_response
from app.models import RefreshToken, User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


async def _sign_in(db: AsyncSession, user_id: int, response: Response) -> TokenOut:
    """Store a new refresh token, commit, set the cookie, return the token body."""
    raw, token_hash = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id, token_hash=token_hash, expires_at=refresh_expiry()
        )
    )
    await db.commit()
    set_refresh_cookie(response, raw)
    return TokenOut(access_token=create_access_token(user_id), expires_in=ACCESS_TTL_S)


def _unauthorized_refresh() -> JSONResponse:
    response = error_response(401, "unauthorized", "Invalid or expired refresh token.")
    clear_refresh_cookie(response)
    return response


@router.post(
    "/register",
    status_code=201,
    dependencies=[Depends(limit_by_ip(rate_limit.REGISTER_IP))],
)
async def register(body: RegisterIn, response: Response, db: Session) -> TokenOut:
    password_hash = await run_in_threadpool(hash_password, body.password)
    user = User(email=body.email, password_hash=password_hash, role="customer")
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_users_email_lower" not in str(exc.orig):
            raise
        raise ApiError(
            409, "email_taken", "This email is already registered."
        ) from None
    return await _sign_in(db, user.id, response)


@router.post("/login", dependencies=[Depends(limit_by_ip(rate_limit.LOGIN_IP))])
async def login(body: LoginIn, response: Response, db: Session) -> TokenOut:
    # A4: failures per submitted email, known or not; a success does not reset them.
    rate_limit.LOGIN_ACCOUNT_FAILURES.check(body.email)
    user = await db.scalar(select(User).where(func.lower(User.email) == body.email))
    if user is None:
        await run_in_threadpool(verify_dummy, body.password)
        valid = False
    else:
        valid = await run_in_threadpool(
            verify_password, body.password, user.password_hash
        )
    if user is None or not valid:
        rate_limit.LOGIN_ACCOUNT_FAILURES.hit(body.email)
        raise ApiError(401, "invalid_credentials", "Invalid email or password.")
    if needs_rehash(user.password_hash):
        user.password_hash = await run_in_threadpool(hash_password, body.password)
    return await _sign_in(db, user.id, response)


@router.post(
    "/refresh",
    response_model=TokenOut,
    dependencies=[Depends(limit_by_ip(rate_limit.REFRESH_IP))],
)
async def refresh(
    response: Response, db: Session, raw: RefreshCookie = None
) -> TokenOut | JSONResponse:
    if not raw:
        return _unauthorized_refresh()
    token = await db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == refresh_token_hash(raw))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if token is None:
        return _unauthorized_refresh()
    if token.revoked_at is not None:
        # Q3: reuse of a rotated or logged-out token logs out every device.
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == token.user_id)
            .where(RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.commit()
        return _unauthorized_refresh()
    if token.expires_at <= now:
        return _unauthorized_refresh()
    token.revoked_at = now
    return await _sign_in(db, token.user_id, response)


@router.post(
    "/logout",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(limit_by_ip(rate_limit.LOGOUT_IP))],
)
async def logout(db: Session, raw: RefreshCookie = None) -> Response:
    """Revoke this cookie's token if it is active; no reuse check here (A8)."""
    if raw:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == refresh_token_hash(raw))
            .where(RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
    response = Response(status_code=204)
    clear_refresh_cookie(response)
    return response
