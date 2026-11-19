"""Argon2id password hashing (Q11): `PasswordHasher` defaults, RFC 9106 low-memory.

Sync on purpose, so the seed (GH-5) reuses them; the API calls them in a threadpool.
"""

from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """False on a wrong password or a malformed hash; never raises."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@cache
def _dummy_hash() -> str:
    return hash_password("dummy password for unknown emails")


def verify_dummy(password: str) -> None:
    """One real verify for an unknown email, so timing does not reveal it (Q13)."""
    verify_password(password, _dummy_hash())
