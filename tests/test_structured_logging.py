"""Structured logging regression suite (P1: observability gap closure).

Pins the behaviours ``docs/operations/RUNBOOK.md`` listed as missing:

* **configuration actually exists** — one idempotent root handler, level
  via ``CONTROL_PLANE_LOG_LEVEL``, encoding via ``CONTROL_PLANE_LOG_FORMAT``
  (production defaults to JSON). Before this, ``api.*`` loggers inherited
  root's implicit ``WARNING`` level and Python's ``lastResort`` handler, so
  every ``logger.info``/``logger.debug`` in the control plane was dropped;
* **JSON records parse** and carry ``ts``/``level``/``logger``/``message``
  plus any ``extra={}`` field (``event``, ``run_id``, ``stage``, ...);
* **request correlation** — ``X-Request-Id`` is echoed when header-safe,
  minted otherwise, never reflected raw; the access line's ``request_id``
  equals the response header;
* **secrets stay out of logs** — the bearer token never appears in a
  formatted record (the auth-layer twin of this assertion lives in
  ``tests/test_production_auth_env.py``);
* **durable terminal writes** — ``_persist_final`` retries transient
  failures, reports ``True``/``False``, and logs ``run.terminal`` or
  ``run.terminal_persist_failed`` with the ``run_id`` instead of swallowing
  the error.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import uuid

import pytest
from fastapi.testclient import TestClient

import api.logging_config as lc
from api.app import app
from api.logging_config import (
    LOG_FORMAT_ENV,
    LOG_LEVEL_ENV,
    REQUEST_ID_VAR,
    RequestIdFilter,
    StructuredFormatter,
    configure_logging,
    new_request_id,
)
from api.models import RunStage
from api.service import Service
from api.store import RunRecord, Store

client = TestClient(app)

_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@pytest.fixture(autouse=True)
def _restore_baseline_logging():
    """Re-install the baseline log configuration after each test.

    ``configure_logging(force=True)`` mutates the *global* root logger
    (including its level), so a test that forces DEBUG/JSON must leave the
    session exactly as it found it — otherwise later tests would see JSON
    lines or debug output they never asked for, and the suite would pass or
    fail depending on execution order.
    """
    yield
    saved = {
        key: os.environ.pop(key, None)
        for key in (LOG_LEVEL_ENV, LOG_FORMAT_ENV, "CONTROL_PLANE_ENV")
    }
    try:
        configure_logging(force=True)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _attach_capture_handler() -> tuple[logging.Handler, io.StringIO]:
    """Attach a root handler shaped exactly like the configured one."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(StructuredFormatter())
    handler.addFilter(RequestIdFilter())
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)
    return handler, buffer


class TestConfiguration:
    def test_handler_is_installed_exactly_once(self):
        configure_logging()
        configure_logging()
        marked = getattr(logging.getLogger(), lc._HANDLER_MARKER, None)
        assert marked is not None, "importing the app must configure logging"
        assert logging.getLogger().handlers.count(marked) == 1, (
            "configure_logging must be idempotent: a second call must not"
            " duplicate every line in production logs"
        )

    def test_level_env_drives_the_root_level(self, monkeypatch):
        monkeypatch.setenv(LOG_LEVEL_ENV, "DEBUG")
        configure_logging(force=True)
        assert logging.getLogger().level == logging.DEBUG

    def test_unknown_level_falls_back_to_info(self, monkeypatch):
        monkeypatch.setenv(LOG_LEVEL_ENV, "NOT-A-LEVEL")
        configure_logging(force=True)
        assert logging.getLogger().level == logging.INFO, (
            "an unknown level must never disable logging"
        )

    def test_format_env_selects_json(self, monkeypatch):
        monkeypatch.setenv(LOG_FORMAT_ENV, "json")
        configure_logging(force=True)
        marked = getattr(logging.getLogger(), lc._HANDLER_MARKER)
        assert isinstance(marked.formatter, StructuredFormatter)

    def test_production_env_defaults_to_json(self, monkeypatch):
        monkeypatch.setenv("CONTROL_PLANE_ENV", "production")
        configure_logging(force=True)
        marked = getattr(logging.getLogger(), lc._HANDLER_MARKER)
        assert isinstance(marked.formatter, StructuredFormatter), (
            "production logs are machine-parsed; JSON is the default there"
        )

    def test_development_defaults_to_text(self, monkeypatch):
        monkeypatch.delenv(LOG_FORMAT_ENV, raising=False)
        monkeypatch.delenv("CONTROL_PLANE_ENV", raising=False)
        configure_logging(force=True)
        marked = getattr(logging.getLogger(), lc._HANDLER_MARKER)
        assert not isinstance(marked.formatter, StructuredFormatter)


