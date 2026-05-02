"""Chat context — driver↔business threads anchored on quotes.

Real-time delivery is via WebSocket + Redis Pub/Sub fan-out (so
multiple FastAPI instances stay in sync). REST endpoints handle
history, listing, and the slow path.
"""
