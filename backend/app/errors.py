"""One error envelope for every error (C-001, PATTERN-006).

`{"error": {"code": "...", "message": "...", "fields": [{"field", "message"}]}}`,
with `fields` only for validation errors. The submitted input is never sent back
(an unknown field is reported under its location, e.g. `body`, not its name):
validation errors keep pydantic's `msg` and drop its `input` and `ctx`.
"""

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

# A1: the code for an HTTPException raised without one (Starlette's 404 and 405 too).
_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    429: "rate_limited",
}


class ApiError(HTTPException):
    """An HTTPException with an envelope code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(status_code, message, dict(headers) if headers else None)
        self.code = code


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    fields: list[dict[str, str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if fields is not None:
        error["fields"] = fields
    return JSONResponse(
        {"error": error}, status_code=status_code, headers=dict(headers or {})
    )


def _field(error: Mapping[str, Any]) -> str:
    if error.get("type") == "json_invalid":
        return "body"  # the location is a character offset, not a field
    loc = [str(part) for part in error.get("loc", ())]
    if error.get("type") == "extra_forbidden":
        # The unknown field's name is client input: name only where it was sent.
        return loc[0] if loc else "body"
    if loc and loc[0] == "body" and len(loc) > 1:
        loc = loc[1:]
    return ".".join(loc)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields = [{"field": _field(e), "message": str(e["msg"])} for e in exc.errors()]
    return error_response(422, "validation_error", "Invalid input.", fields=fields)


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    if isinstance(exc, ApiError):
        code = exc.code
    else:
        code = _CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else code
    return error_response(exc.status_code, code, message, headers=exc.headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