class TestJsonRecords:
    def test_info_record_is_parseable_json_with_required_keys(self, caplog):
        handler, buffer = _attach_capture_handler()
        try:
            with caplog.at_level(logging.DEBUG):
                logging.getLogger("api.test.json").info(
                    "hello", extra={"event": "unit.test", "run_id": "run-42"}
                )
        finally:
            logging.getLogger().removeHandler(handler)

        line = buffer.getvalue().strip()
        assert line, "the configured handler must actually emit records"
        payload = json.loads(line)  # must be one complete JSON object
        assert payload["level"] == "INFO"
        assert payload["logger"] == "api.test.json"
        assert payload["message"] == "hello"
        assert payload["event"] == "unit.test"
        assert payload["run_id"] == "run-42"
        assert payload["request_id"] == "-", "no request context -> '-'"
        assert payload["ts"].endswith("Z")

    def test_exception_records_carry_the_traceback(self, caplog):
        handler, buffer = _attach_capture_handler()
        try:
            with caplog.at_level(logging.DEBUG):
                try:
                    raise ValueError("boom")
                except ValueError:
                    logging.getLogger("api.test.exc").exception(
                        "failed", extra={"event": "unit.failure"}
                    )
        finally:
            logging.getLogger().removeHandler(handler)

        payload = json.loads(buffer.getvalue().strip())
        assert payload["level"] == "ERROR"
        assert "ValueError: boom" in payload["exception"]

    def test_debug_is_reachable_when_configured(self, monkeypatch, caplog):
        monkeypatch.setenv(LOG_LEVEL_ENV, "DEBUG")
        configure_logging(force=True)
        handler, buffer = _attach_capture_handler()
        try:
            with caplog.at_level(logging.DEBUG):
                logging.getLogger("api.test.debug").debug("visible-now")
        finally:
            logging.getLogger().removeHandler(handler)
        assert "visible-now" in buffer.getvalue(), (
            "INFO/DEBUG lines were previously dropped unconditionally:"
            " configuring the level must actually reach them"
        )

    def test_debug_is_dropped_at_info_level(self, monkeypatch, caplog):
        monkeypatch.setenv(LOG_LEVEL_ENV, "INFO")
        configure_logging(force=True)
        handler, buffer = _attach_capture_handler()
        try:
            logging.getLogger("api.test.level").debug("must-not-appear")
        finally:
            logging.getLogger().removeHandler(handler)
        assert "must-not-appear" not in buffer.getvalue()


class TestRequestIdCorrelation:
    def test_safe_incoming_id_is_echoed(self):
        assert new_request_id("ticket-42_ABC.9") == "ticket-42_ABC.9"

    def test_unsafe_incoming_id_is_replaced_not_reflected(self):
        minted = new_request_id("inject me with spaces and *stars*")
        assert _SAFE.match(minted), "an unsafe id must never be echoed"
        assert minted != "inject me with spaces and *stars*"

    def test_overlong_id_is_replaced(self):
        minted = new_request_id("x" * 65)
        assert minted != "x" * 65 and _SAFE.match(minted)

    def test_missing_id_is_minted(self):
        assert _SAFE.match(new_request_id(None))
        assert _SAFE.match(new_request_id(""))

    def test_filter_injects_the_contextvar(self):
        token = REQUEST_ID_VAR.set("ctx-1")
        try:
            record = logging.LogRecord(
                "t", logging.INFO, __file__, 1, "m", None, None
            )
            assert RequestIdFilter().filter(record) is True
            assert record.request_id == "ctx-1"
        finally:
            REQUEST_ID_VAR.reset(token)

    def test_response_header_echoes_the_incoming_id(self):
        resp = client.get("/health", headers={"X-Request-Id": "ticket-42"})
        assert resp.headers["X-Request-Id"] == "ticket-42"

    def test_response_header_mints_one_when_absent(self):
        resp = client.get("/health")
        assert _SAFE.match(resp.headers["X-Request-Id"]), (
            "every response must carry a correlation id"
        )

    def test_unsafe_header_value_is_not_reflected(self):
        resp = client.get("/health", headers={"X-Request-Id": "bad value*here"})
        echoed = resp.headers["X-Request-Id"]
        assert echoed != "bad value*here"
        assert _SAFE.match(echoed)

    def test_access_log_request_id_matches_the_header(self, caplog):
        with caplog.at_level(logging.INFO, logger="api.app"):
            resp = client.get("/health", headers={"X-Request-Id": "corr-7"})
        access = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "http.request"
            and getattr(record, "request_id", None) == "corr-7"
        ]
        assert access, "one access line per request, keyed by request id"
        record = access[-1]
        assert record.method == "GET"
        assert record.path == "/health"
        assert record.status == 200
        assert isinstance(record.duration_ms, float)
        assert record.request_id == resp.headers["X-Request-Id"]


