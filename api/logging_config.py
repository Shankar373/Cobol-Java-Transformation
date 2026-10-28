"""Structured logging for the control plane.

Production incidents are diagnosed from ``docker logs``.  Before this
module existed the control plane had **no logging configuration at all**:
``api.*`` loggers inherited the root logger's implicit ``WARNING`` level
and Python's ``lastResort`` plain-text handler, so every ``logger.info`` /
``logger.debug`` call in the API was silently dropped, messages were free
text that could not be grepped by ``run_id``, and no request carried an id
a customer could quote in a ticket.  ``docs/operations/RUNBOOK.md`` listed
this as an open gap ("structured operational logging ... emit one JSON
line per run lifecycle event").

What this module provides:

* **one** handler on the root logger, installed idempotently (a marker
  attribute prevents duplicates no matter how often configuration runs);
* JSON records by default in production (``ts``, ``level``, ``logger``,
  ``message``) — plain ``text`` in development, overridable with
  ``CONTROL_PLANE_LOG_FORMAT=json|text``;
* level control via ``CONTROL_PLANE_LOG_LEVEL`` (default ``INFO``), so
  ``DEBUG`` is reachable instead of unreachable;
* a per-request id (``X-Request-Id``) held in a ``contextvars.ContextVar``
  and injected into **every** record emitted while handling that request,
  giving request -> log correlation without threading an argument through
  the call graph;
* structured fields: any ``extra={...}`` passed to a logging call (e.g.
  ``run_id``, ``stage``, ``event``, ``duration_ms``) is serialised into the
  JSON object.

Deliberate non-features: no third-party dependency (the runtime stays
stdlib-only and deterministic), and **no secret is ever a log field** —
``CONTROL_PLANE_API_TOKEN`` is never passed to a logging call anywhere in
``api/``; ``tests/test_production_auth_env.py`` and
``tests/test_structured_logging.py`` pin that.

Configuration runs at ``api.app`` import so every entry point (uvicorn,
CLI, tests) gets the same behaviour; tests may re-run it with ``force=True``
after changing the environment.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

#: Environment variable selecting the output encoding (``json``/``text``).
LOG_FORMAT_ENV = "CONTROL_PLANE_LOG_FORMAT"
#: Environment variable selecting the root level (``DEBUG``/``INFO``/...).
LOG_LEVEL_ENV = "CONTROL_PLANE_LOG_LEVEL"

#: Per-request correlation id, set by the request-id middleware.
REQUEST_ID_VAR: ContextVar[str | None] = ContextVar(
    "control_plane_request_id", default=None
)

#: Marker attribute on the root logger: exactly one configured handler.
_HANDLER_MARKER = "_systemaops_structured_logging"

#: Incoming/echoed request ids: header-injection-safe alphabet and length.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: ``logging.LogRecord`` built-in attributes — never re-serialised as extras.
_STANDARD_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "request_id",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def new_request_id(incoming: str | None = None) -> str:
    """Echo a safe incoming ``X-Request-Id`` or mint a fresh one.

    Anything outside ``[A-Za-z0-9._-]{1,64}`` is discarded rather than
    reflected: the value is echoed back in a response header, so it must
    never be able to carry CR/LF or unbounded payload.
    """
    if incoming:
        candidate = incoming.strip()
        if _SAFE_REQUEST_ID.match(candidate):
            return candidate
    return uuid.uuid4().hex


def current_request_id() -> str | None:
    """The correlation id of the request being handled, if any."""
    return REQUEST_ID_VAR.get()


class RequestIdFilter(logging.Filter):
    """Stamp every record with the current request id (``"-"`` when none)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = REQUEST_ID_VAR.get() or "-"
        return True


class StructuredFormatter(logging.Formatter):
    """One JSON object per record; ``extra={}`` fields become JSON keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Readable single-line text for development (same fields, no JSON).

    Structured extras and the request id are appended to the formatted
    line itself (``formatMessage``), so a traceback — which ``format()``
    appends afterwards — still appears last.
    """

    def formatMessage(self, record: logging.LogRecord) -> str:
        base = super().formatMessage(record)
        extras = [
            f"{key}={value}"
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_")
        ]
        suffix = f" [{' '.join(extras)}]" if extras else ""
        return (
            f"{base}{suffix} (request_id={getattr(record, 'request_id', '-')})"
        )


def _default_format() -> str:
    raw = os.environ.get(LOG_FORMAT_ENV, "").strip().lower()
    if raw in ("json", "text"):
        return raw
    # Production logs are machine-parsed (log shippers, `docker logs | jq`);
    # development stays human-readable. CONTROL_PLANE_ENV mirrors the
    # production gate used by api.app.verify_production_auth_configuration.
    return "json" if os.environ.get("CONTROL_PLANE_ENV", "").strip() == "production" else "text"


def _configured_level() -> int:
    raw = os.environ.get(LOG_LEVEL_ENV, "INFO").strip().upper()
    level = logging.getLevelName(raw)
    if isinstance(level, int):
        return level
    # Unknown value must not disable logging: fall back and say so once.
    sys.stderr.write(
        f"Unknown {LOG_LEVEL_ENV}={raw!r}; using INFO\n"
    )
    return logging.INFO


def configure_logging(*, force: bool = False) -> logging.Logger:
    """Install the control-plane log handler (idempotent).

    ``force=True`` replaces a previously installed handler — used by tests
    that change ``CONTROL_PLANE_LOG_LEVEL`` / ``CONTROL_PLANE_LOG_FORMAT``
    and need the new settings applied. Double-installation is otherwise a
    no-op, so importing the app twice cannot duplicate every line.
    """
    root = logging.getLogger()
    existing = getattr(root, _HANDLER_MARKER, None)
    if existing is not None:
        if not force:
            return root
        root.removeHandler(existing)
        try:
            existing.close()
        except Exception:  # pragma: no cover - defensive
            pass
        setattr(root, _HANDLER_MARKER, None)

    level = _configured_level()
    handler = logging.StreamHandler(sys.stderr)
    if _default_format() == "json":
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    handler.addFilter(RequestIdFilter())
    handler.setLevel(level)
    root.addHandler(handler)
    root.setLevel(level)
    setattr(root, _HANDLER_MARKER, handler)
    return root
