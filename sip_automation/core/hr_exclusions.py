from __future__ import annotations

from pathlib import Path

import yaml


class HRExclusionsStore:
    """Persist HR-reconciliation excluded employee IDs to a YAML file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def load(self) -> list[str]:
        """Return the current list of excluded employee IDs (may be empty)."""
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                content = yaml.safe_load(fh) or {}
            return [str(v) for v in content.get("excluded_employee_ids", [])]
        except Exception:
            return []

    def save(self, employee_ids: list[str]) -> None:
        """Atomically overwrite the exclusion list."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                {"excluded_employee_ids": [str(i) for i in employee_ids]},
                fh,
                sort_keys=False,
                default_flow_style=False,
            )
        tmp.replace(self.path)