class TestSecretsStayOutOfLogs:
    def test_token_never_appears_in_a_formatted_record(
        self, monkeypatch, caplog
    ):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "super-secret-token-value")
        with caplog.at_level(logging.DEBUG):
            resp = client.get(
                "/applications",
                headers={"Authorization": "Bearer super-secret-token-value"},
            )
        assert resp.status_code == 200
        formatter = StructuredFormatter()
        for record in caplog.records:
            line = formatter.format(record)
            assert "super-secret-token-value" not in line, (
                "the bearer token must never reach a log record"
            )

    def test_access_log_excludes_headers(self, monkeypatch, caplog):
        monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "super-secret-token-value")
        with caplog.at_level(logging.DEBUG):
            client.get(
                "/applications",
                headers={"Authorization": "Bearer super-secret-token-value"},
            )
        for record in caplog.records:
            if getattr(record, "event", None) != "http.request":
                continue
            keys = set(record.__dict__)
            assert "authorization" not in {k.lower() for k in keys}
            assert "headers" not in {k.lower() for k in keys}


def _make_run(store: Store) -> RunRecord:
    run = RunRecord(
        id=f"run-log-{uuid.uuid4().hex[:8]}",
        application_id="app-log",
        workload_id="wl-log",
        stage=RunStage.CREATED,
    )
    store.add_run(run)
    return run


class TestTerminalPersistDurability:
    def test_success_logs_a_terminal_event_with_run_id(
        self, tmp_path, caplog
    ):
        store = Store(db_path=tmp_path / "terminal.db")
        svc = Service(store)
        run = _make_run(store)
        run.stage = RunStage.FAILED
        run.error = "expected"

        with caplog.at_level(logging.INFO, logger="api.service"):
            ok = svc._persist_final(run)

        assert ok is True
        events = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "run.terminal"
        ]
        assert events, "a terminal transition must be observable in logs"
        assert events[-1].run_id == run.id
        assert events[-1].stage == "FAILED"

    def test_transient_write_failure_is_retried(
        self, monkeypatch, tmp_path, caplog
    ):
        store = Store(db_path=tmp_path / "retry.db")
        svc = Service(store)
        run = _make_run(store)
        run.stage = RunStage.FAILED

        calls = {"n": 0}
        real_update = store.update_run

        def flaky(record):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("database is locked")
            return real_update(record)

        monkeypatch.setattr(store, "update_run", flaky)

        with caplog.at_level(logging.INFO, logger="api.service"):
            ok = svc._persist_final(run)

        assert ok is True, "transient lock contention must be recovered"
        assert calls["n"] == 3
        assert store.get_run(run.id).stage == RunStage.FAILED

    def test_persistent_failure_is_reported_and_logged(
        self, monkeypatch, tmp_path, caplog
    ):
        store = Store(db_path=tmp_path / "persist-fail.db")
        svc = Service(store)
        run = _make_run(store)
        run.stage = RunStage.FAILED

        def always_fails(record):
            raise RuntimeError("validation_generation moved on")

        monkeypatch.setattr(store, "update_run", always_fails)

        with caplog.at_level(logging.ERROR, logger="api.service"):
            ok = svc._persist_final(run)

        assert ok is False, "a lost terminal write must be reported, not hidden"
        failures = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "run.terminal_persist_failed"
        ]
        assert failures, "the operator must see which run was stranded"
        assert failures[-1].run_id == run.id
        assert failures[-1].attempts == 3
        assert failures[-1].stage == "FAILED"

    def test_retries_are_bounded(self, monkeypatch, tmp_path):
        store = Store(db_path=tmp_path / "bounded.db")
        svc = Service(store)
        run = _make_run(store)
        run.stage = RunStage.FAILED

        calls = {"n": 0}

        def always_fails(record):
            calls["n"] += 1
            raise RuntimeError("no")

        monkeypatch.setattr(store, "update_run", always_fails)
        assert svc._persist_final(run, attempts=2) is False
        assert calls["n"] == 2, "retries must be bounded, never infinite"
