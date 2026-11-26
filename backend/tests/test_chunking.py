"""Chunk text rules (GH-13 B1, B2, N1): pure functions, golden strings, no database.

Interface the tests settle (the plan names the functions, not their arguments):
- `product_text(product, category_name, variants) -> str`, ORM objects (transient
  here); variants in any order, their values taken in variant `id` order;
- `review_chunks(reviews) -> list[str]`, ORM `Review` objects in any order;
- `policy_chunks(title, body) -> list[str]`;
- `content_hash(model, text) -> str`; `MAX_CHUNK_CHARS == 2000`.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.indexing.chunking import (
    MAX_CHUNK_CHARS,
    content_hash,
    policy_chunks,
    product_text,
    review_chunks,
)
from app.models import Product, ProductVariant, Review

MODEL = "text-embedding-3-small"
T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def product(**values: Any) -> Product:
    row: dict[str, Any] = {
        "id": 1,
        "brand": "Nike",
        "name": "Hanorac Club",
        "description": "Hanorac cu glugă.",
        "attributes": {},
        "rating_avg": Decimal("4.67"),
        "rating_count": 3,
        "version": 4,
        **values,
    }
    return Product(**row)


def variant(
    variant_id: int, attributes: dict[str, str], **values: Any
) -> ProductVariant:
    row: dict[str, Any] = {
        "id": variant_id,
        "product_id": 1,
        "sku": f"CLO-1-{variant_id}",
        "attributes": attributes,
        "price_minor": 24999,
        "stock": 17,
        **values,
    }
    return ProductVariant(**row)


def review(
    review_id: int,
    *,
    rating: int = 5,
    title: str = "Bun",
    body: str = "Îmi place.",
    created_at: datetime = T0,
) -> Review:
    return Review(
        id=review_id,
        product_id=1,
        author_display_name="Maria Popescu",
        rating=rating,
        title=title,
        body=body,
        created_at=created_at,
    )


def line_of(review_id: int, length: int) -> tuple[Review, str]:
    """A review whose rendered line has exactly `length` characters, and that line."""
    prefix = f"[#{review_id}] 5/5 — T: "
    body = "a" * (length - len(prefix))
    return review(review_id, title="T", body=body), prefix + body


# --- B1: the product chunk --------------------------------------------------------


def test_product_text_golden() -> None:
    item = product(
        attributes={
            "material": "bumbac",
            "gender": "bărbați",
            "pockets": 2,
            "hood": True,
            "waterproof": False,
            "features": ["glugă reglabilă", "buzunar cangur"],
        }
    )
    variants = [
        variant(12, {"size": "M", "color": "negru"}, sku="CLO-001-NEGRU-M"),
        variant(10, {"size": "S", "color": "negru"}, sku="CLO-001-NEGRU-S"),
        variant(11, {"size": "L", "color": "alb"}, sku="CLO-001-ALB-L"),
    ]

    text = product_text(item, "Îmbrăcăminte", variants)

    assert text == (
        "Nume: Hanorac Club\n"
        "Marcă: Nike\n"
        "Categorie: Îmbrăcăminte\n"
        "features: glugă reglabilă, buzunar cangur\n"
        "gender: bărbați\n"
        "hood: da\n"
        "material: bumbac\n"
        "pockets: 2\n"
        "waterproof: nu\n"
        "Descriere: Hanorac cu glugă.\n"
        "Variante: color: negru, alb; size: S, L, M"
    )


def test_product_text_never_holds_sku_price_stock_or_rating() -> None:
    item = product(rating_avg=Decimal("4.67"), rating_count=31)
    variants = [
        variant(1, {"size": "M"}, sku="CLO-777-NEGRU-M", price_minor=98765, stock=4321)
    ]

    text = product_text(item, "Îmbrăcăminte", variants)

    for forbidden in ["CLO-777", "98765", "987.65", "987,65", "4321", "4.67", "31"]:
        assert forbidden not in text
    for label in ["SKU", "Preț", "Stoc", "Rating"]:
        assert label not in text


def test_product_text_without_attributes_or_variants() -> None:
    text = product_text(product(attributes={}), "Încălțăminte", [])

    assert text == (
        "Nume: Hanorac Club\n"
        "Marcă: Nike\n"
        "Categorie: Încălțăminte\n"
        "Descriere: Hanorac cu glugă."
    )


def test_no_variante_line_when_no_variant_has_attributes() -> None:
    text = product_text(product(), "Îmbrăcăminte", [variant(1, {}), variant(2, {})])

    assert "Variante" not in text
    assert text.endswith("Descriere: Hanorac cu glugă.")


def test_variante_line_skips_variants_without_a_key() -> None:
    variants = [variant(3, {"size": "M"}), variant(4, {}), variant(5, {"size": "M"})]

    text = product_text(product(), "Îmbrăcăminte", variants)

    assert text.splitlines()[-1] == "Variante: size: M"


def test_product_text_keeps_catalog_text_as_is() -> None:
    item = product(
        name="Rochie „Vara” 100% in",
        description="Linia 1.\nLinia 2: <b>nu</b> e HTML.",
        attributes={"care": "spălare la 30 °C, pe dos"},
    )

    text = product_text(item, "Rochii & fuste", [])

    assert "Nume: Rochie „Vara” 100% in\n" in text
    assert "Categorie: Rochii & fuste\n" in text
    assert "care: spălare la 30 °C, pe dos\n" in text
    assert text.endswith("Descriere: Linia 1.\nLinia 2: <b>nu</b> e HTML.")


# --- B2: reviews ------------------------------------------------------------------


def test_review_chunks_golden_and_ordered_by_created_at_then_id() -> None:
    reviews = [
        review(9, rating=3, title="Ok", body="Merge.", created_at=T0 + timedelta(1)),
        review(7, rating=5, title="Super", body="Excelent!", created_at=T0),
        review(5, rating=4, title="Bun", body="Îmi place.", created_at=T0),
        review(
            2, rating=1, title="Slab", body="S-a rupt.", created_at=T0 + timedelta(2)
        ),
    ]

    assert review_chunks(reviews) == [
        "[#5] 4/5 — Bun: Îmi place.\n"
        "[#7] 5/5 — Super: Excelent!\n"
        "[#9] 3/5 — Ok: Merge.\n"
        "[#2] 1/5 — Slab: S-a rupt."
    ]


def test_review_chunks_hold_no_author_name() -> None:
    chunks = review_chunks([review(1), review(2)])

    assert all("Maria" not in chunk and "Popescu" not in chunk for chunk in chunks)


def test_no_reviews_no_chunks() -> None:
    assert review_chunks([]) == []


def test_reviews_fill_a_chunk_up_to_exactly_2000_characters() -> None:
    first, first_line = line_of(1, 1000)
    second, second_line = line_of(2, 999)

    chunks = review_chunks([first, second])

    assert chunks == [f"{first_line}\n{second_line}"]
    assert len(chunks[0]) == MAX_CHUNK_CHARS == 2000


def test_reviews_split_at_a_review_boundary_past_2000() -> None:
    first, first_line = line_of(1, 1000)
    second, second_line = line_of(2, 1000)

    assert review_chunks([first, second]) == [first_line, second_line]


def test_reviews_pack_greedily_in_order() -> None:
    made = [line_of(n, 700) for n in range(1, 6)]
    reviews = [r for r, _ in made]
    lines = [line for _, line in made]

    chunks = review_chunks(reviews)

    assert chunks == [
        f"{lines[0]}\n{lines[1]}",
        f"{lines[2]}\n{lines[3]}",
        lines[4],
    ]
    assert all(len(chunk) <= MAX_CHUNK_CHARS for chunk in chunks)


def test_a_review_longer_than_2000_is_its_own_chunk_uncut() -> None:
    short_a, line_a = line_of(1, 50)
    long_review, long_line = line_of(2, 2500)
    short_b, line_b = line_of(3, 50)

    chunks = review_chunks([short_a, long_review, short_b])

    assert chunks == [line_a, long_line, line_b]


# --- B2: policies -----------------------------------------------------------------


def test_short_policy_is_one_chunk_title_blank_line_body() -> None:
    assert policy_chunks(
        "Livrare", "Livrăm în 2-3 zile.\n\nGratuit peste 200 lei."
    ) == ["Livrare\n\nLivrăm în 2-3 zile.\n\nGratuit peste 200 lei."]


def test_policy_of_exactly_2000_characters_is_one_chunk() -> None:
    title = "Retur"
    body = "Paragraful unu.\n\n" + "b" * (
        2000 - len(title) - 2 - len("Paragraful unu.\n\n")
    )

    chunks = policy_chunks(title, body)

    assert chunks == [f"{title}\n\n{body}"]
    assert len(chunks[0]) == 2000


def test_long_policy_splits_at_blank_lines_only() -> None:
    paragraphs = [c * 900 for c in "pqrs"]
    title = "Garanție"
    body = "\n\n".join(paragraphs)
    full = f"{title}\n\n{body}"

    chunks = policy_chunks(title, body)

    assert chunks == [
        f"{title}\n\n{paragraphs[0]}\n\n{paragraphs[1]}",
        f"{paragraphs[2]}\n\n{paragraphs[3]}",
    ]
    assert "\n\n".join(chunks) == full
    assert all(len(chunk) <= MAX_CHUNK_CHARS for chunk in chunks)


def test_policy_paragraph_longer_than_2000_stays_whole() -> None:
    long_paragraph = "x" * 2300
    body = f"Scurt.\n\n{long_paragraph}\n\nFinal."

    chunks = policy_chunks("Plată", body)

    assert long_paragraph in chunks
    assert "\n\n".join(chunks) == f"Plată\n\n{body}"
    assert all(len(c) <= MAX_CHUNK_CHARS for c in chunks if c != long_paragraph)


# --- N1: content_hash -------------------------------------------------------------


def test_content_hash_formula() -> None:
    text = "Nume: Hanorac\nMarcă: Nike"

    expected = hashlib.sha256(f"{MODEL}\n{text}".encode()).hexdigest()

    assert content_hash(MODEL, text) == expected
    assert len(expected) == 64


@pytest.mark.parametrize(
    ("model", "text"),
    [("text-embedding-3-large", "Nume: Hanorac"), (MODEL, "Nume: Hanorac.")],
)
def test_content_hash_changes_with_model_or_text(model: str, text: str) -> None:
    assert content_hash(model, text) != content_hash(MODEL, "Nume: Hanorac")
