"""SQLAlchemy declarative base and common column mixins.

Every model in the backend inherits from `Base`. Timestamp columns are applied
via the `Timestamped` mixin. Tenant-scoped tables additionally carry a
`tenant_id` column — tenant filtering is enforced at the repository layer, not
in the database, per ARCHITECTURE.md decision 10.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.platform.ids import new_id

# Naming convention keeps Alembic autogenerate migrations stable across
# machines and avoids the need to manually rename constraints.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UuidPrimaryKey:
    """Mixin giving a model a UUID primary key generated in Python."""

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=new_id,
    )


class Timestamped:
    """Mixin giving a model created_at / updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantScoped:
    """Mixin marking a table as tenant-scoped.

    Presence of this mixin is the contract used by the repository-layer lint:
    any repository method that queries a `TenantScoped` table must accept a
    `tenant_id` argument. Enforcement ships with the first tenant-scoped table
    (warehouse).
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
