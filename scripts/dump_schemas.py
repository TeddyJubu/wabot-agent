"""Dump JSON Schemas for the public Pydantic wire models.

Used to refresh ``tests/snapshots/*.schema.json`` when a model field changes.
The snapshot diff is the reviewable artifact in PRs — TS authors see the
shape change and update ``web/src/api/pairing.ts`` + the Vitest expected-keys
list in the same PR.

Usage:
    uv run python scripts/dump_schemas.py > tests/snapshots/pairing_payload.schema.json
"""

from __future__ import annotations

import json
import sys

from wabot_agent.schemas import PairingPayload


def main() -> None:
    json.dump(PairingPayload.model_json_schema(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
