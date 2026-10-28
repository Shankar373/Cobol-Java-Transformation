"""FastAPI control-plane application.

Endpoints:
  POST   /applications                           — register an application
  GET    /applications                           — list applications
  GET    /applications/{id}                      — application detail
  GET    /applications/{id}/runs                 — list runs for an application
  POST   /applications/{id}/upload               — upload COBOL source files
  POST   /applications/{id}/candidate            — upload Java candidate files
  POST   /applications/{id}/ingest               — ingest ZIP archive
  GET    /applications/{id}/discovery             — discovery results
  POST   /applications/{id}/modernize            — trigger transform + validate
  GET    /runs/{id}                              — run status
  GET    /runs/{id}/detail                       — run detail (state + provenance)
  GET    /runs/{id}/artifacts                    — artifact metadata
  POST   /runs/{id}/validate                     — re-run validation (async)
  GET    /runs/{id}/verdict                      — verdict
  GET    /runs/{id}/report                       — modernization report
  GET    /runs/{id}/download                     — download generated ZIP
  GET    /health                                 — liveness probe
  GET    /ready                                  — readiness probe (503 when
                                                   a gating dependency is down)

Security / abuse controls:
  * optional bearer-token auth — set ``CONTROL_PLANE_API_TOKEN`` and every
    route except ``/health`` and ``/ready`` requires
    ``Authorization: Bearer <token>`` (constant-time comparison; no token
    configured means auth is off, which is the documented development
    default);
  * bounded upload reads — ``CONTROL_PLANE_MAX_REQUEST_BYTES``,
    ``CONTROL_PLANE_MAX_FILE_BYTES`` and ``CONTROL_PLANE_MAX_UPLOAD_FILES``
    reject oversized payloads before they are buffered;
  * typed service errors map to explicit HTTP statuses
    (404/409/413/429/400/500) instead of a generic 400/500.

Logging / observability:
  * one idempotent handler configured at import (see
    ``api.logging_config``): JSON lines in production, text in
    development, level via ``CONTROL_PLANE_LOG_LEVEL``, encoding via
    ``CONTROL_PLANE_LOG_FORMAT``;
  * every request gets an ``X-Request-Id`` (echoed when safe, minted
    otherwise) that is injected into all records emitted while handling
    it, and one access line is written per request with method, path,
    status and duration — no headers, no tokens, ever;
  * run lifecycle events carry ``run_id`` / ``stage`` / ``event`` fields
    so ``docker logs | grep <run>`` (or ``jq``) reconstructs a run.
"""

from __future__ import annotations

import hmac
import io
import logging
import os
import re
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api.artifact_seal import read_verified_bundle
from api.errors import ApiError, PayloadTooLargeError, ServiceError
from api.ingestion import IngestionError
from api.limits import env_int_limit
from api.logging_config import (
    REQUEST_ID_VAR,
    configure_logging,
    new_request_id,
)
from api.models import (
    ApplicationCreate,
    ApplicationResponse,
    ApprovalRequest,
    ApprovalResponse,
    ArtifactsResponse,
    ArtifactMetadata,
    ComparisonDetail,
    DiscoveryResponse,
    IngestResponse,
    IntegratedProofResult,
    IntegratedProofResponse,
    ModernizeOptions,
    ModernizeResponse,
    ModernizationReportResponse,
    RunDetailResponse,
    RunResponse,
    UploadResponse,
    ValidateResponse,
    VerdictResponse,
)
from api.service import Service
from api.store import ApplicationRecord, Store

logger = logging.getLogger(__name__)

# Configure structured logging before anything else emits a record: without
# this the root logger's implicit WARNING level silently dropped every
# info/debug line in the control plane (RUNBOOK gap "structured operational
# logging"). Idempotent — a second import or `force=False` call is a no-op.
configure_logging()

# ---------------------------------------------------------------------------
# Singletons (MVP — module-level, no DI framework)
# ---------------------------------------------------------------------------

_DEF_DB_DIR = Path(__file__).resolve().parent.parent / "data"
_DEF_DB_PATH = str(_DEF_DB_DIR / "control-plane.db")

_DEFAULT_MAX_REQUEST_BYTES = 50 * 1024 * 1024
_DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
_DEFAULT_MAX_UPLOAD_FILES = 1000
# Caps for the generated-app download archive (built in memory).
_DEFAULT_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
_DEFAULT_MAX_DOWNLOAD_FILES = 5000


def _store_path() -> str:
    """Resolve the SQLite path for the control plane.

    ``CONTROL_PLANE_DB`` overrides the default file location; ``:memory:``
    selects the historical non-persistent store (used by unit tests).
    """
    return os.environ.get("CONTROL_PLANE_DB", _DEF_DB_PATH)


def _env_limit(name: str, default: int) -> int:
    return env_int_limit(name, default, logger)


_store = Store(_store_path())
_service = Service(_store)

# A daemon worker dies with its process, so any run left non-terminal in the
# persisted store has no worker left to finish it: fail those runs at startup
# instead of letting clients poll them forever.
try:
    _interrupted = _store.mark_interrupted_runs()
    if _interrupted:
        logger.warning(
            "Marked %d interrupted run(s) as FAILED at startup",
            _interrupted,
            extra={
                "event": "startup.reconciled",
                "interrupted_runs": _interrupted,
            },
        )
