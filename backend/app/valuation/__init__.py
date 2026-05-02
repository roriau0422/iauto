"""Car valuation context (Phase 4).

CatBoost-trained regressor over our own marketplace `sales` data plus
catalog/vehicle features. The hot path serves predictions via
`POST /v1/valuation/estimate`; a daily Arq cron retrains.
"""
