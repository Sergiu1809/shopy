"""Chunk text rules (GH-13 B1, B2, N1): pure functions, no database, no I/O.

Chunk text is catalog data with Romanian labels (D-021). Never SKU, price, stock or
rating (D-006, D-010): those are read live.
"""

import hashlib
from collections.abc import Iterable, Sequence
from typing import Any

from app.models import Product, ProductVariant, Review

MAX_CHUNK_CHARS = 2000


def content_hash(model: str, text: str) -> str:
    """SHA-256 hex of the model and the text: a new model re-embeds everything (N1)."""
    return hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()


def _render(value: Any) -> str:
    """An attribute value (PATTERN-016): text as is, bool da/nu, list joined (A3)."""
    if isinstance(value, bool):
        return "da" if value else "nu"
    if isinstance(value, list):
        return ", ".join(_render(item) for item in value)
    return str(value)


def _variant_summary(variants: Iterable[ProductVariant]) -> str | None:
    """`<key>: <distinct values>; …`, keys sorted, values in variant id order."""
    values: dict[str, list[str]] = {}
    for variant in sorted(variants, key=lambda v: v.id):
        for key, value in variant.attributes.items():
            rendered = _render(value)
            seen = values.setdefault(key, [])
            if rendered not in seen:
                seen.append(rendered)
    if not values:
        return None
    return "; ".join(f"{key}: {', '.join(values[key])}" for key in sorted(values))


def product_text(
    product: Product, category_name: str, variants: Iterable[ProductVariant]
) -> str:
    """The one chunk of a product (B1), one field per line."""
    lines = [
        f"Nume: {product.name}",
        f"Marcă: {product.brand}",
        f"Categorie: {category_name}",
    ]
    attributes = product.attributes or {}
    lines += [f"{key}: {_render(attributes[key])}" for key in sorted(attributes)]
    lines.append(f"Descriere: {product.description}")
    summary = _variant_summary(variants)
    if summary is not None:
        lines.append(f"Variante: {summary}")
    return "\n".join(lines)


def _pack(units: Sequence[str], separator: str) -> list[str]:
    """Join units greedily while a chunk stays within MAX_CHUNK_CHARS; never cut one."""
    chunks: list[str] = []
    current: str | None = None
    for unit in units:
        if current is None:
            current = unit
        elif len(current) + len(separator) + len(unit) <= MAX_CHUNK_CHARS:
            current += separator + unit
        else:
            chunks.append(current)
            current = unit
    if current is not None:
        chunks.append(current)
    return chunks


def review_chunks(reviews: Iterable[Review]) -> list[str]:
    """A product's reviews (B2): oldest first, split only between reviews.

    No author and no product name, so a product edit never reindexes its reviews.
    """
    ordered = sorted(reviews, key=lambda r: (r.created_at, r.id))
    lines = [f"[#{r.id}] {r.rating}/5 — {r.title}: {r.body}" for r in ordered]
    return _pack(lines, "\n")


def policy_chunks(title: str, body: str) -> list[str]:
    """One chunk per policy (A4); a longer one splits at blank lines only (B2)."""
    text = f"{title}\n\n{body}"
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    return _pack([title, *body.split("\n\n")], "\n\n")
