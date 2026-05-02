"""Phase 5 session 21 — index + autovacuum hardening assertions.

These run as integration tests against the test DB. They lock down
schema invariants that aren't visible from the ORM definitions:

* HNSW index on `ai_kb_chunks.embedding` exists with cosine ops.
* Compound `(tenant_id, created_at DESC)` index on `quotes` exists
  so the marketplace pagination query is index-only.
* Autovacuum reloptions are tuned tighter than the cluster default
  on the high-churn tables.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _index_definition(session: AsyncSession, indexname: str) -> str | None:
    row = await session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
        {"n": indexname},
    )
    out = row.scalar_one_or_none()
    return str(out) if out else None


@pytest.mark.asyncio
async def test_hnsw_index_on_ai_kb_chunks_embedding(db_session: AsyncSession) -> None:
    indexdef = await _index_definition(db_session, "ix_ai_kb_chunks_embedding_hnsw")
    assert indexdef is not None
    # Must use HNSW + cosine ops (matches the runtime <=> query operator).
    assert "USING hnsw" in indexdef
    assert "vector_cosine_ops" in indexdef


@pytest.mark.asyncio
async def test_quotes_pagination_index(db_session: AsyncSession) -> None:
    indexdef = await _index_definition(db_session, "ix_quotes_tenant_id_created_at")
    assert indexdef is not None
    assert "tenant_id" in indexdef
    # `created_at DESC` makes the LIMIT/ORDER BY index-only — must
    # actually be DESC, not ASC.
    assert "created_at DESC" in indexdef


@pytest.mark.asyncio
async def test_high_churn_tables_have_tightened_autovacuum(
    db_session: AsyncSession,
) -> None:
    """`pg_class.reloptions` is `text[]` of `key=value` strings. Each
    high-churn table should override at least the vacuum scale factor.
    """
    rows = await db_session.execute(
        text(
            """
            SELECT relname, COALESCE(array_to_string(reloptions, ','), '') AS opts
            FROM pg_class
            WHERE relname IN (
                'outbox_events', 'ai_messages', 'ai_spend_events', 'chat_messages'
            )
            """
        )
    )
    tightened = {row[0]: row[1] for row in rows.all()}

    # All four tables must have at least one autovacuum override applied.
    for table in ("outbox_events", "ai_messages", "ai_spend_events", "chat_messages"):
        opts = tightened.get(table, "")
        assert "autovacuum_vacuum_scale_factor" in opts, (
            f"{table} missing tighter autovacuum override; got reloptions={opts!r}"
        )

    # Outbox is tightest — 1% threshold.
    assert "autovacuum_vacuum_scale_factor=0.01" in tightened["outbox_events"]
