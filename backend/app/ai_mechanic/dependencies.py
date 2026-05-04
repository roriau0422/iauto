"""FastAPI dependencies for the AI Mechanic context."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.agent import AgentRunner, build_live_runner
from app.ai_mechanic.embeddings import EmbeddingClient, OpenAIEmbeddingClient
from app.ai_mechanic.multimodal import GeminiMultimodalClient, MultimodalClient
from app.ai_mechanic.service import AiMechanicService
from app.ai_mechanic.warning_lights import (
    HashHeuristicClassifier,
    WarningLightClassifier,
)
from app.ai_mechanic.whisper import OpenAIWhisperClient, WhisperClient
from app.media.client import MediaClient, S3MediaClient
from app.platform.cache import get_redis
from app.platform.config import Settings, get_settings
from app.platform.db import get_session


class _UnconfiguredRunner:
    """Stand-in runner used when GEMINI_API_KEY is missing.

    Read-only AI Mechanic endpoints (list sessions, list messages) have
    no business booting the LiteLLM agent — they get wired up the
    moment a route imports `get_ai_mechanic_service`. Defer the failure
    to actual `.run()` invocations so the dev environment can list
    sessions without a Gemini key set.
    """

    async def run(self, **_: object) -> object:
        raise RuntimeError("GEMINI_API_KEY is not configured — set it before posting messages.")


@lru_cache(maxsize=1)
def _build_runner_singleton() -> AgentRunner:
    """One process-wide live agent runner.

    The Agents SDK + LiteLLM client are heavy to construct — the
    LRU cache keeps the constructor cost off the request path.
    Tests substitute via `dependency_overrides[get_agent_runner]`.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        return _UnconfiguredRunner()  # type: ignore[return-value]
    return build_live_runner(settings=settings)


def get_agent_runner() -> AgentRunner:
    return _build_runner_singleton()


class _UnconfiguredAiClient:
    """Generic fallback for any AI client that requires an API key.

    The Pydantic `Settings` validation lets the server boot without
    Gemini/OpenAI keys (dev-friendly); construction of these clients
    raises eagerly. We swap in this stub so read-only endpoints can run
    and feature endpoints fail explicitly the moment they actually call
    out to the model.
    """

    def __init__(self, kind: str) -> None:
        self._kind = kind

    def __getattr__(self, name: str) -> object:
        async def _missing(*_: object, **__: object) -> object:
            raise RuntimeError(f"{self._kind} client unavailable — required API key is not set.")

        return _missing


@lru_cache(maxsize=1)
def _build_embedding_client_singleton() -> EmbeddingClient:
    settings = get_settings()
    if not (settings.openai_api_key or settings.gemini_api_key):
        return _UnconfiguredAiClient("embedding")  # type: ignore[return-value]
    return OpenAIEmbeddingClient(settings=settings)


def get_embedding_client() -> EmbeddingClient:
    return _build_embedding_client_singleton()


@lru_cache(maxsize=1)
def _build_whisper_client_singleton() -> WhisperClient:
    settings = get_settings()
    if not (settings.openai_api_key or settings.gemini_api_key):
        return _UnconfiguredAiClient("whisper")  # type: ignore[return-value]
    return OpenAIWhisperClient(settings=settings)


def get_whisper_client() -> WhisperClient:
    return _build_whisper_client_singleton()


@lru_cache(maxsize=1)
def _build_media_client_singleton() -> MediaClient:
    return S3MediaClient(get_settings())


def get_media_download_client() -> MediaClient:
    return _build_media_client_singleton()


@lru_cache(maxsize=1)
def _build_warning_light_classifier_singleton() -> WarningLightClassifier:
    """Phase 3 placeholder. Phase 5 swaps this for an ONNX-served MobileNet."""
    return HashHeuristicClassifier()


def get_warning_light_classifier() -> WarningLightClassifier:
    return _build_warning_light_classifier_singleton()


@lru_cache(maxsize=1)
def _build_multimodal_singleton() -> MultimodalClient:
    settings = get_settings()
    if not settings.gemini_api_key:
        return _UnconfiguredAiClient("multimodal")  # type: ignore[return-value]
    return GeminiMultimodalClient(settings=settings)


def get_multimodal_client() -> MultimodalClient:
    return _build_multimodal_singleton()


def get_redis_dep() -> Redis:
    return get_redis()


def get_ai_mechanic_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis_dep)],
    runner: Annotated[AgentRunner, Depends(get_agent_runner)],
    embeddings: Annotated[EmbeddingClient, Depends(get_embedding_client)],
    whisper: Annotated[WhisperClient, Depends(get_whisper_client)],
    media_download: Annotated[MediaClient, Depends(get_media_download_client)],
    classifier: Annotated[WarningLightClassifier, Depends(get_warning_light_classifier)],
    multimodal: Annotated[MultimodalClient, Depends(get_multimodal_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AiMechanicService:
    return AiMechanicService(
        session=session,
        redis=redis,
        runner=runner,
        embeddings=embeddings,
        whisper=whisper,
        media_download=media_download,
        warning_light_classifier=classifier,
        multimodal=multimodal,
        settings=settings,
    )
