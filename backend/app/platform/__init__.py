"""Shared infrastructure that every bounded context depends on.

Contents of this package are not domain-specific. They host database session
plumbing, configuration, logging, error types, the outbox, and the ID
generator. Nothing here may import from a bounded context.
"""
