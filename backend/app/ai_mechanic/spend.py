"""Token + audio-second cost estimation.

The cost table is rough and hand-curated for Phase 3 dogfooding —
prices below are placeholders denominated in micro-MNT. Phase 5 swaps
to a config-driven table fed from the provider's billing API once we
have multi-vendor routing.

Source-of-truth pricing (May 2026, MNT-pegged):
  - gemini-3-flash-preview: ~50 micro-MNT / 1000 prompt tokens, ~150 / 1000 completion
  - text-embedding-3-small: ~1 micro-MNT / 1000 tokens
  - whisper-1: ~333 micro-MNT / audio second (i.e. ~20 MNT / minute)
"""

from __future__ import annotations

# Prices in micro-MNT (1 MNT = 1_000_000 micro). Estimated; do NOT use
# these for invoicing. The phase-5 cost-alert cron sums these into a
# daily-spend metric and triggers a Slack page when it crosses
# AI_DAILY_SPEND_BUDGET_MICRO_MNT (env, not implemented this session).
_PRICE_MICRO_MNT_PER_1K_TOKENS: dict[str, tuple[int, int]] = {
    # (prompt, completion)
    "gemini/gemini-3-flash-preview": (50, 150),
    "gemini-3-flash-preview": (50, 150),
    "gemini-multimodal-visual": (60, 180),
    "text-embedding-3-small": (1, 0),
}

# Audio-second pricing for transcription / multimodal-audio models.
# Whisper bills per minute; we record per-second to keep the granular
# spend log honest. Gemini's audio multimodal is roughly 2× Whisper at
# May 2026 rates.
_PRICE_MICRO_MNT_PER_AUDIO_SECOND: dict[str, int] = {
    "whisper-1": 333,
    "gemini-multimodal-audio": 700,
}


def estimate_cost_micro_mnt(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    audio_seconds: int = 0,
) -> int:
    """Best-effort cost estimate in micro-MNT.

    Audio-priced models bill on `audio_seconds`; everything else falls
    through to the per-1K-token rate. Unknown models return 0 — the
    spend log still records the raw counts so the cost-alert cron can
    flag surprises.
    """
    audio_rate = _PRICE_MICRO_MNT_PER_AUDIO_SECOND.get(model)
    if audio_rate is not None:
        return audio_seconds * audio_rate
    rates = _PRICE_MICRO_MNT_PER_1K_TOKENS.get(model)
    if rates is None:
        return 0
    prompt_rate, completion_rate = rates
    prompt_cost = (prompt_tokens * prompt_rate) // 1000
    completion_cost = (completion_tokens * completion_rate) // 1000
    return prompt_cost + completion_cost
