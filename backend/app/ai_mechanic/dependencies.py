"""FastAPI dependencies for the AI Mechanic context."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.agent import AgentRunner, build_live_runner
from app.ai_mechanic.embeddings import EmbeddingClient, OpenAIEmbeddingClient
from app.ai_mechanic.service import AiMechanicService
from app.ai_mechanic.whisper import OpenAIWhisperClient, WhisperClient
from app.media.client import MediaClient, S3MediaClient
from app.platform.cache import get_redis
from app.platform.config import Settings, get_settings
from app.platform.db import get_session


@lru_cache(maxsize=1)
def _build_runner_singleton() -> AgentRunner:
    """One process-wide live agent runner.

    The Agents SDK + LiteLLM client are heavy to construct — the
    LRU cache keeps the constructor cost off the request path.
    Tests substitute via `dependency_overrides[get_agent_runner]`.
    """
    return build_live_runner(settings=get_settings())


def get_agent_runner() -> AgentRunner:
    return _build_runner_singleton()


@lru_cache(maxsize=1)
def _build_embedding_client_singleton() -> EmbeddingClient:
    return OpenAIEmbeddingClient(settings=get_settings())


def get_embedding_client() -> EmbeddingClient:
    return _build_embedding_client_singleton()


@lru_cache(maxsize=1)
def _build_whisper_client_singleton() -> WhisperClient:
    return OpenAIWhisperClient(settings=get_settings())


def get_whisper_client() -> WhisperClient:
    return _build_whisper_client_singleton()


@lru_cache(maxsize=1)
def _build_media_client_singleton() -> MediaClient:
    return S3MediaClient(get_settings())


def get_media_download_client() -> MediaClient:
    return _build_media_client_singleton()


def get_redis_dep() -> Redis:
    return get_redis()


def get_ai_mechanic_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis_dep)],
    runner: Annotated[AgentRunner, Depends(get_agent_runner)],
    embeddings: Annotated[EmbeddingClient, Depends(get_embedding_client)],
    whisper: Annotated[WhisperClient, Depends(get_whisper_client)],
    media_download: Annotated[MediaClient, Depends(get_media_download_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AiMechanicService:
    return AiMechanicService(
        session=session,
        redis=redis,
        runner=runner,
        embeddings=embeddings,
        whisper=whisper,
        media_download=media_download,
        settings=settings,
    )
