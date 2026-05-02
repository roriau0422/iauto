"""Warehouse context — tenant-scoped inventory.

Each business owns a SKU catalog and an append-only ledger of stock
movements. `on_hand` for a SKU is the SUM of the ledger's
`signed_quantity` column — no separate stock balance row, so an
adjust/issue race can never desync from the ledger of truth.
"""
