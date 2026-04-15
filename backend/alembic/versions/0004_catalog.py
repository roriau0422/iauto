"""catalog: countries, brands, models + vehicles FK.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-15

Seed contents (curated, not exhaustive — the curator adds rows over time):

  Countries (sort_order keeps Japan first because the Mongolian used-car
  market is overwhelmingly Japanese right-hand drive imports):
    JP Japan · KR South Korea · DE Germany · US United States
    CN China · GB United Kingdom · SE Sweden · IT Italy

  Brands: 30 popular nameplates across those countries.
  Models: 60+ popular models — still small, sized to cover the ≥80% of
  plates we expect to see in alpha. Misses are logged and curated weekly.
"""

from __future__ import annotations

import uuid
from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


class CountrySeed(NamedTuple):
    code: str
    name_en: str
    name_mn: str
    sort_order: int


class BrandSeed(NamedTuple):
    country_code: str
    slug: str
    name: str
    sort_order: int


class ModelSeed(NamedTuple):
    brand_slug: str
    slug: str
    name: str
    sort_order: int


COUNTRIES: tuple[CountrySeed, ...] = (
    CountrySeed("JP", "Japan", "Япон", 10),
    CountrySeed("KR", "South Korea", "Өмнөд Солонгос", 20),
    CountrySeed("DE", "Germany", "Герман", 30),
    CountrySeed("US", "United States", "Америкийн Нэгдсэн Улс", 40),
    CountrySeed("CN", "China", "Хятад", 50),
    CountrySeed("GB", "United Kingdom", "Их Британи", 60),
    CountrySeed("SE", "Sweden", "Швед", 70),
    CountrySeed("IT", "Italy", "Итали", 80),
)

BRANDS: tuple[BrandSeed, ...] = (
    # Japan
    BrandSeed("JP", "toyota", "Toyota", 10),
    BrandSeed("JP", "lexus", "Lexus", 20),
    BrandSeed("JP", "nissan", "Nissan", 30),
    BrandSeed("JP", "honda", "Honda", 40),
    BrandSeed("JP", "mazda", "Mazda", 50),
    BrandSeed("JP", "subaru", "Subaru", 60),
    BrandSeed("JP", "mitsubishi", "Mitsubishi", 70),
    BrandSeed("JP", "suzuki", "Suzuki", 80),
    BrandSeed("JP", "isuzu", "Isuzu", 90),
    BrandSeed("JP", "daihatsu", "Daihatsu", 100),
    # Korea
    BrandSeed("KR", "hyundai", "Hyundai", 10),
    BrandSeed("KR", "kia", "Kia", 20),
    BrandSeed("KR", "genesis", "Genesis", 30),
    BrandSeed("KR", "ssangyong", "SsangYong", 40),
    # Germany
    BrandSeed("DE", "mercedesbenz", "Mercedes-Benz", 10),
    BrandSeed("DE", "bmw", "BMW", 20),
    BrandSeed("DE", "audi", "Audi", 30),
    BrandSeed("DE", "volkswagen", "Volkswagen", 40),
    BrandSeed("DE", "porsche", "Porsche", 50),
    BrandSeed("DE", "opel", "Opel", 60),
    # USA
    BrandSeed("US", "ford", "Ford", 10),
    BrandSeed("US", "chevrolet", "Chevrolet", 20),
    BrandSeed("US", "jeep", "Jeep", 30),
    BrandSeed("US", "tesla", "Tesla", 40),
    BrandSeed("US", "cadillac", "Cadillac", 50),
    # China
    BrandSeed("CN", "byd", "BYD", 10),
    BrandSeed("CN", "geely", "Geely", 20),
    BrandSeed("CN", "haval", "Haval", 30),
    # UK
    BrandSeed("GB", "landrover", "Land Rover", 10),
    # Sweden
    BrandSeed("SE", "volvo", "Volvo", 10),
)

