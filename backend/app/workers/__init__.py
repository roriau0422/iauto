"""Arq background workers.

Each worker is its own module with a `WorkerSettings` class that Arq picks up
via `arq app.workers.<name>.WorkerSettings`.
"""
