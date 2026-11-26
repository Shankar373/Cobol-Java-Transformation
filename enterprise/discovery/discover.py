"""Discovery workflow: ingest -> immutable checkpoint -> scan -> dependency analysis -> report.

Orchestrates the stages and nothing else; each stage is its own module.  The order is a safety property: the input
is frozen into a content-addressed, read-only checkpoint (pinned to the exact commit for Git) *before* any analysis,
and every later step reads the checkpoint, never the staging area or the original input.

Hard rules: no LLM, no network except an explicit remote Git fetch, deterministic artefacts (the only wall-clock
values live in ``run-record.json``), fail closed, never silently drop a file or a finding.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .applications import build_applications, link_applications
from .blueprint import BLUEPRINT_ARTEFACTS, build_blueprint
from .checkpoint import CheckpointInfo, create_checkpoint, verify_checkpoint
from .compilers import (
    ToolchainConfig, assess_compatibility, default_runner, probe_toolchain, select_backend, toolchain_requirements,
)
from .classify import classify
from .errors import DiagnosticSink, IngestionError, UnsupportedInputError
from .findings import FileScan, ScanProblem
from .gitingest import _hardened_env, _rev_parse, ingest_git
from .hashing import sha256_bytes
from .inventory import FileRecord, list_directories
from .limits import DEFAULT_LIMITS, Limits
from .model import IngestionResult, ingest_directory, rmtree_force
from .remotegit import NetworkPolicy, ingest_remote_git
from .report import build_report, render_summary
from .runtime_deps import dialect_report
from .resolve import build_graph, program_library_orders
from .scan_cobol import scan_cobol
from .scan_infra import scan_bms, scan_build, scan_other_language, scan_sql
from .scan_jcl import scan_control_text, scan_jcl
from .textio import decode_source
from .zipsource import ingest_zip
from .graph import stamp_graph_id

__all__ = ["STEP_IDS", "DiscoveryRequest", "DiscoveryResult", "Progress", "discover", "is_remote_git", "scan_file"]

STEP_IDS: tuple[tuple[str, str], ...] = (
    ("ingestion", "Ingestion"),
    ("checkpoint", "Immutable checkpoint"),
    ("scanning_inventory", "Scanning and inventory"),
    ("dependency_analysis", "Dependency analysis"),
    ("compiler_discovery", "Compiler and application discovery"),
    ("report", "Discovery report"),
)
#: ``(step_id, status, message)`` with status in running|completed|warning|failed.
Progress = Callable[[str, str, str], None]

_KINDS = ("git", "zip", "directory")
_REMOTE_RE = re.compile(r"^(https?://|ssh://|git://|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:)", re.IGNORECASE)
_HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
_OUTPUTS = {
    "report": "discovery-report.json", "graph": "dependency-graph.json", "inventory": "file-inventory.json",
    "unresolved": "unresolved-references.json", "summary": "discovery-summary.md", "compatibility": "compiler-compatibility.json",
    "applications": "applications.json", "readiness": "transformation-readiness.json",
    "blueprint": "application-blueprint.json",
}
_RUN_RECORD = "run-record.json"
_SOURCE_BLOCKER_CLASSES = frozenset({"cobol", "copybook", "jcl-job", "jcl-proc", "bms", "sql", "idcams", "sort-control"})


@dataclass(frozen=True)
class DiscoveryRequest:
    """What to ingest.  ``network_policy`` is operator-set, never user input."""

    kind: str  # "git" | "zip" | "directory"
    source: str  # URL, archive path or directory path
    ref: str | None = None
    label: str | None = None
    allow_ssh: bool = False
    network_policy: NetworkPolicy = field(default_factory=NetworkPolicy)

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise UnsupportedInputError(f"unknown input kind {self.kind!r}", code="UNKNOWN_INPUT_KIND")


@dataclass
class DiscoveryResult:
    checkpoint: CheckpointInfo
    outdir: Path
    report: dict[str, Any]
    outputs: dict[str, str]
    reused: bool
    #: ``PROGRAM-ID -> library orders`` from the discovery build (plain data for the engine bridge; see
    #: :func:`enterprise.discovery.resolve.program_library_orders`).  Not part of the report or any artefact.
    library_orders: dict[str, tuple[tuple[str, ...], ...]] = field(default_factory=dict)


def is_remote_git(source: str) -> bool:
    return bool(_REMOTE_RE.match(source.strip()))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Steps:
    """Progress reporting plus the wall-clock run record (never part of the deterministic artefacts)."""

    def __init__(self, progress: Progress | None) -> None:
        self._progress = progress
        self.records: dict[str, dict[str, Any]] = {}
        self._started: dict[str, float] = {}
        self.current = ""

    def emit(self, step: str, status: str, message: str = "") -> None:
        now = time.monotonic()
        if status == "running":
            self.current, self._started[step] = step, now
            self.records[step] = {"id": step, "status": status, "message": message, "started_at": _utc_now(), "duration_ms": 0}
        else:
            if self.current == step:
                self.current = ""
            record = self.records.setdefault(step, {"id": step, "started_at": _utc_now(), "duration_ms": 0})
            record.update(status=status, message=message, duration_ms=int((now - self._started.get(step, now)) * 1000))
        if self._progress is not None:
            try:
                self._progress(step, status, message)
            except Exception:  # noqa: BLE001 - a progress callback must not break a run
                pass


def _origin_label(source: str, kind: str) -> str:
    """A short, path-free label (never an absolute path or a credential-bearing URL)."""
    text = source[7:] if source.startswith("file://") else source
    name = text.rstrip("/\\").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if kind == "git" and name.endswith(".git"):
        name = name[:-4]
    return name or kind


def _resolve_local_ref(repo: str, ref: str, staging: Path) -> str:
    if ref.startswith("-") or any(c.isspace() or ord(c) < 32 for c in ref):
        raise UnsupportedInputError(f"invalid git ref {ref!r}", code="INVALID_REF", path=ref)
    path = repo[7:] if repo.lower().startswith("file://") else repo
    return _rev_parse(Path(path), _hardened_env(staging), f"{ref}^{{commit}}", ref)


def _ingest(request: DiscoveryRequest, staging: Path, limits: Limits, sink: DiagnosticSink
            ) -> tuple[IngestionResult, Path | None]:
    label = request.label or _origin_label(request.source, request.kind)
    if request.kind == "zip":
        archive = Path(request.source)
        result = ingest_zip(archive, staging, origin=label, limits=limits, sink=sink)
        return result, result.original_archive
    if request.kind == "git":
        if is_remote_git(request.source):
            return ingest_remote_git(request.source, staging, ref=request.ref, allow_ssh=request.allow_ssh,
                                     policy=request.network_policy, limits=limits, sink=sink), None
        commit = None
        if request.ref:
            commit = request.ref if _HEX40.match(request.ref) else _resolve_local_ref(request.source, request.ref, staging)
        result = ingest_git(request.source, staging, commit=commit, limits=limits, sink=sink)
        result.ref = request.ref or ""
        return result, None
    root = Path(request.source).resolve()
    if not root.is_dir():
        raise UnsupportedInputError(f"not a directory: {root.name}", code="INPUT_NOT_FOUND", path=root.name)
    return ingest_directory(root, origin=label, kind="directory", skip=(".git",), skip_reason="version-control metadata",
                            sink=sink, limits=limits), None


def _validate_request(request: DiscoveryRequest, store: Path) -> None:
    if request.ref and request.kind != "git":
        raise UnsupportedInputError(f"a ref applies to git inputs only, not {request.kind!r}", code="REF_NOT_APPLICABLE",
                                    path=request.ref)
    if request.kind == "directory":
        root, target = Path(request.source).resolve(), store.resolve()
        if target == root or root in target.parents:
            raise UnsupportedInputError("the store must not lie inside the input directory", code="STORE_INSIDE_INPUT")


# --- scanning -----------------------------------------------------------------------------------------------------------


def scan_file(path: str, cls: str, text: str) -> FileScan | None:
    """Run the scanner that matches ``cls``; ``None`` when the class has no scanner."""
    if cls == "cobol":
        return scan_cobol(path, text)
    if cls == "copybook":
        return scan_cobol(path, text, copybook=True)
    if cls in ("jcl-job", "jcl-proc"):
        return scan_jcl(path, text)
    if cls == "bms":
        return scan_bms(path, text)
    if cls == "sql":
        return scan_sql(path, text)
    if cls in ("idcams", "sort-control"):
        return scan_control_text(path, "idcams" if cls == "idcams" else "sort", text)
    if cls in ("build-config", "script", "ci-config", "config"):
        return scan_build(path, text)
    if cls in ("assembler", "pli", "rexx", "clist"):
        return scan_other_language(path, text, cls)
    return None


def _scan_record(source_root: Path, file: Any, limits: Limits) -> FileRecord:
    record = FileRecord(path=file.path, sha256=file.sha256, size=file.size)
    if file.size > limits.max_source_bytes:
        guess = classify(file.path, None)
        record.cls, record.evidence = guess.cls, guess.evidence + ("larger than max_source_bytes; content not read",)
        record.blocker = f"size {file.size} exceeds max_source_bytes={limits.max_source_bytes}" \
            if guess.cls in _SOURCE_BLOCKER_CLASSES | {"unknown"} else ""  # an oversized unknown member may be COBOL: never silently dropped
        return record
    try:
        data = (source_root / file.path).read_bytes()
    except OSError:
        raise IngestionError("a preserved file could not be read", code="CHECKPOINT_TAMPERED", path=file.path) from None
    if sha256_bytes(data) != file.sha256:
        raise IngestionError("preserved bytes differ from the recorded hash", code="CHECKPOINT_TAMPERED", path=file.path)
    decoded = decode_source(data)
    guess = classify(file.path, None if decoded.binary else decoded.text, binary=decoded.binary)
    record.cls, record.evidence = guess.cls, guess.evidence
    record.encoding, record.encoding_confidence = decoded.encoding, decoded.confidence
    if decoded.note:
        record.evidence += (decoded.note,)
    if decoded.binary:
        return record
    try:
        scan = scan_file(file.path, guess.cls, decoded.text)
    except Exception as exc:  # noqa: BLE001 - a scanner defect must surface as a finding, never as a silent skip
        scan = FileScan(path=file.path, problems=[ScanProblem(file.path, 1, "SCANNER_FAILED",
                                                              f"{type(exc).__name__} while scanning as {guess.cls}")])
    if scan is not None:
        record.scan, record.source_format, record.line_count = scan, scan.source_format, scan.line_count
    return record


def _analyse(ingestion: IngestionResult, source_root: Path, limits: Limits, steps: _Steps
             ) -> tuple[list[FileRecord], list[Any], Any]:
    steps.emit("scanning_inventory", "running")
    records = [_scan_record(source_root, f, limits) for f in sorted(ingestion.files, key=lambda f: f.path)]
    directories = list_directories(source_root, records)
    steps.emit("scanning_inventory", "completed", f"{len(records)} files, {len(directories)} directories")
    steps.emit("dependency_analysis", "running")
    build = build_graph(records)
    steps.emit("dependency_analysis", "completed", f"{build.graph.stats()['edges']} dependency edges")
    return records, directories, build


# --- output -------------------------------------------------------------------------------------------------------------


_PROBE_TTL_SECONDS = 300.0
_probe_cache: dict[tuple[str, str], tuple[float, list[Any]]] = {}


def _probes(config: ToolchainConfig) -> list[Any]:
    """Tool probes; the default (real) probe is cached briefly because it may start a container, injected ones never are."""
    runner = config.runner or default_runner
    kwargs: dict[str, Any] = {"which": config.which} if config.which else {}
    if config.runner is not None or config.which is not None:
        return probe_toolchain(runner=runner, image=config.image, use_container=True, **kwargs)
    key = (config.backend, config.image)
    cached = _probe_cache.get(key)
    if cached and time.monotonic() - cached[0] < _PROBE_TTL_SECONDS:
        return cached[1]
    probes = probe_toolchain(runner=runner, image=config.image, use_container=config.backend in ("auto", "container"))
    _probe_cache[key] = (time.monotonic(), probes)
    return probes


def _compiler_discovery(records: list[FileRecord], build: Any, source_root: Path, config: ToolchainConfig
                         ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Required toolchains, open-source tool availability and the syntax-only compatibility check; never raises for a missing tool."""
    runner = config.runner or default_runner
    probes = _probes(config) if config.backend != "none" else []
    backend = select_backend(probes, preference=config.backend, image=config.image)
    dialects = {str(f["file"]): str(f["primary"]) for f in dialect_report(records)["files"]}  # type: ignore[attr-defined]
    compatibility = assess_compatibility(records, build.graph, source_root, backend, dialects=dialects, probes=probes, runner=runner,
                                         budget_seconds=config.budget_seconds)
    return {"required": toolchain_requirements(records), "tools": [p.as_dict() for p in probes]}, compatibility


