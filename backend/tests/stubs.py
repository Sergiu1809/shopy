"""Test doubles for paid providers (PATTERN-012): tests inject them, no env picks."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence

from app.indexing.embeddings import EMBEDDING_DIM, EmbeddingResult

MODEL = "text-embedding-3-small"


def stub_vector(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """A deterministic vector from the text's SHA-256; different texts differ."""
    digest = hashlib.sha256(text.encode()).digest()
    return [((digest[i % len(digest)] + i) % 251) / 256 for i in range(dim)]


class StubEmbeddingProvider:
    """Records every call's texts; returns deterministic vectors, never calls out.

    `fail_with` is raised after the call is recorded (a provider error); `gate` holds
    the call open until it is set; `dim` other than 1536 returns wrong-size vectors.
    """

    provider: str = "openai"

    def __init__(
        self,
        *,
        model: str = MODEL,
        total_tokens: int = 100,
        dim: int = EMBEDDING_DIM,
        fail_with: BaseException | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.model = model
        self.total_tokens = total_tokens
        self.dim = dim
        self.fail_with = fail_with
        self.gate = gate
        self.calls: list[list[str]] = []

    @property
    def texts(self) -> list[str]:
        """Every text sent, over all calls."""
        return [text for call in self.calls for text in call]

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        self.calls.append(list(texts))
        if self.gate is not None:
            await self.gate.wait()
        if self.fail_with is not None:
            raise self.fail_with
        return EmbeddingResult(
            vectors=[stub_vector(text, self.dim) for text in texts],
            total_tokens=self.total_tokens,
        )
