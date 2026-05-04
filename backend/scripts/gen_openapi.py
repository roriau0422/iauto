"""Regenerate the committed OpenAPI snapshot.

Writes `shared/openapi/v1.json` from the current FastAPI app — mobile codegen
(`openapi-typescript`) and CI drift detection read from that file, so it
must be regenerated whenever a route or response model changes.

Run:
    venv/Scripts/python.exe scripts/gen_openapi.py          # Windows
    python scripts/gen_openapi.py                           # Unix

Exits non-zero if the snapshot is stale (useful in CI).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

# Make Cyrillic-heavy output safe on Windows consoles.
for _stream in ("stdout", "stderr"):
    with contextlib.suppress(Exception):
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")

# Repository layout: backend/scripts/gen_openapi.py → shared/openapi/v1.json.
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO_ROOT = _BACKEND.parent
_SNAPSHOT_PATH = _REPO_ROOT / "shared" / "openapi" / "v1.json"


def build_spec() -> dict[str, object]:
    # Imported lazily so running with --help doesn't spin up settings.
    from app.main import create_app

    return create_app().openapi()


def render(spec: dict[str, object]) -> str:
    # Stable, deterministic output: keys sorted, ensure_ascii=False for
    # Cyrillic passthrough, trailing newline so git doesn't complain.
    return json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Exit non-zero if the snapshot would change. Use in CI to fail "
            "builds that forgot to regenerate it."
        ),
    )
    args = parser.parse_args()

    new_body = render(build_spec())

    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if args.check:
        if not _SNAPSHOT_PATH.exists():
            print(
                f"[check] missing snapshot: {_SNAPSHOT_PATH}",
                file=sys.stderr,
            )
            return 1
        current = _SNAPSHOT_PATH.read_text(encoding="utf-8")
        if current != new_body:
            print(
                "[check] OpenAPI snapshot is out of date. "
                "Run `python scripts/gen_openapi.py` and commit the diff.",
                file=sys.stderr,
            )
            return 1
        print("[check] snapshot is up to date")
        return 0

    _SNAPSHOT_PATH.write_text(new_body, encoding="utf-8")
    print(f"wrote {_SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
