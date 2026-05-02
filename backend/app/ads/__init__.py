"""Ads context — self-served paid campaigns billed via QPay.

Per spec section 13. A business creates a campaign + payment intent in
one shot; QPay settlement triggers `ads.campaign_activated` via the
outbox handler. CPM-based billing: each impression debits
`(cpm_mnt / 1000)` MNT against the budget. When `spent_mnt >=
budget_mnt`, the campaign auto-flips to `exhausted`.
"""
