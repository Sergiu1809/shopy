"""Argon2id password hashing (Q11); sync functions the seed (GH-5) reuses. No Docker."""

import pytest

from app.auth.passwords import (
    hash_password,
    needs_rehash,
    verify_dummy,
    verify_password,
)

PASSWORD = "Parola123"


def test_hash_is_argon2id_with_rfc9106_low_memory_defaults() -> None:
    from argon2 import PasswordHasher
    from argon2.low_level import Type

    hashed = hash_password(PASSWORD)

    assert hashed.startswith("$argon2id$")
    assert "m=65536,t=3,p=4" in hashed
    default = PasswordHasher()
    assert default.type is Type.ID
    assert not default.check_needs_rehash(hashed)
    assert PASSWORD not in hashed


def test_hash_is_salted() -> None:
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_verify_password_accepts_the_right_password() -> None:
    hashed = hash_password(PASSWORD)

    assert verify_password(PASSWORD, hashed) is True


def test_verify_password_rejects_a_wrong_password() -> None:
    hashed = hash_password(PASSWORD)

    assert verify_password("Parola124", hashed) is False


def test_verify_password_rejects_a_malformed_hash() -> None:
    assert verify_password(PASSWORD, "not-a-hash") is False


def test_needs_rehash_for_weaker_parameters() -> None:
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)

    assert needs_rehash(weak) is True
    assert needs_rehash(hash_password(PASSWORD)) is False


def test_verify_dummy_runs_a_real_argon2_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown emails cost one verify too, so timing does not reveal them (Q13)."""
    from argon2 import PasswordHasher

    calls: list[str] = []
    original = PasswordHasher.verify

    def spy(self: PasswordHasher, hash: str | bytes, password: str | bytes) -> bool:
        calls.append(str(hash))
        return original(self, hash, password)

    monkeypatch.setattr(PasswordHasher, "verify", spy)

    assert verify_dummy(PASSWORD) is None  # type: ignore[func-returns-value]
    assert len(calls) == 1
    assert calls[0].startswith("$argon2id$")
