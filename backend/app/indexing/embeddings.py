"""Embedding providers (PATTERN-012, D-009, N10): an interface, OpenAI, and checks.

Tests and CI inject a stub (`tests/stubs.py`); the real client is built only by the
worker process (`python -m worker`), never in a test (N12).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import openai
from openai import AsyncOpenAI

from app.models.indexing import EMBEDDING_DIM as EMBEDDING_DIM

# Seconds per request; the SDK's own retries stay at their default (A10).
OPENAI_TIMEOUT_SECONDS = 60


class EmbeddingError(Exception):
    """A failed or unusable embedding call; the message never quotes the provider."""


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    total_tokens: int


class EmbeddingProvider(Protocol):
    provider: str  # the usage_ledger value
    model: str

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult: ...


class OpenAIEmbeddingProvider:
    provider = "openai"

    def __init__(
        self, api_key: str, model: str, client: AsyncOpenAI | None = None
    ) -> None:
        self.model = model
        self._client = client or AsyncOpenAI(
            api_key=api_key, timeout=OPENAI_TIMEOUT_SECONDS
        )

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        """One request with every text; no `dimensions` override (N10)."""
        try:
            response = await self._client.embeddings.create(
                model=self.model, input=list(texts)
            )
        except openai.APIError as exc:
            # The SDK message can quote a masked key: keep the class and status only.
            status = getattr(exc, "status_code", None)
            suffix = f" ({status})" if status is not None else ""
            raise EmbeddingError(f"openai {type(exc).__name__}{suffix}") from None
        ordered = sorted(response.data, key=lambda item: item.index)
        return EmbeddingResult(
            vectors=[list(item.embedding) for item in ordered],
            total_tokens=response.usage.total_tokens,
        )


def check_vectors(result: EmbeddingResult, count: int) -> None:
    """One vector per text, each of EMBEDDING_DIM floats, or EmbeddingError."""
    if len(result.vectors) != count:
        raise EmbeddingError(f"expected {count} embeddings, got {len(result.vectors)}")
    for vector in result.vectors:
        if len(vector) != EMBEDDING_DIM:
            raise EmbeddingError(
                f"expected {EMBEDDING_DIM} dimensions, got {len(vector)}"
            )