except Exception:
    logger.exception(
        "Startup reconciliation of interrupted runs failed",
        extra={"event": "startup.reconcile_failed"},
    )

app = FastAPI(
    title="COBOL-Java Transformation Control Plane",
    version="0.1.0",
    description="Thin orchestration API over the validation engine.",
)


# ---------------------------------------------------------------------------
# Security middleware
# ---------------------------------------------------------------------------

class BodyLimitMiddleware:
    """Cap the size of every request body, whether or not the client declares one.

    Uploads already go through a size check, but that check only runs when the
    request carries a ``Content-Length`` header.  A chunked request declares no
    length, so it could previously be buffered in memory without any bound at
    all.  This middleware closes that hole for every route:

    * the client declares a length over the limit -> rejected with 413 before
      we read anything, so an oversized upload costs us nothing;
    * the client declares a length within the limit -> passed straight through,
      so large legitimate uploads still stream instead of being buffered;
    * the client declares no length (chunked) -> the body is read and counted
      first, then handed to the application, so an over-limit body never
      reaches a handler.

    It is registered as the innermost middleware so that responses produced
    here still pass back out through the CORS and security layers, and it sits
    behind the auth check so an unauthenticated request is refused before we
    spend any effort reading its body.
    """

    def __init__(self, app, max_bytes: int | None = None) -> None:
        self.app = app
        self._max_bytes = max_bytes

    def _limit(self) -> int:
        # A value passed in by the caller wins; otherwise read the environment
        # on every request so a config change (or a test) takes effect without
        # restarting the service.
        if self._max_bytes is not None:
            return self._max_bytes
        return _env_limit(
            "CONTROL_PLANE_MAX_REQUEST_BYTES", _DEFAULT_MAX_REQUEST_BYTES
        )

    async def __call__(self, scope, receive, send):  # noqa: ANN001
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # These methods have no body to measure.  Reading the channel here
        # would also take over the connection the application uses to notice
        # client disconnects, which cancels a streaming response before it has
        # sent anything — so we leave them alone.
        if scope.get("method", "").upper() in _BODYLESS_METHODS:
            await self.app(scope, receive, send)
            return

        limit = self._limit()
        declared: str | None = None
        for key, value in scope.get("headers", []):
            if key == b"content-length":
                declared = value.decode("latin-1")
                break

        if declared is not None and declared.isdigit():
            if int(declared) > limit:
                await _send_oversized_body_error(send)
                return
            # A declared length we can trust is already bounded, so stream it
            # straight through instead of buffering a second copy in memory.
            await self.app(scope, receive, send)
            return

        # The client never told us how big the body is (chunked or absent), so
        # we count it ourselves before letting the application see any of it.
        buffered = b""
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                # The client vanished part-way through sending the body.  We
                # never got a complete, bounded payload, so refuse it rather
                # than hand a truncated body to a handler that would try to
                # parse it.
                await _send_truncated_body_error(send)
                return
            buffered += message.get("body", b"")
            if len(buffered) > limit:
                await _send_oversized_body_error(send)
                return
            if not message.get("more_body"):
                break

        # The first read hands back the body we already collected; every read
        # after that goes to the real channel.  The application may be waiting
        # on a genuine disconnect signal (streaming responses do exactly that),
        # so we must not invent one here or the stream would be cut short.
        sent_body = False

        async def replay_receive():  # noqa: ANN202
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {
                    "type": "http.request",
                    "body": buffered,
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay_receive, send)


# These three methods cannot carry a request body worth measuring, so we hand
# them to the application untouched.  DELETE is intentionally not in this set:
# it is allowed to carry a body, and nothing streams a response on it, so
# bounding it costs us nothing and we keep the check.
_BODYLESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def _send_oversized_body_error(send) -> None:  # noqa: ANN001
    """Refuse a body larger than the configured limit, with a readable message."""
    payload = b'{"detail":"Request body exceeds the configured byte limit"}'
    await _send_json_error_response(send, 413, payload)


async def _send_truncated_body_error(send) -> None:  # noqa: ANN001
    """Refuse a body the client stopped sending before it was complete."""
    payload = b'{"detail":"Request body was not received completely"}'
    await _send_json_error_response(send, 400, payload)


async def _send_json_error_response(send, status: int, payload: bytes) -> None:  # noqa: ANN001
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


# Registered first, so it sits innermost in the stack: every later
# `add_middleware` wraps it, keeping auth / security headers / CORS outside.
app.add_middleware(BodyLimitMiddleware)

# CORS: deny by default. Configure CONTROL_PLANE_ALLOWED_ORIGINS as a
# comma-separated list (e.g. "https://app.example.com,https://admin.example.com")
# to enable cross-origin requests. Empty or unset = no CORS (same-origin only).
_allowed_origins = [
    o.strip() for o in os.environ.get("CONTROL_PLANE_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
if _allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type"],
        max_age=600,
    )


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # HSTS (only effective over HTTPS; harmless over HTTP)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Prevent MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Clickjacking protection
        response.headers["X-Frame-Options"] = "DENY"
        # XSS protection (legacy but harmless)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permissions policy (restrict powerful features)
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )
        # Content Security Policy (restrictive; adjust if frontend needs inline scripts)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        # Cache control for API responses (prevent caching of sensitive data)
        if request.url.path != "/health":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
        return response


