"""Request and response bodies of the auth routes and `GET /me` (PATTERN-006, Q8, Q14).

Unknown fields are rejected (`extra="forbid"`), so a `role` can never be submitted.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PlainValidator,
    TypeAdapter,
    ValidationError,
)
from pydantic_core import PydanticCustomError

INVALID_EMAIL = "Invalid email address."  # A6: one fixed message, no input echoed
_MAX_EMAIL_LENGTH = 254
_ASCII_DIGITS = frozenset("0123456789")
_email_str = TypeAdapter(EmailStr)


def _email(value: object) -> str:
    """Trimmed, lowercased (matches `uq_users_email_lower`), at most 254 characters."""
    if not isinstance(value, str):
        raise PydanticCustomError("email", INVALID_EMAIL)
    email = value.strip().lower()
    if len(email) > _MAX_EMAIL_LENGTH:
        raise PydanticCustomError("email", INVALID_EMAIL)
    try:
        return _email_str.validate_python(email)
    except ValidationError:
        raise PydanticCustomError("email", INVALID_EMAIL) from None


def _password_rule(value: str) -> str:
    """A7: at least one uppercase letter (any script) and one ASCII digit."""
    if not any(c.isupper() for c in value) or not any(
        c in _ASCII_DIGITS for c in value
    ):
        raise PydanticCustomError(
            "password",
            "Password must contain at least one uppercase letter and one digit.",
        )
    return value


Email = Annotated[str, PlainValidator(_email, json_schema_input_type=str)]
Password = Annotated[
    str, Field(min_length=8, max_length=128), AfterValidator(_password_rule)
]


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: Password


class LoginIn(BaseModel):
    """A6: no composition rule, so an older password can still sign in."""

    model_config = ConfigDict(extra="forbid")

    email: Email
    password: Annotated[str, Field(min_length=1, max_length=128)]


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class MeOut(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime
