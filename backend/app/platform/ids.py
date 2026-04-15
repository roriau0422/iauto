"""Primary-key generation.

Abstracted behind a function so we can swap to UUIDv7 later without touching
call-sites. Using uuid4 for now — random, collision-safe, well-supported.
"""

from __future__ import annotations

import uuid


def new_id() -> uuid.UUID:
    """Return a fresh UUID to be used as a primary key."""
    return uuid.uuid4()
