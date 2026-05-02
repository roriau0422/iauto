"""Notifications context — push delivery via FCM/APNs (mocked in dev).

Subscribes to outbox events from other contexts (payments, marketplace,
vehicles) and emits push notifications. Provider-agnostic at the
service layer; concrete providers live under `providers/`.
"""
