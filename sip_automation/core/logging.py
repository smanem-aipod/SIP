from __future__ import annotations

import json
import logging
import logging.config
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from sip_automation.core.config import ConfigManager


_CONFIGURED = False


def configure_logging(
    config: ConfigManager,
) -> None:
    """
    Configure application logging from config/logging.yaml.

    Calling this function multiple times is safe.
    """

    global _CONFIGURED

    if _CONFIGURED:
        return

    logging_config = config.get_logging_config()

    level_name = str(
        logging_config.get("level", "INFO")
    ).upper()

    numeric_level = getattr(
        logging,
        level_name,
        logging.INFO,
    )

    console_config = logging_config.get(
        "console",
        {},
    )

    file_config = logging_config.get(
        "file",
        {},
    )

    format_config = logging_config.get(
        "format",
        {},
    )

    json_output = bool(
        format_config.get("json", True)
    )

    handlers: list[logging.Handler] = []

    if console_config.get("enabled", True):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        handlers.append(console_handler)

    if file_config.get("enabled", True):
        file_path = Path(
            file_config.get(
                "path",
                "logs/sip_automation.log",
            )
        )

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        maximum_bytes = (
            int(file_config.get("rotation_size_mb", 10))
            * 1024
            * 1024
        )

        file_handler = RotatingFileHandler(
            filename=file_path,
            maxBytes=maximum_bytes,
            backupCount=int(
                file_config.get("backup_count", 10)
            ),
            encoding="utf-8",
        )

        file_handler.setLevel(numeric_level)
        handlers.append(file_handler)

    logging.basicConfig(
        level=numeric_level,
        format="%(message)s",
        handlers=handlers,
        force=True,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(
            fmt="iso",
            utc=True,
            key="timestamp",
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer(
            serializer=json.dumps,
            sort_keys=True,
        )
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            numeric_level
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Return a structured logger.
    """

    return structlog.get_logger(name)


def bind_run_context(
    *,
    run_id: str,
    initiated_by: str | None = None,
    fiscal_year: int | None = None,
) -> None:
    """
    Add safe pipeline-run metadata to all logs in the current context.
    """

    values: dict[str, Any] = {
        "run_id": run_id,
    }

    if initiated_by is not None:
        values["initiated_by"] = initiated_by

    if fiscal_year is not None:
        values["fiscal_year"] = fiscal_year

    structlog.contextvars.bind_contextvars(
        **values
    )


def clear_log_context() -> None:
    """
    Clear structured logging context after a run completes.
    """

    structlog.contextvars.clear_contextvars()