MODELS: tuple[ModelSeed, ...] = (
    # Toyota — dominates the alpha market, so it's big.
    ModelSeed("toyota", "prius", "Prius", 10),
    ModelSeed("toyota", "prius20", "Prius 20", 11),
    ModelSeed("toyota", "prius30", "Prius 30", 12),
    ModelSeed("toyota", "prius50", "Prius 50", 13),
    ModelSeed("toyota", "landcruiser", "Land Cruiser", 20),
    ModelSeed("toyota", "landcruiserprado", "Land Cruiser Prado", 21),
    ModelSeed("toyota", "camry", "Camry", 30),
    ModelSeed("toyota", "corolla", "Corolla", 40),
    ModelSeed("toyota", "rav4", "RAV4", 50),
    ModelSeed("toyota", "highlander", "Highlander", 60),
    ModelSeed("toyota", "hilux", "Hilux", 70),
    ModelSeed("toyota", "alphard", "Alphard", 80),
    ModelSeed("toyota", "vellfire", "Vellfire", 90),
    ModelSeed("toyota", "sienna", "Sienna", 100),
    ModelSeed("toyota", "harrier", "Harrier", 110),
    ModelSeed("toyota", "estima", "Estima", 120),
    ModelSeed("toyota", "crown", "Crown", 130),
    # Lexus
    ModelSeed("lexus", "rx", "RX", 10),
    ModelSeed("lexus", "lx", "LX", 20),
    ModelSeed("lexus", "gx", "GX", 30),
    ModelSeed("lexus", "es", "ES", 40),
    ModelSeed("lexus", "ls", "LS", 50),
    ModelSeed("lexus", "nx", "NX", 60),
    # Nissan
    ModelSeed("nissan", "xtrail", "X-Trail", 10),
    ModelSeed("nissan", "patrol", "Patrol", 20),
    ModelSeed("nissan", "qashqai", "Qashqai", 30),
    ModelSeed("nissan", "sunny", "Sunny", 40),
    ModelSeed("nissan", "leaf", "Leaf", 50),
    # Honda
    ModelSeed("honda", "crv", "CR-V", 10),
    ModelSeed("honda", "civic", "Civic", 20),
    ModelSeed("honda", "accord", "Accord", 30),
    ModelSeed("honda", "fit", "Fit", 40),
    # Mazda
    ModelSeed("mazda", "cx5", "CX-5", 10),
    ModelSeed("mazda", "cx9", "CX-9", 20),
    ModelSeed("mazda", "mazda6", "Mazda6", 30),
    # Subaru
    ModelSeed("subaru", "forester", "Forester", 10),
    ModelSeed("subaru", "outback", "Outback", 20),
    # Mitsubishi
    ModelSeed("mitsubishi", "outlander", "Outlander", 10),
    ModelSeed("mitsubishi", "pajero", "Pajero", 20),
    ModelSeed("mitsubishi", "delica", "Delica", 30),
    # Hyundai
    ModelSeed("hyundai", "sonata", "Sonata", 10),
    ModelSeed("hyundai", "elantra", "Elantra", 20),
    ModelSeed("hyundai", "accent", "Accent", 30),
    ModelSeed("hyundai", "tucson", "Tucson", 40),
    ModelSeed("hyundai", "santafe", "Santa Fe", 50),
    ModelSeed("hyundai", "ioniq", "Ioniq", 60),
    # Kia
    ModelSeed("kia", "sorento", "Sorento", 10),
    ModelSeed("kia", "sportage", "Sportage", 20),
    ModelSeed("kia", "k5", "K5", 30),
    ModelSeed("kia", "morning", "Morning", 40),
    # Mercedes-Benz
    ModelSeed("mercedesbenz", "cclass", "C-Class", 10),
    ModelSeed("mercedesbenz", "eclass", "E-Class", 20),
    ModelSeed("mercedesbenz", "sclass", "S-Class", 30),
    ModelSeed("mercedesbenz", "gclass", "G-Class", 40),
    ModelSeed("mercedesbenz", "glc", "GLC", 50),
    ModelSeed("mercedesbenz", "gle", "GLE", 60),
    # BMW
    ModelSeed("bmw", "3series", "3 Series", 10),
    ModelSeed("bmw", "5series", "5 Series", 20),
    ModelSeed("bmw", "7series", "7 Series", 30),
    ModelSeed("bmw", "x3", "X3", 40),
    ModelSeed("bmw", "x5", "X5", 50),
    # Audi
    ModelSeed("audi", "a4", "A4", 10),
    ModelSeed("audi", "a6", "A6", 20),
    ModelSeed("audi", "q5", "Q5", 30),
    ModelSeed("audi", "q7", "Q7", 40),
    # Volkswagen
    ModelSeed("volkswagen", "tiguan", "Tiguan", 10),
    ModelSeed("volkswagen", "passat", "Passat", 20),
    ModelSeed("volkswagen", "golf", "Golf", 30),
    # Ford
    ModelSeed("ford", "ranger", "Ranger", 10),
    ModelSeed("ford", "explorer", "Explorer", 20),
    ModelSeed("ford", "escape", "Escape", 30),
    # Land Rover
    ModelSeed("landrover", "rangerover", "Range Rover", 10),
    ModelSeed("landrover", "discovery", "Discovery", 20),
    # Tesla
    ModelSeed("tesla", "model3", "Model 3", 10),
    ModelSeed("tesla", "modely", "Model Y", 20),
)


