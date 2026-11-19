"""`/admin`: every route on this router needs an admin (PATTERN-007, Q2).

The dependency sits at router level, so a route added here can't forget it. The
admin routes themselves arrive with GH-6.
"""

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_admin

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)
