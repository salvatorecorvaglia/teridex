"""Structured logging via structlog.

Two output modes:
* TTY: pretty, human-readable.
* Non-TTY (CI, Docker, files): line-delimited JSON.

Use :func:`get_logger` everywhere. Inject per-request context with
:func:`bind_context`.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from structlog.types import EventDict, Processor

_request_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "teridex_request_context", default=None
)

_configured = False


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
) -> None:
    """Configure structlog + stdlib logging. Idempotent."""

    global _configured  # noqa: PLW0603 - module-level idempotency flag
    if _configured:
        return

    if json is None:
        json = not sys.stderr.isatty()

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
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level.upper(),
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
