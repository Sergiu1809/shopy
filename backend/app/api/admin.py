"""`/admin`: every route on this router needs an admin (PATTERN-007, Q2).

The dependency sits at router level, so a route added here can't forget it, and it
runs before the body is validated: a customer gets 403, never a 422.

Products and their variants (GH-6). Every write locks the product row first (then
the variant), compares each submitted value with the row, writes only what differs,
and bumps a counter with `version = version + 1` in SQL only when something changed:
- `products.version`: any product field; a variant created, deleted, or with a new
  `sku` or `attributes` (what the product's index chunk holds, P2).
- `product_variants.version`: `price_minor` or `stock` (D-014).
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.db import get_session
from app.errors import ApiError
from app.models import Category, Product, ProductVariant, Store
from app.schemas.catalog import (
    BIGINT_MAX,
    ProductCreate,
    ProductDetailOut,
    ProductOut,
    ProductPage,
    ProductUpdate,
    VariantCreate,
    VariantOut,
    VariantUpdate,
)

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)

Session = Annotated[AsyncSession, Depends(get_session)]
ProductId = Annotated[int, Path(ge=1, le=BIGINT_MAX)]
VariantId = Annotated[int, Path(ge=1, le=BIGINT_MAX)]

PRODUCT_NOT_FOUND = "Product not found."
VARIANT_NOT_FOUND = "Variant not found."
# Fields the product's index chunk holds (P2): a change bumps the product version.
DESCRIPTIVE_VARIANT_FIELDS = {"sku", "attributes"}
# Read live, never indexed (D-006): a change bumps the variant version (D-014).
LIVE_VARIANT_FIELDS = {"price_minor", "stock"}


async def _store_id(db: AsyncSession) -> int | None:
    """The single store (brief §7: one row in v1); the seed picks it the same way."""
    store_id: int | None = await db.scalar(select(Store.id).order_by(Store.id).limit(1))
    return store_id


async def _category_in_store(db: AsyncSession, category_id: int, store_id: int) -> bool:
    found = await db.scalar(
        select(Category.id).where(
            Category.id == category_id, Category.store_id == store_id
        )
    )
    return found is not None


def _unknown_category() -> RequestValidationError:
    """A 422 under `category_id`, built by the one validation handler (C-001)."""
    return RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "category_id"),
                "msg": "Unknown category.",
            }
        ]
    )


async def _product(db: AsyncSession, product_id: int, *, lock: bool = False) -> Product:
    query = select(Product).where(Product.id == product_id)
    if lock:
        query = query.with_for_update()
    product = await db.scalar(query.execution_options(populate_existing=True))
    if product is None:
        raise ApiError(404, "not_found", PRODUCT_NOT_FOUND)
    return product


async def _locked_variant(
    db: AsyncSession, product_id: int, variant_id: int
) -> ProductVariant:
    """Only a variant of this product; lock it after its product (one lock order)."""
    variant = await db.scalar(
        select(ProductVariant)
        .where(ProductVariant.id == variant_id)
        .where(ProductVariant.product_id == product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if variant is None:
        raise ApiError(404, "not_found", VARIANT_NOT_FOUND)
    return variant


async def _flush_sku(db: AsyncSession) -> None:
    """Flush; a SKU that exists is a 409 (the unique constraint decides, race-safe)."""
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_product_variants_sku" not in str(exc.orig):
            raise
        raise ApiError(409, "sku_taken", "This SKU is already in use.") from None


def _dump(value: Any) -> str:
    # JSON on both sides: Python says 1 == True, JSONB does not.
    return json.dumps(value, sort_keys=True)


def _changes(row: Any, submitted: dict[str, Any]) -> dict[str, Any]:
    """The submitted fields whose value differs from the row's."""
    return {
        name: value
        for name, value in submitted.items()
        if _dump(getattr(row, name)) != _dump(value)
    }


async def _variants(db: AsyncSession, product_id: int) -> list[VariantOut]:
    variants = await db.scalars(
        select(ProductVariant)
        .where(ProductVariant.product_id == product_id)
        .order_by(ProductVariant.id)
    )
    return [VariantOut.model_validate(v) for v in variants]


async def _detail(db: AsyncSession, product: Product) -> ProductDetailOut:
    return ProductDetailOut(
        **ProductOut.model_validate(product).model_dump(),
        variants=await _variants(db, product.id),
    )


