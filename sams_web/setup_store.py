"""Generic JSON-backed storage for setup sections."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


#: Secret-free snapshot of the lab's settings, kept in git. The live file
#: (`SAMS_SETUP_DATA_FILE`) is *not* in git — it holds the SMTP password and
#: each server's own state — so a new installation starts from this seed
#: instead of from bare code defaults.
SEED_FILE = Path(__file__).resolve().parent / "setup_data.example.json"


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return raw if isinstance(raw, dict) else None


class SetupStore:
    def __init__(self, path: Path, seed_path: Path | None = SEED_FILE) -> None:
        self.path = path
        self.seed_path = seed_path

    def load_all(self) -> dict[str, Any]:
        if not self.path.exists():
            # Read-only fallback: nothing is written until the first save,
            # which then persists the seeded sections to the live file.
            if self.seed_path is not None and self.seed_path.exists():
                return _read_json_object(self.seed_path) or {}
            return {}
        return _read_json_object(self.path) or {}

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
