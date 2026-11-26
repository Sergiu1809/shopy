"""`python -m seed.validate_catalog`: check `catalog.json` and `users.json` (CI step).

Prints `OK: <n> products, ...` and exits 0, or prints every error and exits 1.
Errors name the location and the rule, never the input, so no large text is echoed.
"""

import sys
from pathlib import Path

from pydantic import ValidationError

from seed.schema import CATALOG_PATH, USERS_PATH, load_catalog, load_users


def describe(name: str, exc: ValidationError) -> list[str]:
    """One readable line per error: file, location and message; no input."""
    lines = []
    for error in exc.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "(file)"
        lines.append(f"{name}: {location}: {error['msg']}")
    return lines


def validate_files(catalog_path: Path, users_path: Path) -> list[str]:
    errors: list[str] = []
    for path, load in ((catalog_path, load_catalog), (users_path, load_users)):
        try:
            load(path)
        except ValidationError as exc:
            errors.extend(describe(path.name, exc))
        except OSError as exc:
            errors.append(f"{path.name}: cannot read the file ({exc.strerror})")
    return errors


def main() -> int:
    errors = validate_files(CATALOG_PATH, USERS_PATH)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"{len(errors)} error(s).", file=sys.stderr)
        return 1
    catalog, users = load_catalog(CATALOG_PATH), load_users(USERS_PATH)
    products = [p for c in catalog.categories for p in c.products]
    variants = sum(len(p.variants) for p in products)
    reviews = sum(len(p.reviews) for p in products)
    print(
        f"OK: {len(products)} products, {variants} variants, {reviews} reviews,"
        f" {len(users.users)} users"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
