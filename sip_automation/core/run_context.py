from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4
from sip_automation.core.uploaded_files import UploadedFiles
from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import RuntimeParameterError


@dataclass(frozen=True)
class RunContext:
    """
    Immutable context for one data-pipeline execution.

    The context is passed through loaders, repositories, processing steps,
    and logging. It prevents pipeline code from relying on global mutable
    runtime values.
    """

    run_id: UUID = field(default_factory=uuid4)

    initiated_by: str = "system"

    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    parameters: dict[str, Any] = field(
        default_factory=dict
    )
    uploaded_files: UploadedFiles | None = None

    @classmethod
    def from_config(
        cls,
        config: ConfigManager,
        *,
        initiated_by: str,
        overrides: dict[str, Any] | None = None,
        uploaded_files: UploadedFiles | None = None,
        run_id: UUID | None = None,
    ) -> "RunContext":
        """
        Create a run context from configured defaults and optional
        runtime overrides.

        Overrides take precedence over application.yaml defaults.
        """

        parameters = config.get_runtime_defaults()

        if overrides:
            parameters = cls._deep_merge(
                parameters,
                overrides,
            )

        return cls(
            run_id=run_id or uuid4(),
            initiated_by=initiated_by,
            parameters=parameters,
            uploaded_files=uploaded_files,
        )

    def get_parameter(
        self,
        dotted_path: str,
        default: Any = None,
        *,
        required: bool = False,
    ) -> Any:
        """
        Retrieve a runtime parameter using dotted-path syntax.

        Examples:
            fiscal_year
            record_source.employee
            record_source.sales
        """

        value = self._get_dotted_value(
            self.parameters,
            dotted_path,
            default=default,
        )

        if required and value is None:
            raise RuntimeParameterError(
                f"Required runtime parameter is unavailable: "
                f"{dotted_path!r}"
            )

        return value

    def with_parameters(
        self,
        overrides: dict[str, Any],
    ) -> "RunContext":
        """
        Return a new context with updated parameters.

        The existing context is not mutated.
        """

        merged_parameters = self._deep_merge(
            self.parameters,
            overrides,
        )

        return RunContext(
            run_id=self.run_id,
            initiated_by=self.initiated_by,
            started_at=self.started_at,
            parameters=merged_parameters,
            uploaded_files=self.uploaded_files,
        )

    @property
    def fiscal_year(self) -> int | None:
        value = self.get_parameter("fiscal_year")

        return int(value) if value is not None else None

    @property
    def effective_start_date(self) -> date:
        configured_value = self.get_parameter(
            "effective_start_date"
        )

        if configured_value is None:
            return self.started_at.date()

        if isinstance(configured_value, date):
            return configured_value

        return date.fromisoformat(
            str(configured_value)
        )

    def as_log_context(self) -> dict[str, Any]:
        """
        Return safe run metadata for structured logging.

        Business data and employee-specific information are excluded.
        """

        return {
            "run_id": str(self.run_id),
            "initiated_by": self.initiated_by,
            "started_at": self.started_at.isoformat(),
            "fiscal_year": self.fiscal_year,
        }

    @staticmethod
    def _get_dotted_value(
        data: dict[str, Any],
        dotted_path: str,
        *,
        default: Any = None,
    ) -> Any:
        current: Any = data

        for part in dotted_path.split("."):
            if not isinstance(current, dict):
                return default

            if part not in current:
                return default

            current = current[part]

        return current

    @classmethod
    def _deep_merge(
        cls,
        base: dict[str, Any],
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(base)

        for key, value in overrides.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = cls._deep_merge(
                    result[key],
                    value,
                )
            else:
                result[key] = value

        return result