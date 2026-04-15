"""ORM models for the catalog context."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.base import Base, Timestamped, UuidPrimaryKey


class VehicleCountry(UuidPrimaryKey, Timestamped, Base):
    """Country of origin for a vehicle brand (e.g. Japan, Germany).

    `code` is the ISO 3166-1 alpha-2 for machine use; `name_en` / `name_mn`
    are shown in UIs. `sort_order` drives the catalog listing so Japan sits
    above Italy — the Mongolian market is overwhelmingly Japanese.
    """

    __tablename__ = "vehicle_countries"

    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_mn: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")

    brands: Mapped[list[VehicleBrand]] = relationship(back_populates="country")


class VehicleBrand(UuidPrimaryKey, Timestamped, Base):
    """A car manufacturer (Toyota, Hyundai, Mercedes-Benz, …).

    `slug` is the lowercase ASCII form used for case-insensitive matching
    against XYP `markName` strings. The uniqueness is enforced at the DB
    level so the resolver can rely on it.
    """

    __tablename__ = "vehicle_brands"

    country_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicle_countries.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")

    country: Mapped[VehicleCountry] = relationship(back_populates="brands")
    models: Mapped[list[VehicleModel]] = relationship(back_populates="brand")


class VehicleModel(UuidPrimaryKey, Timestamped, Base):
    """A specific model within a brand (Prius, Land Cruiser, Accent, …).

    `slug` is unique *within a brand*; two different brands may share the
    same model slug. We enforce the composite uniqueness with a table-level
    `UniqueConstraint` rather than a column `unique=True` so that e.g.
    Mercedes "E-Class" and some other brand's "E" do not collide.
    """

    __tablename__ = "vehicle_models"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicle_brands.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")

    brand: Mapped[VehicleBrand] = relationship(back_populates="models")

    __table_args__ = (UniqueConstraint("brand_id", "slug", name="uq_vehicle_models_brand_id_slug"),)