@router.get("/products")
async def list_products(
    db: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=BIGINT_MAX)] = 0,
) -> ProductPage:
    total = await db.scalar(select(func.count()).select_from(Product))
    products = await db.scalars(
        select(Product).order_by(Product.id).limit(limit).offset(offset)
    )
    return ProductPage(
        items=[ProductOut.model_validate(p) for p in products], total=total or 0
    )


@router.post("/products", status_code=201)
async def create_product(body: ProductCreate, db: Session) -> ProductDetailOut:
    store_id = await _store_id(db)
    if store_id is None or not await _category_in_store(db, body.category_id, store_id):
        raise _unknown_category()
    product = Product(store_id=store_id, **body.model_dump())
    db.add(product)
    await db.flush()
    await db.refresh(product)
    detail = await _detail(db, product)
    await db.commit()
    return detail


@router.get("/products/{product_id}")
async def get_product(product_id: ProductId, db: Session) -> ProductDetailOut:
    return await _detail(db, await _product(db, product_id))


@router.patch("/products/{product_id}")
async def update_product(
    product_id: ProductId, body: ProductUpdate, db: Session
) -> ProductDetailOut:
    product = await _product(db, product_id, lock=True)
    changes = _changes(product, body.model_dump(exclude_unset=True))
    if "category_id" in changes and not await _category_in_store(
        db, changes["category_id"], product.store_id
    ):
        raise _unknown_category()
    if changes:
        for name, value in changes.items():
            setattr(product, name, value)
        product.version = Product.version + 1
        await db.flush()
        await db.refresh(product)
    detail = await _detail(db, product)
    await db.commit()
    return detail


@router.delete("/products/{product_id}", status_code=204, response_class=Response)
async def delete_product(product_id: ProductId, db: Session) -> Response:
    """Hard delete; variants, images and reviews go with it (FK cascade, Q-017)."""
    deleted = await db.scalar(
        delete(Product).where(Product.id == product_id).returning(Product.id)
    )
    if deleted is None:
        raise ApiError(404, "not_found", PRODUCT_NOT_FOUND)
    await db.commit()
    return Response(status_code=204)


@router.get("/products/{product_id}/variants")
async def list_variants(product_id: ProductId, db: Session) -> list[VariantOut]:
    product = await _product(db, product_id)
    return await _variants(db, product.id)


@router.post("/products/{product_id}/variants", status_code=201)
async def create_variant(
    product_id: ProductId, body: VariantCreate, db: Session
) -> VariantOut:
    product = await _product(db, product_id, lock=True)
    variant = ProductVariant(product_id=product.id, **body.model_dump())
    db.add(variant)
    product.version = Product.version + 1
    await _flush_sku(db)
    await db.refresh(variant)
    out = VariantOut.model_validate(variant)
    await db.commit()
    return out


@router.patch("/products/{product_id}/variants/{variant_id}")
async def update_variant(
    product_id: ProductId, variant_id: VariantId, body: VariantUpdate, db: Session
) -> VariantOut:
    product = await _product(db, product_id, lock=True)
    variant = await _locked_variant(db, product.id, variant_id)
    changes = _changes(variant, body.model_dump(exclude_unset=True))
    if changes:
        for name, value in changes.items():
            setattr(variant, name, value)
        if changes.keys() & DESCRIPTIVE_VARIANT_FIELDS:
            product.version = Product.version + 1
        if changes.keys() & LIVE_VARIANT_FIELDS:
            variant.version = ProductVariant.version + 1
        await _flush_sku(db)
        await db.refresh(variant)
    out = VariantOut.model_validate(variant)
    await db.commit()
    return out


@router.delete(
    "/products/{product_id}/variants/{variant_id}",
    status_code=204,
    response_class=Response,
)
async def delete_variant(
    product_id: ProductId, variant_id: VariantId, db: Session
) -> Response:
    """Hard delete; the last variant of a product may go too (Q-017)."""
    product = await _product(db, product_id, lock=True)
    deleted = await db.scalar(
        delete(ProductVariant)
        .where(ProductVariant.id == variant_id)
        .where(ProductVariant.product_id == product.id)
        .returning(ProductVariant.id)
    )
    if deleted is None:
        raise ApiError(404, "not_found", VARIANT_NOT_FOUND)
    product.version = Product.version + 1
    await db.commit()
    return Response(status_code=204)
