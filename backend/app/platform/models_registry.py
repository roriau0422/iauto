"""Single import point for every ORM model in the project.

Alembic's `env.py` imports this module so that `Base.metadata` contains every
table before autogenerate runs. Adding a new model? Import it here.
"""

from __future__ import annotations

# -- platform-owned tables (outbox, event archive) ---------------------------
# populated in a later commit

# -- identity ----------------------------------------------------------------
# populated in a later commit

__all__: list[str] = []
