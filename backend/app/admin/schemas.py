"""HTTP schemas for the admin context."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class SpendByModelOut(BaseModel):
    model: str
    prompt_tokens: int
    completion_tokens: int
    audio_seconds: int
    micro_mnt: int


class SpendByUserOut(BaseModel):
    user_id: uuid.UUID
    requests: int
    micro_mnt: int


class SpendReportOut(BaseModel):
    """Trailing-window AI spend report.

    `window_hours` is the number of hours covered (24, 168, ...).
    `total_micro_mnt` is the sum across every recorded event in the
    window. Per-model + top-user breakdowns help spot cost regressions
    quickly.
    """

    window_hours: int
    total_micro_mnt: int
    by_model: list[SpendByModelOut]
    top_users: list[SpendByUserOut]
