"""Structured logging via structlog.

Two output modes:
* TTY: pretty, human-readable.
* Non-TTY (CI, Docker, files): line-delimited JSON.

Use :func:`get_logger` everywhere. Inject per-request context with
:func:`bind_context`.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pathlib import Path

    from structlog.types import EventDict, Processor

_request_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "teridex_request_context", default=None
)

_configured = False
_log_file_stream: Any = None


def _merge_request_context(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    ctx = _request_context.get()
    if ctx:
        for key, value in ctx.items():
            event_dict.setdefault(key, value)
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    json: bool | None = None,
    log_file: Path | None = None,
    force: bool = False,
) -> None:
    """Configure structlog + stdlib logging. Idempotent unless force=True."""

    global _configured, _log_file_stream  # noqa: PLW0603 - module-level idempotency flags
    if _configured and not force:
        return

    # Do not close the previous log stream in tests to prevent cached loggers from raising ValueError
    # when writing to a closed file descriptor.
    _log_file_stream = None

    stream: Any = sys.stderr
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            stream = log_file.open("a", encoding="utf-8")
            _log_file_stream = stream
        except OSError:
            # Fallback to sys.stderr if log file cannot be opened
            stream = sys.stderr

    if json is None:
        json = not stream.isatty() if hasattr(stream, "isatty") else True

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _merge_request_context,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if json:
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=stream,
        level=level.upper(),
        force=True,
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if not _configured:
        configure_logging()
    bound: structlog.stdlib.BoundLogger = (
        structlog.get_logger(name) if name else structlog.get_logger()
    )
    return bound


def bind_context(**kwargs: Any) -> None:
    """Bind keys onto the current logging context (request/query scope)."""
    current = _request_context.get() or {}
    ctx = {**current, **kwargs}
    _request_context.set(ctx)


def clear_context() -> None:
    _request_context.set(None)
