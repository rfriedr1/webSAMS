"""Generic JSON-backed storage for setup sections."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SetupStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return raw

    def save_all(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def get_section(self, section_key: str, default: Any) -> Any:
        payload = self.load_all()
        return payload.get(section_key, default)

    def set_section(self, section_key: str, value: Any) -> None:
        payload = self.load_all()
        payload[section_key] = value
        self.save_all(payload)
