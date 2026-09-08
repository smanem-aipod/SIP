"""
File-backed pointer to the "current active run".

Lets the UI restore the last run's results even after a full browser
restart (not just within one sessionStorage-backed tab), by asking the
server "what is the current run?" instead of relying only on client-side
storage. The pointer only changes when a new run is actually created
(a fresh upload succeeds) or when a run's calculations complete - simply
navigating the UI (e.g. clicking "Start Over") does not touch it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

# current_run.py is located at:
#
# project_root/src/sip_automation/core/current_run.py
#
# parents[0] = core
# parents[1] = sip_automation
# parents[2] = src
# parents[3] = project root

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_CURRENT_RUN_PATH = (
    PROJECT_ROOT / "data" / "current_run.yaml"
)


@dataclass
class CurrentRun:
    run_id: str
    enabled_roles: list[str]
    role_row_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CurrentRunStore:
    """
    Single-record file-backed store for the current active run.

    There is intentionally only ever one record - this app has no
    per-user run isolation today (one shared login), so "the current
    run" is a single global pointer, consistent with the rest of the
    app's demo-level session model.
    """

    def __init__(
        self,
        *,
        path: Path = DEFAULT_CURRENT_RUN_PATH,
    ) -> None:
        self.path = path

    def get(self) -> CurrentRun | None:
        if not self.path.exists():
            return None

        with self.path.open(
            "r",
            encoding="utf-8",
        ) as stream:
            content = yaml.safe_load(stream) or {}

        run_id = content.get("run_id")

        if not run_id:
            return None

        return CurrentRun(
            run_id=str(run_id),
            enabled_roles=list(
                content.get("enabled_roles") or []
            ),
            role_row_counts=dict(
                content.get("role_row_counts") or {}
            ),
        )

    def set_run_id(
        self,
        run_id: str,
    ) -> None:
        """
        Called right after a new run is created (raw load succeeds).

        Resets enabled_roles/role_row_counts since they belong to the
        previous run's calculations stage, which hasn't happened yet
        for this new run.
        """

        self._write(
            CurrentRun(
                run_id=run_id,
                enabled_roles=[],
                role_row_counts={},
            )
        )

    def set_calculation_result(
        self,
        *,
        run_id: str,
        enabled_roles: list[str],
        role_row_counts: dict[str, int],
    ) -> None:
        """
        Called after calculations complete, so a restored session has
        the role list/counts needed to populate the results view without
        re-running anything.
        """

        self._write(
            CurrentRun(
                run_id=run_id,
                enabled_roles=list(enabled_roles),
                role_row_counts=dict(role_row_counts),
            )
        )

    def _write(
        self,
        current_run: CurrentRun,
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self.path.with_suffix(".tmp")

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as stream:
            yaml.safe_dump(
                current_run.to_dict(),
                stream,
                sort_keys=False,
                default_flow_style=False,
            )

        temporary_path.replace(self.path)
