"""Catalog context — canonical vehicle countries / brands / models.

A thin reference-data namespace that all other contexts can look up against.
Populated by migration 0004 with a hand-curated seed (countries of origin,
top-selling brands, popular models). Brand/model strings reported by the XYP
gateway are resolved case-insensitively against this catalog when a vehicle
row is created — unmatched strings are logged for weekly catalog curation.

The catalog is NOT tenant-scoped: every tenant sees the same taxonomy.
"""
