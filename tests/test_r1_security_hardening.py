"""Red-first coverage for the 2026-10-21 universal requirements audit, batch R1.

The properties under test come from the project's security requirements:

- every controlled execution is network- and resource-limited, and must be
  cleaned up if it times out;
- archive extraction is protected against zip bombs and ambiguous names;
- request bodies are bounded even when the client declares no length;
- the production deployment refuses to serve an unauthenticated API.

Concretely, that is:

- producer container isolation (`producers/opensource4j.py`);
- production entry points must not serve an unauthenticated API;
- multipart upload names collide case-insensitively, matching the ZIP path;
- ZIP entries are rejected on compression ratio (zip-bomb guard);
- request bodies are bounded when `Content-Length` is absent.

Each test pins observable behaviour; none of them asserts on implementation
detail beyond the argv/contract that the requirement actually constrains.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from api.ingestion import IngestionError, ingest_zip
from api.service import Service, ServiceError

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Producer container isolation
# ---------------------------------------------------------------------------

def _capture_producer_calls(monkeypatch, program_id: str = "PROG1") -> list[list[str]]:
    """Run the producer with a stubbed `docker run`; return every argv issued.

    All calls are recorded (not just the first): a correct producer must also
    issue container cleanup after the timeout, and that must not be mistaken
    for the run invocation.
    """
    import subprocess as sp

    from engine.transformation.producers import opensource4j as mod

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001 - argv is the contract under test
        calls.append(list(cmd))
        raise sp.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    adapter = mod.OpenSourceCOBOL4JProducerAdapter()
    result = adapter.transform(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. PROG1.\n",
        program_id=program_id,
    )
    assert result is not None
    assert calls, "producer never invoked docker — isolation untestable"
    return calls


def _run_argv(calls: list[list[str]]) -> list[str]:
    """Return the argv of the `docker run` invocation (cleanup excluded)."""
    for argv in calls:
        if len(argv) >= 2 and argv[0] == "docker" and argv[1] == "run":
            return argv
    raise AssertionError(f"no `docker run` invocation among: {calls}")


def _capture_producer_argv(monkeypatch, program_id: str = "PROG1") -> list[str]:
    """Run the producer with a stubbed `docker run` and return the run argv."""
    return _run_argv(_capture_producer_calls(monkeypatch, program_id))


def test_producer_container_disables_network(monkeypatch):
    """The producer container must not be able to reach the network."""
    argv = _capture_producer_argv(monkeypatch)
    assert "--network" in argv, "producer container has no --network flag"
    assert argv[argv.index("--network") + 1] == "none"


def test_producer_container_applies_resource_limits(monkeypatch):
    """CPU, memory and PID limits must all be present and non-empty."""
    argv = _capture_producer_argv(monkeypatch)
    for flag in ("--memory", "--cpus", "--pids-limit"):
        assert flag in argv, f"producer container missing {flag}"
        value = argv[argv.index(flag) + 1]
        assert value, f"{flag} present but empty"


def test_producer_container_hardening_flags(monkeypatch):
    """Privilege escalation must be blocked inside the container."""
    argv = _capture_producer_argv(monkeypatch)
    assert "--security-opt" in argv
    opt_index = argv.index("--security-opt")
    assert "no-new-privileges" in argv[opt_index + 1]


def test_producer_container_is_named_for_timeout_cleanup(monkeypatch):
    """The container must carry a name so a timed-out run can be cleaned up.

    `--rm` alone does not remove a container whose CLI client was killed by
    the timeout, so the run must be identifiable and a cleanup must be issued.
    """
    calls = _capture_producer_calls(monkeypatch)
    argv = _run_argv(calls)

    assert "--name" in argv, "producer container has no --name for cleanup"
    name = argv[argv.index("--name") + 1]
    assert name, "--name present but empty"

    cleanup = [a for a in calls if len(a) >= 3 and a[:2] == ["docker", "rm"]]
    assert cleanup, f"no `docker rm` issued after timeout; calls={calls}"
    assert name in cleanup[0], (
        f"cleanup does not target the timed-out container: {cleanup[0]}"
    )


# ---------------------------------------------------------------------------
# Production entry points must not serve an unauthenticated API
# ---------------------------------------------------------------------------

def test_production_compose_requires_api_token():
    """The production compose file must refuse to start without a token."""
    compose = (REPO_ROOT / "docker-compose.production.yml").read_text(
        encoding="utf-8"
    )
    assert "CONTROL_PLANE_API_TOKEN:? " in compose or (
        "${CONTROL_PLANE_API_TOKEN:?" in compose
    ), (
        "docker-compose.production.yml must use compose's required-variable "
        "syntax so a production stack cannot start unauthenticated"
    )


def test_start_script_still_refuses_unauthenticated_start():
    """The start script must keep its own token check (it predates the compose rule)."""
    script = REPO_ROOT / "scripts" / "deploy" / "start-production.sh"
    if not script.is_file():
        pytest.skip("start-production.sh not present in this tree")
    text = script.read_text(encoding="utf-8")
    assert "CONTROL_PLANE_API_TOKEN" in text


# ---------------------------------------------------------------------------
# Multipart upload names must collide case-insensitively, like the ZIP path
# ---------------------------------------------------------------------------

def test_multipart_casefold_collision_rejected():
    """`A.cob` and `a.cob` must not both be accepted."""
    with pytest.raises(ServiceError) as excinfo:
        Service._validate_upload({"src/A.cob": b"one", "src/a.cob": b"two"})
    message = str(excinfo.value)
    assert "A.cob" in message and "a.cob" in message


def test_multipart_separator_alias_collision_rejected():
    """`dir\\x.cbl` and `dir/x.cbl` resolve to the same entry and must collide."""
    with pytest.raises(ServiceError):
        Service._validate_upload({"dir\\x.cbl": b"one", "dir/x.cbl": b"two"})


def test_multipart_distinct_entries_still_accepted():
    """Guard: genuinely distinct names must keep working (no over-correction)."""
    resolved = Service._validate_upload(
        {"src/PROG.cob": b"one", "copy/COPYBOOK.cpy": b"two"}
    )
    assert len(resolved) == 2


# ---------------------------------------------------------------------------
# ZIP compression-ratio (zip-bomb) guard
# ---------------------------------------------------------------------------

def _zip_bytes(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_zip_compression_ratio_bomb_rejected():
    """A tiny archive that explodes in size must be rejected."""
    # ~500 KB of identical characters compresses to a few hundred bytes, so the
    # declared ratio is orders of magnitude above any legitimate source archive.
    data = _zip_bytes({"src/PROG.cob": "0" * 500_000})
    with pytest.raises(IngestionError) as excinfo:
        ingest_zip(data, "bomb-app")
    assert "ratio" in str(excinfo.value).lower()


def test_zip_normal_source_archive_accepted():
    """Guard: ordinary (well-compressing) COBOL source must still ingest."""
    data = _zip_bytes(
        {
            "src/PROG.cob": (
                "IDENTIFICATION DIVISION.\n"
                "PROGRAM-ID. PROG1.\n"
                "DATA DIVISION.\n"
                "WORKING-STORAGE SECTION.\n"
                "01  WS-COUNTER PIC 9(4) VALUE ZERO.\n"
                "PROCEDURE DIVISION.\n"
                "    STOP RUN.\n"
            )
        }
    )
    workspace = ingest_zip(data, "normal-app")
    try:
        assert (workspace / "src" / "PROG.cob").is_file()
    finally:
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)


def test_zip_empty_entries_do_not_divide_by_zero():
    """Guard: a zero-length entry has no meaningful ratio and must be allowed."""
    data = _zip_bytes({"src/EMPTY.cob": ""})
    workspace = ingest_zip(data, "empty-app")
    try:
        assert (workspace / "src" / "EMPTY.cob").is_file()
    finally:
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Bounded request bodies when the client declares no Content-Length
# ---------------------------------------------------------------------------

def _scope(*, with_content_length: bool | None, content_type: str = "application/json"):
    headers = [(b"content-type", content_type.encode())]
    if with_content_length is not None:
        headers.append(
            (b"content-length", str(with_content_length).encode())
        )
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/applications",
        "raw_path": b"/applications",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }


class _AppSpy:
    """ASGI application stub that records whether the pipeline was reached."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        self.called = True
        body = b""
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": json.dumps({"received": len(body)}).encode(),
            }
        )


