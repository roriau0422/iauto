"""Token cost estimation + spend logging.

The cost table is rough and hand-curated for Phase 3 dogfooding —
prices below are placeholders denominated in micro-MNT per 1000 tokens.
Phase 5 swaps to a config-driven table fed from the provider's billing
API once we have multi-vendor routing.

Source-of-truth pricing (May 2026, MNT-pegged):
  - gemini-3-flash-preview: ~50 micro-MNT / 1000 prompt tokens, ~150 / 1000 completion
  - text-embedding-3-small: ~1 micro-MNT / 1000 tokens
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
    "text-embedding-3-small": (1, 0),
}


def estimate_cost_micro_mnt(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    """Best-effort cost estimate in micro-MNT.

    Unknown models default to 0; the spend log still records the token
    counts so the cost-alert cron can flag surprises.
    """
    rates = _PRICE_MICRO_MNT_PER_1K_TOKENS.get(model)
    if rates is None:
        return 0
    prompt_rate, completion_rate = rates
    prompt_cost = (prompt_tokens * prompt_rate) // 1000
    completion_cost = (completion_tokens * completion_rate) // 1000
    return prompt_cost + completion_cost