# ---------------------------------------------------------------------------
# Upgrade / downgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    op.create_table(
        "vehicle_countries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_mn", sa.Text(), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vehicle_countries"),
        sa.UniqueConstraint("code", name="uq_vehicle_countries_code"),
    )

    op.create_table(
        "vehicle_brands",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("country_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["country_id"],
            ["vehicle_countries.id"],
            name="fk_vehicle_brands_country_id_vehicle_countries",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vehicle_brands"),
        sa.UniqueConstraint("slug", name="uq_vehicle_brands_slug"),
    )
    op.create_index(
        "ix_vehicle_brands_country_id", "vehicle_brands", ["country_id"]
    )

    op.create_table(
        "vehicle_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["vehicle_brands.id"],
            name="fk_vehicle_models_brand_id_vehicle_brands",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vehicle_models"),
        sa.UniqueConstraint(
            "brand_id", "slug", name="uq_vehicle_models_brand_id_slug"
        ),
    )
    op.create_index(
        "ix_vehicle_models_brand_id", "vehicle_models", ["brand_id"]
    )

    # Additive nullable columns on vehicles — safe backfill. Existing rows
    # stay NULL; the catalog service populates future inserts.
    op.add_column(
        "vehicles",
        sa.Column(
            "vehicle_brand_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "vehicles",
        sa.Column(
            "vehicle_model_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_vehicles_vehicle_brand_id_vehicle_brands",
        "vehicles",
        "vehicle_brands",
        ["vehicle_brand_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_vehicles_vehicle_model_id_vehicle_models",
        "vehicles",
        "vehicle_models",
        ["vehicle_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_vehicles_vehicle_brand_id", "vehicles", ["vehicle_brand_id"]
    )
    op.create_index(
        "ix_vehicles_vehicle_model_id", "vehicles", ["vehicle_model_id"]
    )

    # ------------------------------------------------------------------
    # Seed data
    # ------------------------------------------------------------------
    country_table = sa.table(
        "vehicle_countries",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.Text()),
        sa.column("name_en", sa.Text()),
        sa.column("name_mn", sa.Text()),
        sa.column("sort_order", sa.Integer()),
    )
    brand_table = sa.table(
        "vehicle_brands",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("country_id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("sort_order", sa.Integer()),
    )
    model_table = sa.table(
        "vehicle_models",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("brand_id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("sort_order", sa.Integer()),
    )

    # Python-side UUIDs keep the migration deterministic per run and avoid
    # a server round-trip per row. The FK maps are built as we go so the
    # brand rows carry the correct country_id, etc.
    country_rows: list[dict[str, object]] = []
    country_id_by_code: dict[str, uuid.UUID] = {}
    for c in COUNTRIES:
        cid = uuid.uuid4()
        country_id_by_code[c.code] = cid
        country_rows.append(
            {
                "id": cid,
                "code": c.code,
                "name_en": c.name_en,
                "name_mn": c.name_mn,
                "sort_order": c.sort_order,
            }
        )
    op.bulk_insert(country_table, country_rows)

    brand_rows: list[dict[str, object]] = []
    brand_id_by_slug: dict[str, uuid.UUID] = {}
    for b in BRANDS:
        bid = uuid.uuid4()
        brand_id_by_slug[b.slug] = bid
        brand_rows.append(
            {
                "id": bid,
                "country_id": country_id_by_code[b.country_code],
                "slug": b.slug,
                "name": b.name,
                "sort_order": b.sort_order,
            }
        )
    op.bulk_insert(brand_table, brand_rows)

    model_rows: list[dict[str, object]] = [
        {
            "id": uuid.uuid4(),
            "brand_id": brand_id_by_slug[m.brand_slug],
            "slug": m.slug,
            "name": m.name,
            "sort_order": m.sort_order,
        }
        for m in MODELS
    ]
    op.bulk_insert(model_table, model_rows)


def downgrade() -> None:
    op.drop_index(
        "ix_vehicles_vehicle_model_id", table_name="vehicles"
    )
    op.drop_index(
        "ix_vehicles_vehicle_brand_id", table_name="vehicles"
    )
    op.drop_constraint(
        "fk_vehicles_vehicle_model_id_vehicle_models",
        "vehicles",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_vehicles_vehicle_brand_id_vehicle_brands",
        "vehicles",
        type_="foreignkey",
    )
    op.drop_column("vehicles", "vehicle_model_id")
    op.drop_column("vehicles", "vehicle_brand_id")

    op.drop_index("ix_vehicle_models_brand_id", table_name="vehicle_models")
    op.drop_table("vehicle_models")

    op.drop_index("ix_vehicle_brands_country_id", table_name="vehicle_brands")
    op.drop_table("vehicle_brands")

    op.drop_table("vehicle_countries")
