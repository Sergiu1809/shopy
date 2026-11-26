"""Catalog field types, and the admin product bodies and responses (PATTERN-006).

`Text`, `Key`, `Sku` and `AttributeValue` are defined here once; `seed/schema.py`
imports them, so the seed and the admin routes accept the same shapes (GH-5, GH-6).
Bodies reject unknown fields, so `store_id`, `version`, the ratings and
`content_hash` can never be submitted. Integers are strict: `"100"`, `1.5` and
`true` are not a price or a stock.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    ValidatorFunctionWrapHandler,
    WrapValidator,
    field_validator,
)
from pydantic_core import PydanticCustomError

BIGINT_MAX = 2**63 - 1  # bigint identity IDs (D-024)
INT4_MAX = 2_147_483_647  # the `integer` columns price_minor and stock

Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Key = Annotated[StrictStr, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Sku = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z0-9]+(-[A-Z0-9]+)*$")]
AttributeValue = StrictStr | StrictInt | StrictBool | list[StrictStr]

Id = Annotated[StrictInt, Field(ge=1, le=BIGINT_MAX)]
Count = Annotated[StrictInt, Field(ge=0, le=INT4_MAX)]  # bani or pieces


def _fixed_message(message: str) -> WrapValidator:
    """One error under the field itself: pydantic's own would name the bad key."""

    def validate(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
        try:
            return handler(value)
        except ValidationError:
            raise PydanticCustomError("attributes", message) from None

    return WrapValidator(validate)


ProductAttributes = Annotated[
    dict[Key, AttributeValue],
    _fixed_message(
        "Attributes must map lowercase keys (a-z, 0-9, _) to text, whole numbers,"
        " true/false or lists of text."
    ),
]
VariantAttributes = Annotated[
    dict[Key, Text],
    _fixed_message(
        "Attributes must map lowercase keys (a-z, 0-9, _) to non-empty text."
    ),
]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Patch(_Body):
    """Every field optional; an explicit null is rejected (the columns are NOT NULL)."""

    @field_validator("*")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        if value is None:
            raise PydanticCustomError("not_null", "must not be null")
        return value


class ProductCreate(_Body):
    category_id: Id
    brand: Text
    name: Text
    description: Text
    attributes: ProductAttributes


class ProductUpdate(_Patch):
    category_id: Id | None = None
    brand: Text | None = None
    name: Text | None = None
    description: Text | None = None
    attributes: ProductAttributes | None = None


class VariantCreate(_Body):
    sku: Sku
    attributes: VariantAttributes
    price_minor: Count  # bani, VAT included (PATTERN-001)
    stock: Count


class VariantUpdate(_Patch):
    sku: Sku | None = None
    attributes: VariantAttributes | None = None
    price_minor: Count | None = None
    stock: Count | None = None


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class VariantOut(_Out):
    id: int
    product_id: int
    sku: str
    attributes: dict[str, Any]
    price_minor: int
    stock: int
    version: int


class ProductOut(_Out):
    """No `content_hash`: it belongs to the reindex worker (P2)."""

    id: int
    store_id: int
    category_id: int
    brand: str
    name: str
    description: str
    attributes: dict[str, Any]
    rating_avg: Decimal | None  # sent as a string, e.g. "4.30"
    rating_count: int
    version: int
    updated_at: datetime


class ProductDetailOut(ProductOut):
    variants: list[VariantOut]  # ordered by id


class ProductPage(BaseModel):
    items: list[ProductOut]  # ordered by id, without variants
    total: int
