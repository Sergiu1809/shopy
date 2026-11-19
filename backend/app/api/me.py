"""`GET /me`: the caller's own account (Q14); never the password hash or Stripe ID."""

from fastapi import APIRouter

from app.auth.dependencies import CurrentUser
from app.schemas.auth import MeOut

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(user: CurrentUser) -> MeOut:
    return MeOut(
        id=user.id, email=user.email, role=user.role, created_at=user.created_at
    )