async def _drive(middleware, scope, chunks):
    sent: list[dict] = []

    async def receive():
        try:
            return chunks.pop(0)
        except IndexError:
            return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    return sent


def test_body_limit_rejects_chunked_oversized_json():
    """A body with no `Content-Length` must still be subject to the limit."""
    import asyncio

    from api.app import BodyLimitMiddleware

    app = _AppSpy()
    middleware = BodyLimitMiddleware(app, max_bytes=1024)
    chunks = [{"type": "http.request", "body": b"x" * 2048, "more_body": False}]
    sent = asyncio.run(_drive(middleware, _scope(with_content_length=None), chunks))

    assert not app.called, "oversized body must never reach the application"
    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    assert statuses and statuses[0] == 413


def test_body_limit_allows_bounded_chunked_json():
    """Guard: a small chunked body must still reach the application."""
    import asyncio

    from api.app import BodyLimitMiddleware

    app = _AppSpy()
    middleware = BodyLimitMiddleware(app, max_bytes=1024)
    chunks = [
        {"type": "http.request", "body": b'{"name":', "more_body": True},
        {"type": "http.request", "body": b'"demo"}', "more_body": False},
    ]
    sent = asyncio.run(_drive(middleware, _scope(with_content_length=None), chunks))

    assert app.called, "bounded chunked body was blocked"
    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    assert statuses and statuses[0] == 200


def test_body_limit_rejects_declared_oversize_content_length():
    """Guard: an oversized declared `Content-Length` fails closed immediately."""
    import asyncio

    from api.app import BodyLimitMiddleware

    app = _AppSpy()
    middleware = BodyLimitMiddleware(app, max_bytes=1024)
    chunks = [{"type": "http.request", "body": b"x" * 16, "more_body": False}]
    sent = asyncio.run(
        _drive(
            middleware,
            _scope(with_content_length=9_999_999),
            chunks,
        )
    )

    assert not app.called
    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    assert statuses and statuses[0] == 413
