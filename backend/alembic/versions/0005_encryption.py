"""encryption: swap plaintext PII for Fernet + HMAC blind indexes.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-16

Columns changed (upgrade):

    users.phone                      → users.phone_cipher  bytea  NOT NULL
                                     → users.phone_search  text   NOT NULL UNIQUE

    vehicles.vin                     → vehicles.vin_cipher bytea  NULL
                                     → vehicles.vin_search text   NULL (partial UNIQUE)
    vehicles.plate                   → vehicles.plate_cipher bytea NOT NULL

Backfill runs in-process by importing `app.platform.crypto` and re-using the
exact `DataCipher` / `SearchIndex` classes that the running app uses, so that
rows written by the migration are byte-for-byte compatible with rows the app
writes after upgrade finishes.

Known gap: `vehicles.raw_xyp` (JSONB) still contains plaintext VIN and plate
inside the original XYP response blob. That column is NOT touched here —
encrypting JSONB is a separate project (key rotation would rewrite every
row, and the access pattern is "owner + admin" anyway). Tracked as a
follow-up; flagged explicitly in ARCHITECTURE.md.

Downgrade is symmetric and requires the same keys to still be configured.
If the operator has lost `APP_DATA_KEY`, downgrade will fail mid-backfill.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.identity.schemas import normalize_phone
from app.platform.crypto import get_cipher, get_search_index
from app.vehicles.models import normalize_vin

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    cipher = get_cipher()
    search = get_search_index()

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.add_column(
        "users",
        sa.Column("phone_cipher", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("phone_search", sa.Text(), nullable=True),
    )

    # Backfill every existing user. Normalize first so the hash we compute
    # here matches what the running app computes later.
    users = bind.execute(sa.text("SELECT id, phone FROM users")).all()
    for row in users:
        normalized = normalize_phone(row.phone)
        bind.execute(
            sa.text(
                "UPDATE users SET phone_cipher = :cipher, "
                "phone_search = :search WHERE id = :id"
            ).bindparams(
                cipher=cipher.encrypt(normalized),
                search=search.compute(normalized),
                id=row.id,
            )
        )

    op.alter_column("users", "phone_cipher", nullable=False)
    op.alter_column("users", "phone_search", nullable=False)
    op.create_unique_constraint(
        "uq_users_phone_search", "users", ["phone_search"]
    )
    op.drop_constraint("uq_users_phone", "users", type_="unique")
    op.drop_column("users", "phone")

    # ------------------------------------------------------------------
    # vehicles
    # ------------------------------------------------------------------
    op.add_column(
        "vehicles",
        sa.Column("vin_cipher", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "vehicles",
        sa.Column("vin_search", sa.Text(), nullable=True),
    )
    op.add_column(
        "vehicles",
        sa.Column("plate_cipher", sa.LargeBinary(), nullable=True),
    )

    vehicles = bind.execute(
        sa.text("SELECT id, vin, plate FROM vehicles")
    ).all()
    for row in vehicles:
        # Plate is always required — encrypt directly.
        plate_cipher_bytes = cipher.encrypt(row.plate)

        if row.vin is not None and row.vin.strip():
            normalized_vin = normalize_vin(row.vin)
            vin_cipher_bytes: bytes | None = cipher.encrypt(normalized_vin)
            vin_search_hex: str | None = search.compute(normalized_vin)
        else:
            vin_cipher_bytes = None
            vin_search_hex = None

        bind.execute(
            sa.text(
                "UPDATE vehicles SET vin_cipher = :vc, vin_search = :vs, "
                "plate_cipher = :pc WHERE id = :id"
            ).bindparams(
                vc=vin_cipher_bytes,
                vs=vin_search_hex,
                pc=plate_cipher_bytes,
                id=row.id,
            )
        )

    op.alter_column("vehicles", "plate_cipher", nullable=False)

    # Swap the uniqueness from plaintext VIN to the blind index.
    op.execute("DROP INDEX IF EXISTS uq_vehicles_vin")
    op.execute(
        "CREATE UNIQUE INDEX uq_vehicles_vin_search "
        "ON vehicles (vin_search) WHERE vin_search IS NOT NULL"
    )

    # The plaintext plate index is useless against ciphertext and its only
    # previous purpose was sort/filter — drop it rather than rebuild against
    # the encrypted column.
    op.drop_index("ix_vehicles_plate", table_name="vehicles")

    op.drop_column("vehicles", "vin")
    op.drop_column("vehicles", "plate")


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    bind = op.get_bind()
    cipher = get_cipher()

    # ------------------------------------------------------------------
    # vehicles
    # ------------------------------------------------------------------
    op.add_column(
        "vehicles",
        sa.Column("vin", sa.Text(), nullable=True),
    )
    op.add_column(
        "vehicles",
        sa.Column("plate", sa.Text(), nullable=True),
    )

    vehicles = bind.execute(
        sa.text("SELECT id, vin_cipher, plate_cipher FROM vehicles")
    ).all()
    for row in vehicles:
        plate_plain = cipher.decrypt(bytes(row.plate_cipher))
        vin_plain = (
            cipher.decrypt(bytes(row.vin_cipher))
            if row.vin_cipher is not None
            else None
        )
        bind.execute(
            sa.text(
                "UPDATE vehicles SET vin = :vin, plate = :plate "
                "WHERE id = :id"
            ).bindparams(vin=vin_plain, plate=plate_plain, id=row.id)
        )

    op.alter_column("vehicles", "plate", nullable=False)
    op.create_index("ix_vehicles_plate", "vehicles", ["plate"])
    op.execute("DROP INDEX IF EXISTS uq_vehicles_vin_search")
    op.execute(
        "CREATE UNIQUE INDEX uq_vehicles_vin "
        "ON vehicles (vin) WHERE vin IS NOT NULL"
    )

    op.drop_column("vehicles", "plate_cipher")
    op.drop_column("vehicles", "vin_search")
    op.drop_column("vehicles", "vin_cipher")

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.add_column(
        "users",
        sa.Column("phone", postgresql.CITEXT(), nullable=True),
    )

    users = bind.execute(
        sa.text("SELECT id, phone_cipher FROM users")
    ).all()
    for row in users:
        plain = cipher.decrypt(bytes(row.phone_cipher))
        bind.execute(
            sa.text("UPDATE users SET phone = :p WHERE id = :id").bindparams(
                p=plain, id=row.id
            )
        )

    op.alter_column("users", "phone", nullable=False)
    op.create_unique_constraint("uq_users_phone", "users", ["phone"])
    op.drop_constraint("uq_users_phone_search", "users", type_="unique")
    op.drop_column("users", "phone_search")
    op.drop_column("users", "phone_cipher")
