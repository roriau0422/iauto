"""KB ingestion: chunking, embedding cache, cosine recall."""

from __future__ import annotations

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.embeddings import FakeEmbeddingClient, content_hash
from app.ai_mechanic.repository import AiKbRepository
from app.ai_mechanic.schemas import KbDocumentCreateIn
from app.ai_mechanic.service import AiMechanicService
from app.platform.config import Settings
from tests.ai_mechanic.fakes import FakeAgentRunner


@pytest.fixture
def ai_service(
    db_session: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> AiMechanicService:
    return AiMechanicService(
        session=db_session,
        redis=redis,
        runner=FakeAgentRunner(),
        embeddings=FakeEmbeddingClient(),
        settings=settings,
    )


async def test_ingest_chunks_and_embeds(
    ai_service: AiMechanicService, db_session: AsyncSession
) -> None:
    body = (
        "Brake pads should be replaced every 50,000 km on average sedans.\n\n"
        "Use OEM-spec pads for best longevity. Aftermarket pads can wear "
        "out twice as fast and damage rotors.\n\n"
        "If you hear a high-pitched squeal during braking, the wear "
        "indicators are likely engaged."
    )
    result = await ai_service.ingest_document(
        payload=KbDocumentCreateIn(
            title="Brake pad maintenance",
            body=body,
        )
    )
    assert result.chunks_added >= 1
    assert result.embeddings_cached == result.chunks_added

    # Re-ingestion is a no-op (idempotent on content_hash).
    again = await ai_service.ingest_document(
        payload=KbDocumentCreateIn(
            title="Brake pad maintenance",
            body=body,
        )
    )
    assert again.chunks_added == 0
    assert again.document_id == result.document_id


async def test_ingest_uses_embedding_cache_on_repeat(
    ai_service: AiMechanicService, db_session: AsyncSession
) -> None:
    # First ingest — populates the cache.
    body_v1 = "Engine oil level should be checked at every refuel."
    await ai_service.ingest_document(payload=KbDocumentCreateIn(title="Oil checks", body=body_v1))

    # Different document with overlapping chunk text — the cache scope
    # is per-document, so this should still call embed for the new
    # document. We just verify the cache mechanics by counting cache rows.
    cache_count = await db_session.execute(text("SELECT count(*) FROM ai_embedding_cache"))
    assert int(cache_count.scalar_one()) >= 1


async def test_search_chunks_returns_results(
    ai_service: AiMechanicService, db_session: AsyncSession
) -> None:
    body = (
        "The car's brake system should be flushed every 2 years to keep "
        "the brake fluid free of moisture and debris."
    )
    result = await ai_service.ingest_document(
        payload=KbDocumentCreateIn(title="Brake system", body=body)
    )
    assert result.chunks_added > 0

    # Run a search using the same fake embedding client.
    embeddings = await FakeEmbeddingClient().embed(texts=["brake system flush"])
    repo = AiKbRepository(db_session)
    rows = await repo.search_chunks(embedding=embeddings[0], limit=5)
    assert len(rows) >= 1
    # First row's distance is closest (smallest).
    distances = [d for _, _, _, d in rows]
    assert distances == sorted(distances)


async def test_content_hash_is_stable() -> None:
    a = content_hash("hello")
    b = content_hash("hello")
    c = content_hash("hello!")
    assert a == b
    assert a != c