def _dump(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def _scrub(value: Any, roots: tuple[str, ...]) -> Any:
    """Remove local locations from diagnostics so artefacts never name the store, staging area or input path."""
    if isinstance(value, str):
        for root in sorted({r for r in roots if r}, key=len, reverse=True):
            for form in {root, root.replace("\\", "/")}:
                value = value.replace(form, "<local>")
        return value
    if isinstance(value, list):
        return [_scrub(item, roots) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item, roots) for key, item in value.items()}
    return value


def _publish(report: dict[str, Any], records: list[FileRecord], directories: list[Any], build: Any, outdir: Path,
             roots: tuple[str, ...]) -> dict[str, str]:
    outdir.mkdir(parents=True, exist_ok=True)
    unresolved = {"ambiguous": [e.as_dict() for e in build.graph.ambiguous()],
                  "unresolved": [e.as_dict() for e in build.graph.unresolved()]}
    # The graph document is scrubbed like every other artefact, and its content address is stamped *after* that
    # rewrite so ``header.graph_id`` always names the bytes actually written (Layer 3 acceptance criterion 1).
    graph_document = _scrub(build.graph.to_dict(), roots)
    graph_id = stamp_graph_id(graph_document)
    report.setdefault("dependency_graph", {})["graph_id"] = graph_id
    scrubbed_report = _scrub(report, roots)
    payloads = {
        "report": _dump(scrubbed_report), "graph": _dump(graph_document),
        "inventory": _dump({"directories": [d.as_dict() for d in directories], "files": [r.as_dict() for r in records],
                            "schema_version": "systemaops.file-inventory/1.0"}),
        "unresolved": _dump({**unresolved, "schema_version": "systemaops.unresolved-references/1.0"}),
        "summary": render_summary(report),
        "compatibility": _dump({**report["compatibility"], "schema_version": "systemaops.compiler-compatibility/1.0",
                                "toolchain": report["toolchain"]}),
        "applications": _dump({**report["applications"], "schema_version": "systemaops.applications/1.0"}),
        "readiness": _dump({**report["readiness"], "schema_version": "systemaops.transformation-readiness/1.0"}),
    }
    # Derived last: it hashes the exact text of every other artefact, so its digests name bytes that exist on disk.
    payloads["blueprint"] = _dump(build_blueprint(
        scrubbed_report, graph_document, {name: payloads[name] for name in BLUEPRINT_ARTEFACTS},
        {name: _OUTPUTS[name] for name in BLUEPRINT_ARTEFACTS}))
    outputs = {}
    for key, text in payloads.items():
        target = outdir / _OUTPUTS[key]
        outputs[key] = _OUTPUTS[key]
        if _already_written(target, text):  # a concurrent run of the same checkpoint produced the identical artefact
            continue
        temporary = outdir / f".{_OUTPUTS[key]}.{os.getpid()}.{threading.get_ident()}.tmp"
        temporary.write_text(text, encoding="utf-8", newline="\n")
        _replace_with_retry(temporary, target)
    return outputs