app.add_middleware(_SecurityHeadersMiddleware)


def _expected_token() -> str | None:
    """Bearer token required for every route except /health (None = off)."""
    token = os.environ.get("CONTROL_PLANE_API_TOKEN")
    return token if token else None


# ---------------------------------------------------------------------------
# Deployment environment (P0: production fails closed without auth)
# ---------------------------------------------------------------------------
#
# Dev/test behaviour is unchanged: without CONTROL_PLANE_ENV (or with an
# explicit development/test value) the API runs with auth off when no
# CONTROL_PLANE_API_TOKEN is configured, exactly as before.  Setting
# CONTROL_PLANE_ENV=production flips the control plane to fail-closed:
# the process refuses to start without a token, and — defence in depth —
# the middleware answers 401 for every request except the probes
# (/health, /ready) and CORS preflight OPTIONS even if the import-time
# check was somehow bypassed.
_PRODUCTION_ENVIRONMENT = "production"
_KNOWN_NON_PRODUCTION_ENVIRONMENTS = frozenset({"", "development", "dev", "test"})


def deployment_environment() -> str:
    """Normalised ``CONTROL_PLANE_ENV`` value (``""`` when unset)."""
    return os.environ.get("CONTROL_PLANE_ENV", "").strip().lower()


def production_environment_active() -> bool:
    """True when this process is configured as a production deployment."""
    return deployment_environment() == _PRODUCTION_ENVIRONMENT


#: Minimum ``CONTROL_PLANE_API_TOKEN`` length accepted in production.
#: Non-emptiness alone let trivial values ("x", "changeme") satisfy every
#: guard in the stack; a shared control-plane secret must at least clear a
#: brute-force floor. `secrets.token_urlsafe(48)` yields 64 characters.
_MIN_PRODUCTION_TOKEN_LENGTH = 32


def verify_production_auth_configuration() -> None:
    """Fail closed when production would run without bearer authentication.

    Raises ``RuntimeError`` (which aborts process startup when called at
    import time) when:

    * ``CONTROL_PLANE_ENV`` holds an unrecognised value — an unknown
      environment must not silently behave like development,
    * ``CONTROL_PLANE_ENV=production`` with no ``CONTROL_PLANE_API_TOKEN``,
      or with a token shorter than :data:`_MIN_PRODUCTION_TOKEN_LENGTH`
      (a strength floor: non-emptiness alone accepted ``x``), and
    * by implication, a process that fails here never serves a request.

    Development and test environments keep their historical behaviour
    (auth off by default, any token accepted).
    """
    env = deployment_environment()
    if env not in _KNOWN_NON_PRODUCTION_ENVIRONMENTS and env != _PRODUCTION_ENVIRONMENT:
        raise RuntimeError(
            f"Unknown CONTROL_PLANE_ENV {env!r}; recognised values are "
            f"'production' and {sorted(v or '(unset)' for v in _KNOWN_NON_PRODUCTION_ENVIRONMENTS)}. "
            "Refusing to start in an unrecognised deployment environment."
        )
    token = _expected_token()
    if env == _PRODUCTION_ENVIRONMENT and token is None:
        raise RuntimeError(
            "CONTROL_PLANE_ENV=production requires CONTROL_PLANE_API_TOKEN to be "
            "set; refusing to start an unauthenticated production control plane."
        )
    if env == _PRODUCTION_ENVIRONMENT and len(token) < _MIN_PRODUCTION_TOKEN_LENGTH:
        raise RuntimeError(
            f"CONTROL_PLANE_ENV=production requires CONTROL_PLANE_API_TOKEN to be "
            f"at least {_MIN_PRODUCTION_TOKEN_LENGTH} characters (this one is "
            f"{len(token)}); refusing a trivially guessable production token. "
            "Generate one: python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\""
        )


@app.middleware("http")
async def _require_api_token(request: Request, call_next):
    token = _expected_token()
    # Unauthenticated probes only: liveness and readiness carry no data and
    # no secrets, and must answer for orchestrators that cannot authenticate.
    if request.url.path in ("/health", "/ready"):
        return await call_next(request)
    # CORS preflight: browsers never attach Authorization (or any credential)
    # to an OPTIONS preflight, so requiring the token here answered 401
    # *before* CORSMiddleware could reply — cross-origin deployment was
    # unusable in exactly the configuration that enables it (token + allowed
    # origins). An OPTIONS request carries no payload and can only elicit the
    # method Allow header, so it is safe to pass; the actual GET/POST that
    # follows is still fully authenticated.
    if request.method == "OPTIONS":
        return await call_next(request)
    if token is None:
        if production_environment_active():
            # Fail closed: a production process without a configured token
            # must never serve an unauthenticated request (defence in depth
            # behind verify_production_auth_configuration's startup check).
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    header = request.headers.get("Authorization", "")
    provided = header[7:] if header.startswith("Bearer ") else ""
    if not provided:
        provided = request.headers.get("X-API-Key", "")
    if not provided or not _token_matches(provided, token):
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


