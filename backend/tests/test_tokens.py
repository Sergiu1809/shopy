"""Access tokens: JWT HS256, 15 min, sub/iat/exp/type, no role (Q9, Q10). No Docker.

PyJWT is imported inside the tests, so a missing dependency fails loudly here.
"""

import os
import secrets

import pytest
from app.auth.tokens import create_access_token, jwt_secret


def decode(token: str, secret: str | None = None) -> dict[str, object]:
    import jwt

    claims: dict[str, object] = jwt.decode(
        token,
        secret or os.environ["JWT_SECRET"],
        algorithms=["HS256"],
        options={"require": ["sub", "iat", "exp", "type"]},
    )
    return claims


def test_access_token_is_hs256_with_the_four_claims() -> None:
    import jwt

    token = create_access_token(42)

    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    claims = decode(token)
    assert set(claims) == {"sub", "iat", "exp", "type"}
    assert claims["sub"] == "42"
    assert claims["type"] == "access"
    assert "role" not in claims


def test_access_token_lives_15_minutes() -> None:
    import time

    before = int(time.time())
    claims = decode(create_access_token(7))
    after = int(time.time())

    iat, exp = claims["iat"], claims["exp"]
    assert isinstance(iat, int) and isinstance(exp, int)
    assert exp - iat == 900
    assert before - 1 <= iat <= after + 1


def test_access_token_is_signed_with_the_current_env_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jwt

    other = secrets.token_urlsafe(48)
    monkeypatch.setenv("JWT_SECRET", other)

    token = create_access_token(1)

    assert decode(token, other)["sub"] == "1"
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, secrets.token_urlsafe(48), algorithms=["HS256"])


def test_jwt_secret_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    value = secrets.token_urlsafe(48)
    monkeypatch.setenv("JWT_SECRET", value)

    assert jwt_secret() == value


def test_jwt_secret_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        jwt_secret()


@pytest.mark.parametrize("value", ["", "change-me", "x" * 31])
def test_jwt_secret_shorter_than_32_bytes_raises(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("JWT_SECRET", value)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        jwt_secret()


@pytest.mark.parametrize("value", ["x" * 32, "ă" * 16])
def test_jwt_secret_of_32_bytes_is_accepted(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # "ă" is two bytes in UTF-8: the rule counts bytes, not characters.
    monkeypatch.setenv("JWT_SECRET", value)

    assert jwt_secret() == value