def _replace_with_retry(source: Path, target: Path) -> None:
    """``os.replace``; on Windows a concurrent reader holding *target* open makes it fail transiently."""
    for attempt in range(8):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 7:
                source.unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (attempt + 1))


def _already_written(target: Path, text: str) -> bool:
    try:
        return target.read_text(encoding="utf-8") == text
    except (OSError, UnicodeDecodeError):
        return False


def _write_run_record(outdir: Path, info: CheckpointInfo, steps: _Steps) -> str:
    record = {"checkpoint_id": info.checkpoint_id, "ingested_at": _utc_now(),
              "steps": [steps.records[sid] for sid, _ in STEP_IDS if sid in steps.records],
              "tool_versions": {"systemaops-discovery": __version__}}
    (outdir / _RUN_RECORD).write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return _RUN_RECORD


def discover(request: DiscoveryRequest, store: Path | str, *, progress: Progress | None = None,
             limits: Limits = DEFAULT_LIMITS,
             toolchain: ToolchainConfig | None = None) -> DiscoveryResult:
    """Run the whole discovery workflow and return the report.

    Raises :class:`IngestionError` on any refusal; staging is always removed and no report is written for a refused
    input.  Any other exception also reports its step as ``failed`` before propagating.
    """
    store = Path(store)
    _validate_request(request, store)
    store.mkdir(parents=True, exist_ok=True)
    steps, sink = _Steps(progress), DiagnosticSink(limits.max_diagnostics)
    staging = Path(tempfile.mkdtemp(prefix="discovery-stage-", dir=store))
    try:
        steps.emit("ingestion", "running")
        ingestion, archive = _ingest(request, staging, limits, sink)
        steps.emit("ingestion", "completed", f"{ingestion.entry_count} files from {ingestion.kind}")

        steps.emit("checkpoint", "running")
        label = ingestion.remote or request.label or _origin_label(request.source, request.kind)
        info = create_checkpoint(ingestion, store, origin_label=label, ref=ingestion.ref or (request.ref or ""),
                                 tree_id=ingestion.tree_id, original_archive=archive)
        steps.emit("checkpoint", "completed", f"{info.checkpoint_id}{' (reused)' if info.reused else ''}")

        records, directories, build = _analyse(ingestion, info.source_root, limits, steps)

        steps.emit("report", "running")
        report_ok = verify_checkpoint(info.path).ok
        # Provenance comes from the stored checkpoint so a reused checkpoint can never contradict its own report.
        provenance: dict[str, object] = {"archive_sha256": info.archive_sha256, "commit": info.commit,
                      "commit_timestamp": info.commit_timestamp, "kind": info.source_kind, "origin": info.origin,
                      "ref": info.ref, "remote": info.origin if info.source_kind == "git" and "://" in info.origin else "",
                      "tree_id": info.tree_id}
        roots = (str(info.source_root), str(staging), str(ingestion.staging_root), str(store), str(store.resolve()))
        steps.emit("compiler_discovery", "running")
        toolchain_info, compatibility = _compiler_discovery(records, build, info.source_root, toolchain or ToolchainConfig.from_environment())
        steps.emit("compiler_discovery", "completed", f"{compatibility['backend']['kind']} backend; {len(compatibility['programs'])} programs")
        # Document provenance (Layer 3): the graph names the checkpoint and source digest it was derived from, so a
        # reader can tie any ``graph_id`` back to the immutable input without trusting a side channel.
        build.graph.checkpoint_id = info.checkpoint_id
        build.graph.source_digest = info.source_digest
        build.graph.created_from = "discovery"
        applications = build_applications(records, build.graph, compatibility)
        link_applications(build.graph, applications)
        report = build_report(checkpoint=info.as_dict(), provenance=provenance, records=records, directories=directories,
                              build=build, diagnostics=_scrub(sink.to_list(), roots), limits=limits.as_dict(),
                              checkpoint_ok=report_ok, tool_version=__version__, toolchain=toolchain_info,
                              compatibility=compatibility, applications=applications)
        outdir = store / "discoveries" / info.checkpoint_id
        outputs = _publish(report, records, directories, build, outdir, roots)
        steps.emit("report", "completed", str(report["completeness"]["status"]))
        outputs["run_record"] = _write_run_record(outdir, info, steps)
        return DiscoveryResult(info, outdir, report, outputs, info.reused, program_library_orders(build))
    except IngestionError as exc:
        steps.emit(steps.current or "ingestion", "failed", exc.code)
        raise
    except Exception:
        steps.emit(steps.current or "ingestion", "failed", "INTERNAL_ERROR")
        raise
    finally:
        try:
            rmtree_force(staging)
        except OSError:  # pragma: no cover - rmtree_force is already best-effort
            pass
