"""The formats of `catalog.json` and `users.json` (PATTERN-006, GH-5).

The only definition of both files: `python -m seed.validate_catalog` (CI) and
`python -m seed.seed` (`make seed`) parse them through these models, so they never
disagree. Every model rejects unknown fields; integers are strict, so `19.99`,
`"1999"` and `true` are not money.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from app.schemas.auth import Email

SEED_DIR = Path(__file__).resolve().parent
CATALOG_PATH = SEED_DIR / "catalog.json"
USERS_PATH = SEED_DIR / "users.json"

CATEGORY_SLUGS = (
    "clothing",
    "laundry-and-cleaning",
    "cosmetics-and-personal-care",
    "small-electronics",
    "home",
)
POLICY_KINDS = ("shipping", "returns", "warranty", "payment", "size_guide")
PRODUCT_FIXTURES = ("out_of_stock", "missing_attribute")
REVIEW_FIXTURES = ("prompt_injection", "xss")
MIN_PRODUCTS, MAX_PRODUCTS = 190, 210

Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Key = Annotated[StrictStr, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Slug = Annotated[StrictStr, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Sku = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z0-9]+(-[A-Z0-9]+)*$")]
AttributeValue = StrictStr | StrictInt | StrictBool | list[StrictStr]


def _utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("must be in UTC (offset 0), for example 2025-03-14T10:22:00Z")
    return value.astimezone(UTC)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- catalog.json --------------------------------------------------------------


class StoreIn(_Model):
    name: Literal["Shopy"]
    currency: Literal["RON"]


class PolicyIn(_Model):
    kind: Literal["shipping", "returns", "warranty", "payment", "size_guide"]
    title: Text
    body: Text


class VariantIn(_Model):
    sku: Sku
    attributes: dict[Key, Text]
    price_minor: Annotated[StrictInt, Field(gt=0)]  # bani, VAT included (PATTERN-001)
    stock: Annotated[StrictInt, Field(ge=0)]


class ReviewIn(_Model):
    author_display_name: Text
    rating: Annotated[StrictInt, Field(ge=1, le=5)]
    title: Text
    body: Text
    created_at: Annotated[AwareDatetime, AfterValidator(_utc)]
    fixture: Literal["prompt_injection", "xss"] | None = None


class ProductIn(_Model):
    brand: Text
    name: Text
    description: Text
    attributes: dict[Key, AttributeValue]
    variants: Annotated[list[VariantIn], Field(min_length=1)]
    reviews: Annotated[list[ReviewIn], Field(min_length=3, max_length=15)]
    fixture: Literal["out_of_stock", "missing_attribute"] | None = None


class CategoryIn(_Model):
    slug: Slug
    name: Text
    products: list[ProductIn]


def _repeated(counts: Counter[str]) -> list[str]:
    return [item for item, n in counts.items() if n > 1]


class CatalogFile(_Model):
    store: StoreIn
    policies: list[PolicyIn]
    categories: list[CategoryIn]

    @model_validator(mode="after")
    def _whole_file(self) -> Self:
        """Rules across the file; every problem is reported, not only the first."""
        problems = [
            *self._category_problems(),
            *self._count_problems(),
            *self._policy_problems(),
            *self._fixture_problems(),
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def _products(self) -> list[tuple[str, ProductIn]]:
        return [(c.slug, p) for c in self.categories for p in c.products]

    def _category_problems(self) -> list[str]:
        slugs = Counter(c.slug for c in self.categories)
        problems = []
        if missing := [s for s in CATEGORY_SLUGS if s not in slugs]:
            problems.append(f"categories: missing slug {', '.join(missing)}")
        if extra := [s for s in slugs if s not in CATEGORY_SLUGS]:
            problems.append(f"categories: unexpected slug {', '.join(extra)}")
        if repeated := _repeated(slugs):
            problems.append(f"categories: duplicate slug {', '.join(repeated)}")
        return problems

    def _count_problems(self) -> list[str]:
        problems = []
        total = len(self._products())
        if not MIN_PRODUCTS <= total <= MAX_PRODUCTS:
            problems.append(
                f"products: {total} in total, expected {MIN_PRODUCTS} to {MAX_PRODUCTS}"
            )
        skus = Counter(v.sku for _, p in self._products() for v in p.variants)
        if repeated := _repeated(skus):
            problems.append(f"sku used more than once: {', '.join(repeated)}")
        return problems

    def _policy_problems(self) -> list[str]:
        kinds = Counter[str](p.kind for p in self.policies)
        problems = []
        if missing := [k for k in POLICY_KINDS if k not in kinds]:
            problems.append(f"policies: missing kind {', '.join(missing)}")
        if repeated := _repeated(kinds):
            problems.append(f"policies: duplicate kind {', '.join(repeated)}")
        return problems

    def _fixture_problems(self) -> list[str]:
        products = self._products()
        reviews = [r for _, p in products for r in p.reviews]
        found = Counter[str](
            [p.fixture for _, p in products if p.fixture]
            + [r.fixture for r in reviews if r.fixture]
        )
        problems = [
            f"fixture {kind}: found {found[kind]}, expected exactly 1"
            for kind in (*REVIEW_FIXTURES, *PRODUCT_FIXTURES)
            if found[kind] != 1
        ]
        for slug, product in products:
            if product.fixture == "out_of_stock":
                if any(v.stock != 0 for v in product.variants):
                    problems.append(
                        f"fixture out_of_stock: {product.name!r} has a variant"
                        " with stock above 0"
                    )
            elif product.fixture == "missing_attribute":
                problems.extend(_missing_attribute_problems(slug, product))
        for review in reviews:
            body = review.body.lower()
            has_markup = "<script" in body and "onerror=" in body
            if review.fixture == "xss" and not has_markup:
                problems.append("fixture xss: the body needs both <script and onerror=")
        return problems


def _missing_attribute_problems(slug: str, product: ProductIn) -> list[str]:
    problems = []
    if slug != "clothing":
        problems.append(f"fixture missing_attribute: must be in clothing, not {slug}")
    if "material" in product.attributes or any(
        "material" in v.attributes for v in product.variants
    ):
        problems.append("fixture missing_attribute: has a material attribute")
    if "material" in product.description.lower():
        problems.append("fixture missing_attribute: the description names the material")
    return problems


# --- users.json ----------------------------------------------------------------


class AddressIn(_Model):
    label: Text | None
    full_name: Text
    phone: Text
    street: Text
    city: Text
    county: Text
    postal_code: Annotated[StrictStr, StringConstraints(pattern=r"^[0-9]{6}$")]
    is_default: StrictBool


class PreferencesIn(_Model):
    sizes: dict[Text, Text]
    preferred_brands: list[Text]


class UserIn(_Model):
    """No password here: the role picks the SEED_* variable (PATTERN-013)."""

    email: Email  # GH-4's rule: lowercased, `.test` / `.local` rejected as at login
    role: Literal["admin", "customer"]
    addresses: list[AddressIn]
    preferences: PreferencesIn | None

    @model_validator(mode="after")
    def _one_default_address(self) -> Self:
        defaults = sum(a.is_default for a in self.addresses)
        if self.addresses and defaults != 1:
            raise ValueError(
                f"addresses: exactly one must be the default, found {defaults}"
            )
        return self


class UsersFile(_Model):
    users: list[UserIn]

    @model_validator(mode="after")
    def _unique_emails(self) -> Self:
        if repeated := _repeated(Counter(u.email for u in self.users)):
            raise ValueError(f"email used more than once: {', '.join(repeated)}")
        return self


def load_catalog(path: Path = CATALOG_PATH) -> CatalogFile:
    return CatalogFile.model_validate_json(path.read_bytes())


def load_users(path: Path = USERS_PATH) -> UsersFile:
    return UsersFile.model_validate_json(path.read_bytes())
