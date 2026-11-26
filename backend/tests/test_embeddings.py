"""The embedding provider (GH-13 N10, N12; PATTERN-012, D-009).

`OpenAIEmbeddingProvider` is tested with an injected fake client (A5): the autouse
guard in conftest fails any test that builds the real `AsyncOpenAI` client.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, cast

import httpx
import openai
import pytest
from app.indexing import embeddings
from app.indexing.embeddings import (
    EMBEDDING_DIM,
    OPENAI_TIMEOUT_SECONDS,
    EmbeddingError,
    EmbeddingResult,
    OpenAIEmbeddingProvider,
    check_vectors,
)

from tests.stubs import StubEmbeddingProvider

MODEL = "text-embedding-3-small"
# What an SDK error message can carry: it must never reach last_error or a log.
SDK_MESSAGE = "Incorrect API key provided: test-key-****-leak. Find your key at ..."


class FakeEmbeddings:
    def __init__(self, response: Any = None, error: BaseException | None = None):
        self.response = response
        self.error = error
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def fake_client(response: Any = None, error: BaseException | None = None) -> Any:
    return SimpleNamespace(embeddings=FakeEmbeddings(response, error))


def fake_response(vectors_by_index: dict[int, list[float]], total_tokens: int) -> Any:
    # Deliberately out of index order: the provider must sort by `index`.
    data = [
        SimpleNamespace(index=i, embedding=v, object="embedding")
        for i, v in sorted(vectors_by_index.items(), reverse=True)
    ]
    return SimpleNamespace(
        data=data,
        model=MODEL,
        usage=SimpleNamespace(prompt_tokens=total_tokens, total_tokens=total_tokens),
    )


def provider_with(client: Any) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(
        api_key="test-key-not-real", model=MODEL, client=cast(Any, client)
    )


def status_error(cls: type[openai.APIStatusError], status: int) -> BaseException:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(status, request=request)
    return cls(SDK_MESSAGE, response=response, body=None)


def test_constants() -> None:
    assert EMBEDDING_DIM == 1536
    assert OPENAI_TIMEOUT_SECONDS == 60


async def test_request_shape() -> None:
    first, second = [0.1] * EMBEDDING_DIM, [0.2] * EMBEDDING_DIM
    client = fake_client(fake_response({0: first, 1: second}, total_tokens=42))
    provider = provider_with(client)

    result = await provider.embed(["primul text", "al doilea text"])

    # One request with every text; no `dimensions` override (N10).
    assert client.embeddings.requests == [
        {"model": MODEL, "input": ["primul text", "al doilea text"]}
    ]
    assert isinstance(result, EmbeddingResult)
    assert result.vectors == [first, second]
    assert result.total_tokens == 42
    assert provider.provider == "openai"
    assert provider.model == MODEL


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (openai.AuthenticationError, 401),
        (openai.RateLimitError, 429),
        (openai.InternalServerError, 500),
    ],
)
async def test_sdk_error_becomes_embedding_error(
    cls: type[openai.APIStatusError], status: int
) -> None:
    provider = provider_with(fake_client(error=status_error(cls, status)))

    with pytest.raises(EmbeddingError) as raised:
        await provider.embed(["text"])

    message = str(raised.value)
    assert message == f"openai {cls.__name__} ({status})"
    assert "Incorrect" not in message
    assert "leak" not in message


async def test_connection_error_becomes_embedding_error() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    provider = provider_with(
        fake_client(error=openai.APIConnectionError(request=request))
    )

    with pytest.raises(EmbeddingError, match="APIConnectionError"):
        await provider.embed(["text"])


def test_check_vectors_accepts_n_vectors_of_1536() -> None:
    result = EmbeddingResult(vectors=[[0.0] * 1536, [1.0] * 1536], total_tokens=3)

    check_vectors(result, 2)


@pytest.mark.parametrize(
    "vectors",
    [
        [[0.0] * 1536],  # one vector for two texts
        [[0.0] * 1536, [0.0] * 1536, [0.0] * 1536],
        [[0.0] * 1536, [0.0] * 1535],
        [[0.0] * 3072, [0.0] * 1536],
    ],
    ids=["too few", "too many", "1535", "3072"],
)
def test_check_vectors_rejects_count_or_size(vectors: list[list[float]]) -> None:
    with pytest.raises(EmbeddingError):
        check_vectors(EmbeddingResult(vectors=vectors, total_tokens=3), 2)


# --- N12: the guard ---------------------------------------------------------------


async def test_real_client_is_guarded() -> None:
    # Built in __init__ or on the first call: either way the guard fires.
    with pytest.raises(pytest.fail.Exception, match="real OpenAI client"):
        provider = OpenAIEmbeddingProvider(api_key="test-key-not-real", model=MODEL)
        await provider.embed(["text"])


def test_no_openai_key_in_a_test_run() -> None:
    assert "OPENAI_API_KEY" not in os.environ


async def test_the_stub_is_a_provider() -> None:
    stub = StubEmbeddingProvider(total_tokens=7)
    provider: embeddings.EmbeddingProvider = stub

    result = await provider.embed(["a", "b"])

    check_vectors(result, 2)
    assert result.vectors[0] != result.vectors[1]
    assert result.total_tokens == 7
    assert stub.calls == [["a", "b"]]
