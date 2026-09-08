from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class UploadedFiles:
    """
    Runtime uploaded source files.

    Keys are logical table names (employee, bp, sales, etc.).
    """

    files: dict[str, Path] = field(default_factory=dict)

    def get_file(
        self,
        logical_table_name: str,
    ) -> Path | None:
        path = self.files.get(logical_table_name)

        if path is None:
            return None

        return Path(path).expanduser().resolve()

    @property
    def is_empty(self) -> bool:
        return not bool(self.files)