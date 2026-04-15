"""HTTP surface.

Version-prefixed routers aggregate under `app.api.v{N}`. New versions live
side-by-side while the old contract is still supported — breaking changes run
/v1/ and /v2/ in parallel for at least 90 days after the /v2/-capable mobile
build reaches production (ARCHITECTURE.md §9).
"""
