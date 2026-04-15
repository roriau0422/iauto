"""Businesses context — profiles for role=business users.

A `Business` row is the tenant boundary for every tenant-scoped table that
will land in subsequent phase-1 and phase-2 sessions (quotes, warehouse
items, stories, ads, ...). `businesses.id` is the `tenant_id` those tables
carry. Session 4 ships the profile CRUD only; vehicle-category coverage
arrives in session 5 with the marketplace incoming feed.
"""
