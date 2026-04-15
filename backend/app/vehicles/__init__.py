"""Vehicles context.

The *physical* car is the aggregate root (one row per VIN). Users are linked
to vehicles through a many-to-many pivot (`vehicle_ownerships`) so the same
car can be owned by more than one user (e.g. family members, dealer + driver,
business + employee) and one user can own many cars.

ARCHITECTURE note: the backend **does not** call smartcar.mn / XYP itself.
The mobile client runs the lookup on-device using a versioned plan served by
`GET /v1/vehicles/lookup/plan`. Error reporting and the operator SMS pager
live inside this context. See `docs/ARCHITECTURE.md §3.7` for the older
server-side story which is retained only for future direct-XYP access.
"""
