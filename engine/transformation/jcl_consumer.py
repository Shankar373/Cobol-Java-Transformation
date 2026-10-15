"""JCL consumer integration module.

Consumer-side boundary for the JCL modernization lane.  This module calls
the lane's public API (``JclDiscovery``, ``modernize_jcl``) and returns a
structured result that the control-plane layer can surface.

This module does NOT modify any shared files.  It is the single import
point for consumer-side code that needs the JCL modernization profile.

Usage::

    from engine.transformation.jcl_consumer import modernize_jcl_workload

    result = modernize_jcl_workload(
        source_path="/path/to/jcl/workspace",
        application_id="my-app",
    )
    print(result.status)         # "FULL" | "PARTIAL" | "EMPTY"
    print(result.profile)        # JclModernizationProfile
    print(result.diagnostics)    # tuple[JclDiagnostic, ...]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from engine.jcl.diagnostics import JclDiagnostic, JclDiagnosticCode
from engine.transformation.jcl_discovery import JclDiscovery, find_jcl_members
from engine.transformation.jcl_to_spring_batch import (
    JclModernizationProfile,
    modernize_jcl,
)


@dataclass(frozen=True)
class JclConsumerResult:
    """Structured result of JCL modernization consumed by the control plane.

    Attributes:
        application_id: identifier for the originating application.
        source_path: resolved source directory used for discovery.
        status: ``"FULL"`` | ``"PARTIAL"`` | ``"EMPTY"`` (from the profile).
        has_errors: whether any ERROR-level diagnostics were emitted.
        has_warnings: whether any WARNING-level diagnostics were emitted.
        job_count: number of JCL jobs discovered.
        step_count: total number of JCL steps across all jobs.
        supported_constructs: explicit contract of supported constructs.
        unsupported_constructs: explicit contract of unsupported constructs.
        diagnostics: full diagnostic trail from the modernization lane.
        profile: the full ``JclModernizationProfile`` (representation +
            diagnostics + status).  Consumer code may inspect this directly.
    """

    application_id: str
    source_path: str
    status: str
    has_errors: bool
    has_warnings: bool
    job_count: int
    step_count: int
    supported_constructs: tuple[str, ...] = field(default_factory=tuple)
    unsupported_constructs: tuple[str, ...] = field(default_factory=tuple)
    diagnostics: tuple[JclDiagnostic, ...] = field(default_factory=tuple)
    profile: JclModernizationProfile | None = None


def _result_for(profile, application_id: str, source_path: str) -> JclConsumerResult:
    """Summarize a JCL modernization profile into its consumer result."""
    job_count = len(profile.application.jobs)
    step_count = sum(len(job.steps) for job in profile.application.jobs)

    return JclConsumerResult(
        application_id=application_id,
        source_path=source_path,
        status=profile.status,
        has_errors=profile.has_errors,
        has_warnings=profile.has_warnings,
        job_count=job_count,
        step_count=step_count,
        supported_constructs=profile.supported_constructs,
        unsupported_constructs=profile.unsupported_constructs,
        diagnostics=profile.diagnostics,
        profile=profile,
    )


def modernize_jcl_workload(
    source_path: str | Path,
    application_id: str = "jcl-modernization",
    base_package: str = "com.generated.batch",
) -> JclConsumerResult:
    """Discover and modernize JCL workload from a source directory.

    This is the single entry point for consumer-side integration.  It:

    1. Discovers JCL jobs in ``source_path`` via ``JclDiscovery``.
    2. Reads raw JCL source files for unsupported-construct scanning.
    3. Calls ``modernize_jcl`` to produce the Spring Batch representation.
    4. Returns a structured ``JclConsumerResult`` that the control plane
       can surface through the API without modifying any shared files.

    Args:
        source_path: directory of JCL members (shared BL-063 rule:
            case-insensitive ``.jcl`` / ``.jcllib`` suffixes, plus
            extensionless members whose content starts with ``//``).
        application_id: identifier for the originating application.
        base_package: target Java package namespace for the batch layer.

    Returns:
        A ``JclConsumerResult`` carrying the profile, diagnostics, and
        summary statistics.

    Raises:
        FileNotFoundError: if ``source_path`` does not exist.
        ValueError: if ``source_path`` is not a directory.
    """
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Source path does not exist: {source}")
    if not source.is_dir():
        raise ValueError(f"Source path is not a directory: {source}")

    # 1. Discover JCL jobs (shared BL-063 member rule).
    discovery = JclDiscovery()
    jcl_app = discovery.discover(source)

    # 2. Read every member for the unsupported-construct scan.  Keys are
    #    member-relative paths (not basenames), so colliding basenames
    #    can never overwrite each other (BL-063).  Undecodable members
    #    are diagnosed fail-closed instead of crashing the run or being
    #    silently dropped.
    raw_sources: dict[str, str] = {}
    decode_diagnostics: list[JclDiagnostic] = []
    for jcl_file in find_jcl_members(source):
        key = jcl_file.relative_to(source).as_posix()
        try:
            raw_sources[key] = jcl_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            decode_diagnostics.append(
                JclDiagnostic.error(
                    JclDiagnosticCode.SOURCE_DECODE_FAILED,
                    f"JCL member '{key}' is not valid UTF-8; excluded from "
                    "the IR and surfaced here so it is never silently lost",
                )
            )
        except OSError as exc:
            decode_diagnostics.append(
                JclDiagnostic.error(
                    JclDiagnosticCode.SOURCE_DECODE_FAILED,
                    f"JCL member '{key}' could not be read: {exc}",
                )
            )

    # 3. Modernize.
    profile = modernize_jcl(
        jcl_app,
        raw_sources,
        application_id=application_id,
        base_package=base_package,
        pre_diagnostics=tuple(decode_diagnostics),
    )

    # 4. Summarize.
    return _result_for(profile, application_id, str(source.resolve()))


def modernize_jcl_from_sources(
    sources: dict[str, str],
    application_id: str = "jcl-modernization",
    base_package: str = "com.generated.batch",
) -> JclConsumerResult:
    """Modernize JCL from in-memory source strings (no filesystem required).

    Alternative entry point for callers that already have JCL source text
    (e.g. from a ZIP upload or an in-memory buffer).  Discovery runs over
    the in-memory sources.

    Args:
        sources: mapping of filename to JCL source text.
        application_id: identifier for the originating application.
        base_package: target Java package namespace for the batch layer.

    Returns:
        A ``JclConsumerResult`` carrying the profile, diagnostics, and
        summary statistics.
    """
    from engine.transformation.jcl_parser import JclParser

    # 1. Parse JCL from in-memory sources.
    jcl_app = JclParser().parse_application(sources)

    # 2. Modernize (raw_sources = sources for unsupported scanning).
    profile = modernize_jcl(
        jcl_app,
        sources,
        application_id=application_id,
        base_package=base_package,
    )

    # 3. Summarize.
    return _result_for(profile, application_id, "(in-memory)")