@app.middleware("http")
async def _request_id_and_access_log(request: Request, call_next):
    """Outermost middleware: correlation id + one structured access line.

    Registered *after* the auth middleware, and Starlette applies the last
    registered middleware outermost, so this wraps auth: a 401 still gets
    an ``X-Request-Id`` and still appears in the logs — the exact case a
    customer reports as "my request failed, here is the id".

    The id is echoed when it is header-safe (``[A-Za-z0-9._-]{1,64}`` —
    never reflected raw, so it cannot inject response headers) and is held
    in a contextvar that ``api.logging_config.RequestIdFilter`` injects
    into every record emitted while handling the request. The access line
    logs method/path/status/duration only: headers and tokens are never
    logged (pinned by the token-leak tests).
    """
    request_id = new_request_id(request.headers.get("X-Request-Id"))
    ctx_token = REQUEST_ID_VAR.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        _log_access(request, request_id, 500, started)
        raise
    finally:
        REQUEST_ID_VAR.reset(ctx_token)

    response.headers["X-Request-Id"] = request_id
    _log_access(request, request_id, response.status_code, started)
    return response


def _log_access(
    request: Request, request_id: str, status: int, started: float
) -> None:
    """One INFO line per request; never headers, never tokens."""
    logger.info(
        "request",
        extra={
            "event": "http.request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )


def _token_matches(provided: str, expected: str) -> bool:
    """Constant-time token compare that cannot raise on non-ASCII.

    ``hmac.compare_digest`` rejects ``str`` operands containing non-ASCII
    characters, which turned an unauthenticated probe carrying a non-ASCII
    bearer token into a 500 instead of a 401.  HTTP headers are latin-1
    decodable, so encoding both sides back to bytes is an exact round-trip;
    ``compare_digest`` on ``bytes`` never raises, keeping the comparison
    constant-time and fail-closed (a decode that still cannot be compared
    simply does not match).
    """
    provided_bytes = provided.encode("latin-1", errors="replace")
    expected_bytes = expected.encode("latin-1", errors="replace")
    return hmac.compare_digest(provided_bytes, expected_bytes)


# Import-time fail-closed gate: a production process without a bearer token
# (or an unknown CONTROL_PLANE_ENV) aborts here instead of serving.
verify_production_auth_configuration()


@app.exception_handler(ApiError)
async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """Map typed service/store errors to their explicit HTTP status."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.public_detail},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _svc() -> Service:
    return _service


def _error(status: int, msg: str) -> HTTPException:
    return HTTPException(status_code=status, detail=msg)


def _guard_content_length(request: Request) -> None:
    """Reject oversized requests from the header before reading any body."""
    raw = request.headers.get("content-length", "")
    if not raw.isdigit():
        return
    limit = _env_limit("CONTROL_PLANE_MAX_REQUEST_BYTES", _DEFAULT_MAX_REQUEST_BYTES)
    if int(raw) > limit:
        raise PayloadTooLargeError(
            f"Request body exceeds the {limit} byte limit"
        )


async def _read_upload_bounded(
    upload: UploadFile,
    *,
    remaining: list[int],
) -> bytes:
    """Read one upload in chunks, enforcing per-file and total budgets.

    ``remaining`` is a single-element list holding the bytes still allowed
    for the whole request, so the budget is shared across files.
    """
    limit = _env_limit("CONTROL_PLANE_MAX_FILE_BYTES", _DEFAULT_MAX_FILE_BYTES)
    name = upload.filename or "upload"
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        size += len(chunk)
        remaining[0] -= len(chunk)
        if size > limit:
            raise PayloadTooLargeError(
                f"File {name!r} exceeds the {limit} byte limit"
            )
        if remaining[0] < 0:
            raise PayloadTooLargeError(
                "Combined upload exceeds the configured request size limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _read_files_bounded(request: Request, files: list[UploadFile]) -> dict[str, bytes]:
    """Read a multipart file list with request/file/count limits enforced."""
    _guard_content_length(request)
    max_files = _env_limit(
        "CONTROL_PLANE_MAX_UPLOAD_FILES", _DEFAULT_MAX_UPLOAD_FILES
    )
    if len(files) > max_files:
        raise PayloadTooLargeError(
            f"Too many files in one upload ({len(files)} > {max_files})"
        )
    request_limit = _env_limit(
        "CONTROL_PLANE_MAX_REQUEST_BYTES", _DEFAULT_MAX_REQUEST_BYTES
    )
    remaining = [request_limit]
    contents: dict[str, bytes] = {}
    for index, upload in enumerate(files):
        name = upload.filename or f"file_{index}"
        if name in contents:
            # Two multipart parts carrying the same filename used
            # to overwrite one dict key, silently dropping a file and
            # undercounting ``files_received`` (the service-level
            # collision detector never saw the duplicate).  Reject the
            # whole upload fail-closed so an accepted request can never
            # lose a source file.
            raise ServiceError(
                f"Duplicate upload filename {name!r}; each file must have a"
                " unique name"
            )
        contents[name] = await _read_upload_bounded(upload, remaining=remaining)
    return contents


def _to_app_response(rec: ApplicationRecord) -> ApplicationResponse:
    """Map an internal record to the API response (provenance preserved)."""
    return ApplicationResponse(
        id=rec.id,
        name=rec.name,
        description=rec.description,
        workload_id=rec.workload_id,
        java_entrypoint=rec.java_entrypoint,
        target_runtime=rec.target_runtime,
        cobol_source_path=rec.cobol_source_path,
        java_candidate_path=rec.java_candidate_path,
        generated_app_path=rec.generated_app_path,
        generated_entrypoint=rec.generated_entrypoint,
        discovered_program_ids=list(rec.discovered_program_ids),
        generated_program_ids=list(rec.generated_program_ids),
        created_at=rec.created_at,
    )


def _to_run_response(rec) -> RunResponse:
    """Map an internal run record to the API run summary.

    ``verdict_state`` is served fail-closed
    (``Service.run_verdict_state``): it is present only when the run's
    verdict hash-matches its persisted evidence manifest, so summary
    consumers (e.g. the dashboard "Verified" stat) can never count an
    uncertified run as verified.
    """
    return RunResponse(
        id=rec.id,
        application_id=rec.application_id,
        workload_id=rec.workload_id,
        stage=rec.stage,
        created_at=rec.created_at,
        completed_at=rec.completed_at,
        error=rec.error,
        verdict_state=_svc().run_verdict_state(rec),
    )


def _safe_download_stem(name: str, fallback: str) -> str:
    """Sanitise an application name for use as a download filename stem."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-")
    return stem or fallback


def _contract_source(contract_id: str | None) -> str | None:
    """``declared``/``default`` prefix of a recorded certification contract."""
    if not contract_id:
        return None
    return contract_id.split(":", 1)[0]


# ---------------------------------------------------------------------------
# Application endpoints
# ---------------------------------------------------------------------------

@app.post("/applications", response_model=ApplicationResponse, status_code=201)
def create_application(body: ApplicationCreate) -> ApplicationResponse:
    """Register a new COBOL-to-Java application."""
    rec = _svc().create_application(
        name=body.name,
        description=body.description,
        workload_id=body.workload_id,
        java_entrypoint=body.java_entrypoint,
        target_runtime=body.target_runtime,
    )
    return _to_app_response(rec)


@app.get("/applications", response_model=list[ApplicationResponse])
def list_applications() -> list[ApplicationResponse]:
    """List all registered applications (persisted, ordered by creation)."""
    return [_to_app_response(rec) for rec in _svc().list_applications()]


@app.get("/applications/{app_id}", response_model=ApplicationResponse)
def get_application(app_id: str) -> ApplicationResponse:
    """Return application detail including generation provenance."""
    return _to_app_response(_svc().get_application(app_id))


@app.get("/applications/{app_id}/runs", response_model=list[RunResponse])
def list_application_runs(app_id: str) -> list[RunResponse]:
    """List all runs for an application (persisted, ordered by creation)."""
    runs = _svc().list_runs(app_id)
    return [_to_run_response(r) for r in runs]


@app.post("/applications/{app_id}/upload", response_model=UploadResponse, status_code=201)
async def upload_cobol_source(
    app_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    """Upload COBOL source files for an application."""
    file_contents = await _read_files_bounded(request, files)
    _app, count = _svc().upload_cobol_source(app_id, file_contents)

    return UploadResponse(
        application_id=_app.id,
        files_received=count,
        cobol_source_path=_app.cobol_source_path or "",
    )


@app.post("/applications/{app_id}/candidate", response_model=UploadResponse, status_code=201)
async def upload_java_candidate(
    app_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    """Upload Java candidate files for an application."""
    file_contents = await _read_files_bounded(request, files)
    _app, count = _svc().upload_java_candidate(app_id, file_contents)

    return UploadResponse(
        application_id=_app.id,
        files_received=count,
        cobol_source_path=_app.java_candidate_path or "",
    )


@app.post("/applications/{app_id}/modernize", response_model=ModernizeResponse, status_code=202)
def modernize_application(
    app_id: str, options: ModernizeOptions | None = None
) -> ModernizeResponse:
    """Trigger transformation + validation pipeline for an application.

    The normal workflow transforms the DISCOVERED application structure and
    validates the GENERATED artifact. The optional body flag is internal/
    test-only and never sent by the UI.
    """
    run = _svc().modernize(
        app_id,
        use_uploaded_candidate=(
            options.use_uploaded_candidate if options else False
        ),
    )

    return ModernizeResponse(
        run_id=run.id,
        application_id=run.application_id,
        stage=run.stage,
    )


@app.post("/applications/{app_id}/ingest", response_model=IngestResponse, status_code=201)
async def ingest_application(
    app_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> IngestResponse:
    """Ingest a ZIP archive containing legacy application source.

    Extracts the archive, runs application discovery, detects the project
    name, and returns structured results about the discovered source tree.
    """
    _guard_content_length(request)
    content = await _read_upload_bounded(file, remaining=[
        _env_limit("CONTROL_PLANE_MAX_REQUEST_BYTES", _DEFAULT_MAX_REQUEST_BYTES)
    ])
    zip_filename = file.filename or "upload.zip"
    try:
        discovery = _svc().ingest_application(app_id, content, zip_filename)
    except IngestionError as exc:
        # Malformed archive / unreadable source tree: explicit 400.
        # Service-level errors (404/409/...) map through the ApiError handler.
        raise _error(400, str(exc))

    app = _svc().get_application(app_id)
    return IngestResponse(
        application_id=app_id,
        workspace_path=app.cobol_source_path or "",
        source_file_count=discovery["source_file_count"],
        total_size_bytes=discovery["total_size_bytes"],
        discovery=discovery,
        detected_name=discovery.get("detected_name", ""),
        top_level_entries=discovery.get("top_level_entries", []),
    )


@app.get("/applications/{app_id}/discovery", response_model=DiscoveryResponse)
def get_application_discovery(app_id: str) -> DiscoveryResponse:
    """Return discovery results for an application."""
    app = _svc().get_application(app_id)
    if app.cobol_source_path is None:
        raise _error(404, "No source has been ingested for this application")

    from api.ingestion import discover_application
    discovery = discover_application(Path(app.cobol_source_path), app_id)

    return DiscoveryResponse(
        application_id=app_id,
        cobol_programs=discovery.cobol_programs,
        copybooks=discovery.copybooks,
        jcl_jobs=discovery.jcl_jobs,
        file_dependencies=discovery.file_dependencies,
        call_dependencies=discovery.call_dependencies,
        dependency_edges=discovery.dependency_edges,
        source_file_count=discovery.source_file_count,
        total_size_bytes=discovery.total_size_bytes,
        discovery_success=discovery.discovery_success,
        discovery_errors=discovery.discovery_errors,
    )


# ---------------------------------------------------------------------------
# Run endpoints
# ---------------------------------------------------------------------------

@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    """Get run status and summary."""
    run = _svc().get_run(run_id)

    return _to_run_response(run)


@app.get("/runs/{run_id}/detail", response_model=RunDetailResponse)
def get_run_detail(run_id: str) -> RunDetailResponse:
    """Get coherent run detail: state, app identity, discovery, files, verdict."""
    detail = _svc().get_run_detail(run_id)

    return RunDetailResponse(
        id=detail["id"],
        application_id=detail["application_id"],
        application_name=detail["application_name"],
        workload_id=detail["workload_id"],
        stage=detail["stage"],
        created_at=detail["created_at"],
        completed_at=detail["completed_at"],
        error=detail["error"],
        verdict_state=detail["verdict_state"],
        discovery=detail["discovery"],
        stage_messages=detail["stage_messages"],
        last_stage=detail.get("last_stage"),
        generated_files=detail["generated_files"],
    )


@app.get("/runs/{run_id}/artifacts", response_model=ArtifactsResponse)
def get_run_artifacts(run_id: str) -> ArtifactsResponse:
    """Get artifact metadata for a run."""
    artifacts = _svc().get_artifacts(run_id)

    return ArtifactsResponse(
        run_id=run_id,
        artifacts=[ArtifactMetadata(**a) for a in artifacts],
    )


# ---------------------------------------------------------------------------
# Customer approval
# ---------------------------------------------------------------------------

def _approval_response(run) -> ApprovalResponse:
    return ApprovalResponse(
        run_id=run.id,
        state=run.approval_state,
        approver=run.approval_approver,
        reason=run.approval_reason,
        decided_at=run.approval_decided_at,
    )


@app.get("/runs/{run_id}/approval", response_model=ApprovalResponse)
def get_run_approval(run_id: str) -> ApprovalResponse:
    """Current approval record for a run (PENDING until a decision)."""
    return _approval_response(_svc().get_run(run_id))


@app.post("/runs/{run_id}/approval", response_model=ApprovalResponse)
def decide_run_approval(run_id: str, body: ApprovalRequest) -> ApprovalResponse:
    """Record an explicit customer decision for a run.

    ``APPROVED`` and ``REJECTED`` are the only decisions; PENDING is the
    implicit state of every new run and never a decision.  Rejection
    REQUIRES a reason; approval may carry an optional reason.  The
    approver string is recorded input, not a verified identity (existing
    bearer-token auth only; no role-based access control).  A later
    decision supersedes the earlier one.
    """
    approver = body.approver.strip()
    if not approver:
        raise _error(422, "approver must be a non-empty string")
    reason = body.reason.strip() if body.reason else None
    if body.decision.value == "REJECTED" and not reason:
        raise _error(422, "rejection requires a reason")
    run = _svc().set_run_approval(
        run_id, decision=body.decision.value, approver=approver, reason=reason
    )
    return _approval_response(run)


@app.post("/runs/{run_id}/validate", response_model=ValidateResponse, status_code=202)
def validate_run(run_id: str) -> ValidateResponse:
    """Re-run validation on an existing run (asynchronous).

    Only terminal runs can be revalidated: an in-flight run answers 409 so
    two workers never race on one run. The reset clears the previous verdict
    before the new attempt starts; poll GET /runs/{id} until terminal.
    """
    run = _svc().revalidate(run_id)

    return ValidateResponse(run_id=run.id, stage=run.stage)


@app.get("/runs/{run_id}/verdict", response_model=VerdictResponse)
def get_run_verdict(run_id: str) -> VerdictResponse:
    """Get the verdict for a run."""
    v = _svc().get_verdict(run_id)
    comparisons_raw = _svc().get_comparisons(run_id)

    comparisons = [ComparisonDetail(**c) for c in comparisons_raw]
    contract_id = v.get("certification_contract")

    return VerdictResponse(
        run_id=v["run_id"],
        engine_run_id=v.get("engine_run_id"),
        state=v["state"],
        workload_id=v["workload_id"],
        source_hash=v["source_hash"],
        candidate_hash=v.get("candidate_hash"),
        oracle_id=v["oracle_id"],
        oracle_digest=v["oracle_digest"],
        executed_check_count=v["executed_check_count"],
        skipped_count=v["skipped_count"],
        unavailable_count=v["unavailable_count"],
        supported_scope_statement=v["supported_scope_statement"],
        evidence_manifest_hash=v["evidence_manifest_hash"],
        derivation_timestamp=v["derivation_timestamp"],
        differences=v.get("differences", []),
        comparisons=comparisons,
        certification_contract=contract_id,
        contract_source=_contract_source(contract_id),
    )


@app.get("/runs/{run_id}/report", response_model=ModernizationReportResponse)
def get_run_report(run_id: str) -> ModernizationReportResponse:
    """Get the full modernization report for a run.

    Contains capability analysis, transformation plan, limitations,
    and recommendations produced by the universal pipeline. Only
    returned when the pipeline ran — never fabricated.
    """
    report = _svc().get_run_report(run_id)

    run = _svc().get_run(run_id)
    return ModernizationReportResponse(
        run_id=run_id,
        application_id=run.application_id,
        report=report,
    )


@app.get("/runs/{run_id}/integrated-proof", response_model=IntegratedProofResponse)
def get_run_integrated_proof(run_id: str) -> IntegratedProofResponse:
    """Get the integrated proof for a run.

    Contains the dependency ledger and central status gate evaluating
    proof state for each declared dependency (proven/blocked/partial/unproven).

    The gate only ever downgrades:
        central VERIFIED <= runtime verdict is VERIFIED
                             AND evidence manifest is complete
                             AND evidence integrity validated
                             AND every required dependency is PROVEN

    JCL, DB2 and CICS have no runtime lane in this repository, so they can
    never reach PROVEN. A workload that declares them therefore resolves to
    NOT VERIFIED at the application level even when the COBOL <-> Java runtime
    lane itself is VERIFIED.
    """
    proof = _svc().get_integrated_proof(run_id)
    p = proof["proof"]
    run = _svc().get_run(run_id)

    return IntegratedProofResponse(
        run_id=run_id,
        proof=IntegratedProofResult(
            workload_id=p.get("workload_id", run.workload_id),
            application_id=p.get("application_id", run.application_id),
            central_status=p.get("central_status", "NOT_VERIFIED"),
            blocking_reasons=p.get(
                "blocking_reasons", p.get("reasons_for_not_verified", [])
            ),
            generation_success=bool(p.get("generation_success", False)),
            overall_capability=p.get("overall_capability", "UNKNOWN"),
            jcl_status=p.get("jcl_status", "NOT_PRESENT"),
            runtime=p.get("runtime", {}),
            dependency_ledger=p.get("dependency_ledger", []),
            required_dependencies=p.get(
                "required_dependencies",
                [e for e in p.get("dependency_ledger", []) if e.get("required", False)],
            ),
            unproven_dependencies=p.get("unproven_dependencies", []),
            runtime_verdict_is_verified=bool(p.get("runtime_verdict_is_verified", False)),
        ),
        application_id=run.application_id,
        verdict_state=(p.get("runtime") or {}).get("verdict_state", "NOT_RUN"),
        evidence_status="COMPLETE" if p.get("evidence_complete", False) else "INCOMPLETE",
        runtime_proof_status=(
            "VERIFIED" if p.get("runtime_verdict_is_verified", False) else "NOT_VERIFIED"
        ),
        reasons_for_not_verified=p.get("reasons_for_not_verified", []),
        proven_dependencies=p.get("proven_dependencies", []),
        unproven_dependencies=p.get("unproven_dependencies", []),
        blocked_dependencies=p.get("blocked_dependencies", []),
        unsupported_dependencies=p.get("unsupported_dependencies", []),
        evidence_complete=bool(p.get("evidence_complete", False)),
        evidence_integrity_valid=bool(p.get("evidence_integrity_valid", False)),
        required_dependencies_proven=bool(p.get("required_dependencies_proven", False)),
        overall_verification=p.get("overall_verification", "NOT_VERIFIED"),
    )


@app.get("/runs/{run_id}/download")
def download_generated(run_id: str) -> StreamingResponse:
    """Download the GENERATED Java application as a ZIP archive.

    Provenance guarantee: packages generated_app_path ONLY — the artifact
    produced by ApplicationGenerator during modernization. An uploaded
    candidate is never served here; runs without a generated artifact
    return 404.

    Export is blocked with 409 until the customer APPROVES the run. The
    gate runs immediately after the run lookup and BEFORE artifact
    lookup/size caps so no archive detail (existence, size, file count)
    leaks to an unapproved export; an unknown run is still 404.
    """
    run = _svc().get_run(run_id)
    if run.approval_state != "APPROVED":
        raise _error(
            409,
            f"Export blocked: run approval is {run.approval_state} — the"
            " customer must approve this run before download"
            f" (POST /runs/{run_id}/approval)",
        )
    app = _svc().get_application(run.application_id)

    java_dir = app.generated_app_path
    if java_dir is None or not Path(java_dir).exists():
        raise _error(404, "No generated Java application available for this run")

    # The archive is built in memory per request.  A pathological
    # or unexpectedly large generated tree could exhaust memory on an
    # authenticated GET, so both the file count and the total byte size
    # are capped and the request fails closed (413) BEFORE any bytes are
    # buffered — never a partial or truncated archive.
    max_files = _env_limit(
        "CONTROL_PLANE_MAX_DOWNLOAD_FILES", _DEFAULT_MAX_DOWNLOAD_FILES
    )
    max_bytes = _env_limit(
        "CONTROL_PLANE_MAX_DOWNLOAD_BYTES", _DEFAULT_MAX_DOWNLOAD_BYTES
    )

    files = sorted(p for p in Path(java_dir).rglob("*") if p.is_file())
    if len(files) > max_files:
        raise PayloadTooLargeError(
            f"Generated application has {len(files)} files,"
            f" exceeding the {max_files} file download limit"
        )
    total_bytes = 0
    for f in files:
        total_bytes += f.stat().st_size
        if total_bytes > max_bytes:
            raise PayloadTooLargeError(
                f"Generated application exceeds the {max_bytes} byte"
                " download limit"
            )

    # Never export bytes that no longer match the run's sealed evidence:
    # a bundle substituted on disk after execution fails closed (409)
    # instead of being served as the verified artifact (P0 — see
    # api.artifact_seal).  The bundle is read exactly once and those
    # same bytes are verified AND packaged, so a filesystem swap between
    # verification and packaging cannot reach the archive (verify-then-zip
    # TOCTOU — BL-140); the file/byte caps are enforced during that read.
    bundle = read_verified_bundle(
        java_dir,
        run.generated_seal,
        max_files=max_files,
        max_bytes=max_bytes,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname in sorted(bundle):
            zf.writestr(arcname, bundle[arcname])

    buf.seek(0)
    # Stable product filename derived from the application name (not the
    # workload id, which collides across applications reusing a workload).
    filename = f"{_safe_download_stem(app.name, run.id)}-generated.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    """Liveness only: the process answers. Use ``/ready`` for dependencies."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness probe: can this control plane actually serve writes?

    ``/health`` proves only that the process answers. ``/ready`` verifies
    the dependencies whose failure makes the API unable to do its job:

    * ``database`` — the SQLite file opens **read-write** (uploads and run
      updates are writes; a read-only or missing file is not ready);
    * ``workspace`` — the durable artifact root
      (``CONTROL_PLANE_WORKSPACE_DIR``) is creatable and writable, so
      ingest/upload/generation land somewhere that survives a restart and
      ``scripts/backup/backup.sh`` captures (unset = development temp dir,
      which is a supported configuration, not a fault);
    * ``staging`` — the sandbox staging root (``SANDBOX_STAGING_DIR``) is
      usable when configured (unset = development temp staging);
    * ``docker`` — the host daemon is probed and **reported but not
      gating**: a host daemon outage cannot be fixed by restarting this
      container, and the API keeps serving honestly either way (runs fail
      closed at the execution stage). Restarting on it would loop;
    * ``jobs`` — active/limit worker slots, informational.

    Returns 200 when the gating checks pass and 503 otherwise, so compose /
    Docker healthchecks mark a control plane that cannot persist anything
    as unhealthy instead of serving it.
    """
    from api.paths import workspace_root, workspace_root_problems
    from engine import docker_cli
    from engine.execution.sandbox_paths import ensure_staging_root, get_staging_root

    checks: dict[str, dict[str, object]] = {}

    db_ok, db_detail = _store.probe_database()
    checks["database"] = {"ok": db_ok, "detail": db_detail}

    ws_root = workspace_root()
    ws_problems = workspace_root_problems()
    checks["workspace"] = {
        "ok": not ws_problems,
        "detail": ws_problems[0]
        if ws_problems
        else (str(ws_root) if ws_root else "unset (platform temp directory)"),
    }

    staging_root = get_staging_root()
    if staging_root is None:
        staging_ok, staging_detail = True, (
            "SANDBOX_STAGING_DIR not configured (development temp staging)"
        )
    else:
        try:
            ensure_staging_root()
            staging_ok, staging_detail = True, f"{staging_root} writable"
        except Exception as exc:  # RuntimeError from ensure_staging_root
            staging_ok, staging_detail = False, str(exc)
    checks["staging"] = {"ok": staging_ok, "detail": staging_detail}

    docker_ok = docker_cli.check_docker_available(timeout=2)
    checks["docker"] = {
        "ok": docker_ok,
        "gating": False,
        "detail": "daemon reachable"
        if docker_ok
        else "daemon unreachable - runs fail closed at execution (not gating)",
    }

    active, limit = _service.job_slots()
    checks["jobs"] = {"active": active, "limit": limit, "gating": False}

    ready_ok = db_ok and not ws_problems and staging_ok
    return JSONResponse(
        status_code=200 if ready_ok else 503,
        content={
            "status": "ready" if ready_ok else "not_ready",
            "checks": checks,
        },
    )
