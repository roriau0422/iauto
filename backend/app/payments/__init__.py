"""Payments context — QPay v2 integration + double-entry ledger.

Per ARCHITECTURE.md decision 13: QPay is the only payment rail. All money
flows through this context; other contexts react to `payment_settled`
events, never to QPay directly.
"""
