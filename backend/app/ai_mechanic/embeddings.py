"""Embedding client + protocol.

Embeddings hit OpenAI `text-embedding-3-small` by default (1536-dim,
matches the migration's `vector(1536)` column). Phase 5 swaps to a
Gemini-native embedding once Google ships an `text-embedding`-compatible
endpoint we can route via LiteLLM.

Tests substitute `FakeEmbeddingClient` so the test suite never burns
tokens.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Protocol

from openai import AsyncOpenAI

from app.platform.config import Settings
from app.platform.logging import get_logger

logger = get_logger("app.ai_mechanic.embeddings")

EMBEDDING_DIM = 1536


def content_hash(text: str) -> str:
    """Stable hash for the embedding cache key. SHA-256 hex digest."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingClient(Protocol):
    """Surface every concrete implementation must satisfy."""

    async def embed(self, *, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingClient:
    """Production client. Routes to OpenAI's embedding API.

    Falls back from `OPENAI_API_KEY` to `GEMINI_API_KEY` so the
    dogfooding setup with one key works. When Google ships a 1536-dim
    embedding model this whole class becomes a wrapper over the LiteLLM
    embedding API.
    """

    def __init__(self, *, settings: Settings) -> None:
        api_key = settings.openai_api_key or settings.gemini_api_key
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY or GEMINI_API_KEY must be set to compute embeddings")
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = settings.ai_mechanic_embedding_model

    async def embed(self, *, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [list(item.embedding) for item in response.data]


class FakeEmbeddingClient:
    """In-memory deterministic stand-in for tests.

    Hashes each input into a 1536-dim float vector. Stable across runs
    so cosine-similarity assertions are reproducible.
    """

    async def embed(self, *, texts: list[str]) -> list[list[float]]:
        # Pretend we're hitting the network so async tests catch
        # missing-await mistakes.
        await asyncio.sleep(0)
        return [_deterministic_embedding(t) for t in texts]


def _deterministic_embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # 32 bytes → cycle into 1536 floats in [-1, 1).
    out: list[float] = []
    for i in range(EMBEDDING_DIM):
        byte = digest[i % len(digest)]
        # Mix the index in so we don't end up with 48 identical 32-cycles.
        scrambled = (byte ^ (i * 31 & 0xFF)) & 0xFF
        out.append((scrambled - 128) / 128.0)
    return out
