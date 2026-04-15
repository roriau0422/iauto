"""baseline: extensions, outbox_events, partitioned events_archive.

Revision ID: 0001
Revises:
Create Date: 2026-04-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # -- 1. Extensions -------------------------------------------------------
    # Idempotent on dev (docker init SQL already ran them) but required for
    # fresh prod databases.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # -- 2. outbox_events ----------------------------------------------------
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
    )
    # Consumer scan: pending events ordered by occurred_at. Partial index
    # keeps it tiny — dispatched rows (by far the majority over time) are
    # excluded from the b-tree.
    op.execute(
        "CREATE INDEX ix_outbox_events_pending "
        "ON outbox_events (occurred_at) "
        "WHERE dispatched_at IS NULL"
    )
    op.create_index(
        "ix_outbox_events_aggregate",
        "outbox_events",
        ["aggregate_type", "aggregate_id"],
    )

    # -- 3. events_archive (partitioned) -------------------------------------
    op.execute(
        """
        CREATE TABLE events_archive (
            id uuid NOT NULL,
            event_type text NOT NULL,
            aggregate_type text NOT NULL,
            aggregate_id uuid NOT NULL,
            tenant_id uuid NULL,
            payload jsonb NOT NULL,
            occurred_at timestamptz NOT NULL,
            archived_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (occurred_at, id)
        ) PARTITION BY RANGE (occurred_at)
        """
    )
    op.execute(
        "CREATE INDEX ix_events_archive_event_type_occurred_at "
        "ON events_archive (event_type, occurred_at)"
    )
    op.execute(
        "CREATE INDEX ix_events_archive_aggregate "
        "ON events_archive (aggregate_type, aggregate_id)"
    )
    op.execute(
        "CREATE INDEX ix_events_archive_tenant_id "
        "ON events_archive (tenant_id) WHERE tenant_id IS NOT NULL"
    )

    # -- 4. Monthly partition helper -----------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION create_events_archive_partition(
            p_year int, p_month int
        ) RETURNS void AS $$
        DECLARE
            partition_name text;
            start_date date;
            end_date date;
        BEGIN
            partition_name := format(
                'events_archive_%s_%s',
                p_year,
                lpad(p_month::text, 2, '0')
            );
            start_date := make_date(p_year, p_month, 1);
            end_date := (start_date + interval '1 month')::date;
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF events_archive '
                'FOR VALUES FROM (%L) TO (%L)',
                partition_name, start_date, end_date
            );
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # -- 5. Seed current + next month --------------------------------------
    op.execute(
        "SELECT create_events_archive_partition("
        "   extract(year from now())::int, "
        "   extract(month from now())::int)"
    )
    op.execute(
        "SELECT create_events_archive_partition("
        "   extract(year from (now() + interval '1 month'))::int, "
        "   extract(month from (now() + interval '1 month'))::int)"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS create_events_archive_partition(int, int)")
    op.execute("DROP TABLE IF EXISTS events_archive CASCADE")
    op.drop_index("ix_outbox_events_aggregate", table_name="outbox_events")
    op.execute("DROP INDEX IF EXISTS ix_outbox_events_pending")
    op.drop_table("outbox_events")
    # Extensions are intentionally left in place on downgrade — they may have
    # been created outside of this migration and other schemas may depend on
    # them.
