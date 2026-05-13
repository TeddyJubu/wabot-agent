from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .redaction import redact


class EventLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event_type: str, payload: dict[str, Any]) -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "type": event_type,
            "payload": redact(payload),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")

