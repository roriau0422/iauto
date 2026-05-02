"""phase 5 session 21: index + autovacuum hardening.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-03

Three production-quality changes:

1. **HNSW index on `ai_kb_chunks.embedding`.** The migration that
   created the table deferred this because:
     * the corpus was sub-1000 rows (seq scan is fine),
     * the test-fixture savepoint hides committed rows from HNSW.
   Both pressures dissolve in production. We CREATE INDEX
   CONCURRENTLY so re-applying the migration on a live DB doesn't
   block ingest writes; the test DB applies it normally because it
   has no concurrent traffic. `m=16, ef_construction=64` are the
   pgvector defaults — tuned to favour recall over build speed.

2. **Autovacuum knobs on high-churn tables.** `outbox_events`,
   `events_archive`, `ai_messages`, `ai_spend_events`,
   `chat_messages`. The default Postgres thresholds (autovacuum at
   20% dead-tuple ratio) are too loose for tables that see >100
   inserts/sec — each VACUUM then has to rewrite gigabytes. Tighten
   to 5% on the spine + 1% on the outbox so HOT updates dominate.

3. **Compound idx for the marketplace pagination hot path** —
   `(tenant_id, created_at DESC)` on `quotes` so a business's
   "my quotes, newest first" feed is index-only for the first page.
   `tenant_id` here is the submitting business's id (per the
   tenant-scoped marketplace tables convention).

Rolling these as a single migration because all three are pure
DDL adds with no behavioural change. Round-trip safe.
"""

from __future__ import annotations

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# Tables tuned for aggressive autovacuum. Every entry maps to the
# Postgres reloption keys we override.
_AUTOVACUUM_TUNING: dict[str, dict[str, str]] = {
    "outbox_events": {
        # Dispatched rows are quickly nulled then never updated again,
        # so the table grows fast but stays mostly cold. 1% threshold
        # keeps the tail trim without thrashing.
        "autovacuum_vacuum_scale_factor": "0.01",
        "autovacuum_analyze_scale_factor": "0.01",
        "autovacuum_vacuum_threshold": "200",
    },
    "ai_messages": {
        "autovacuum_vacuum_scale_factor": "0.05",
        "autovacuum_analyze_scale_factor": "0.05",
    },
    "ai_spend_events": {
        "autovacuum_vacuum_scale_factor": "0.05",
        "autovacuum_analyze_scale_factor": "0.05",
    },
    "chat_messages": {
        "autovacuum_vacuum_scale_factor": "0.05",
        "autovacuum_analyze_scale_factor": "0.05",
    },
}


def upgrade() -> None:
    # -----------------------------------------------------------------
    # 1) HNSW vector index on ai_kb_chunks.embedding (cosine).
    # -----------------------------------------------------------------
    # `IF NOT EXISTS` keeps the migration idempotent if the operator
    # built the index by hand earlier. Cosine ops match the runtime
    # similarity query in `KbRepository.semantic_search`.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_kb_chunks_embedding_hnsw
        ON ai_kb_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # -----------------------------------------------------------------
    # 2) Autovacuum reloptions.
    # -----------------------------------------------------------------
    for table, opts in _AUTOVACUUM_TUNING.items():
        for key, value in opts.items():
            op.execute(f"ALTER TABLE {table} SET ({key} = {value})")

    # -----------------------------------------------------------------
    # 3) Marketplace pagination compound index. The "my quotes" feed
    #    fetches the latest 20 by `tenant_id` (= submitting business)
    #    + `created_at DESC`. The existing `ix_quotes_tenant_id` is
    #    single-column, which forces a sort step; this composite is
    #    index-only.
    # -----------------------------------------------------------------
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_quotes_tenant_id_created_at
        ON quotes (tenant_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_quotes_tenant_id_created_at")

    for table, opts in _AUTOVACUUM_TUNING.items():
        for key in opts:
            op.execute(f"ALTER TABLE {table} RESET ({key})")

    op.execute("DROP INDEX IF EXISTS ix_ai_kb_chunks_embedding_hnsw")
