"""CALL passing modes — independent runtime proof per mode (BY REFERENCE /
BY CONTENT / BY VALUE).

Each mode has its OWN fixture (``fixtures/workload-by-<mode>/cobol``) with
its own CALL statement and its own callee. The mode under test is parsed
from that fixture's own source; no mode's expected behaviour is ever derived
from another mode's fixture or test.

Observable contract (two-module link MAIN -> MODIFY, MODIFY adds 50 to its
linkage item):

* BY REFERENCE — the callee mutates the caller's item:
  ``AFTER CALL VALUE=0150``;
* BY CONTENT   — the callee receives a read-only copy:
  ``AFTER CALL VALUE=0100``;
* BY VALUE     — GnuCOBOL 3.1.2 (the only available COBOL runtime) declares
  its BY VALUE implementation unfinished and aborts with SIGSEGV while the
  callee reads the parameter (pinned by
  ``test_call_passing_mode_oracle_proof`` for the same fixture). The oracle
  is therefore asserted to abort, the generated Java is asserted against the
  documented no-write-back lowering, and the differential pipeline verdict
  for BY VALUE must fail closed to UNAVAILABLE — never VERIFIED.


Docker-free classes pin parser/mapper behaviour per mode (including the
caller-side sync-out, which must exist only for BY REFERENCE). Docker-gated
classes run the actual COBOL in the digest-pinned GnuCOBOL oracle, compile
and run the generated Spring Boot JAR in the digest-pinned Temurin lane,
and seal the differential verdict through the full pipeline with a complete
evidence manifest.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from engine.candidate.docker_spring_boot_adapter import DockerSpringBootCandidateAdapter
from engine.domain.identities import RunId, VerdictState
from engine.oracle.adapter import OracleAdapterConfig
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import CallStatement
from engine.transformation.java_to_spring_mapping import (
    map_java_application_to_spring_boot,
)
from engine.transformation.spring_boot_generator import SpringBootGenerator

# fixture-dir-suffix -> (mode token, caller sync-out expected?, expected
# "AFTER CALL VALUE=" payload, expected callee "CHANGED" line fragment).
# Expected lines match the fixtures' DISPLAY literals exactly: the output
# concatenates the literal and the zero-padded value with no space
# ("BEFORE CALL VALUE=0100"), as byte-verified by
# test_call_passing_mode_oracle_proof.py.
MODES = {
    "by-reference": ("REFERENCE", True, "0150", "MODIFY CHANGED VALUE=0150"),
    "by-content": ("CONTENT", False, "0100", "MODIFY CHANGED LOCAL COPY=0150"),
    "by-value": ("VALUE", False, "0100", "MODIFY CHANGED LOCAL COPY=0150"),
}

#: Documented BY VALUE lowering (GnuCOBOL cannot serve as a BY VALUE oracle).
BY_VALUE_DOCUMENTED_STDOUT = (
    "MAIN STARTED",
    "BEFORE CALL VALUE=0100",
    "MODIFY STARTED",
    "MODIFY RECEIVED VALUE=0100",
    "MODIFY CHANGED LOCAL COPY=0150",
    "AFTER CALL VALUE=0100",
)

SYNC_OUT_LINE = "WS_VALUE = Modify.LS_VALUE"


def _cobol_dir(fixture_suffix: str) -> Path:
    return Path("fixtures") / f"workload-{fixture_suffix}" / "cobol"


def _call_statement(fixture_suffix: str) -> CallStatement:
    """The CALL statement parsed from THIS fixture's own MAIN.cob."""
    source = (_cobol_dir(fixture_suffix) / "MAIN.cob").read_text()
    program = CobolParser().parse(source)
    calls = [
        s
        for para in program.paragraphs
        for s in para.statements
        if isinstance(s, CallStatement)
    ]
    assert len(calls) == 1, f"expected exactly one CALL in {fixture_suffix}"
    return calls[0]


def _generate_project(fixture_suffix: str):
    cobol_dir = _cobol_dir(fixture_suffix)
    app = ApplicationDiscovery().discover(
        str(cobol_dir), application_id=f"call-modes-{fixture_suffix}"
    )
    gen = ApplicationGenerator().generate(
        app, entrypoint="Main", source_root=cobol_dir
    )
    assert gen.success, gen.errors
    spring = map_java_application_to_spring_boot(
        gen.java_application, entry_program="Main", copybook_models=gen.copybook_models
    )
    files = SpringBootGenerator().generate_project(spring)
    return app, gen, files


def _service(files, class_name: str) -> str:
    return next(
        f.source_code
        for f in files
        if f.path.endswith(f"service/{class_name}.java")
    )


def _source_hash(fixture_suffix: str) -> str:
    h = hashlib.sha256()
    for name in sorted(p.name for p in _cobol_dir(fixture_suffix).glob("*.cob")):
        h.update((_cobol_dir(fixture_suffix) / name).read_bytes())
    return h.hexdigest()


def _stage(files, fixture_suffix: str):
    from engine.candidate.adapter import CandidateManifest

    tmpdir = tempfile.mkdtemp(prefix=f"call-modes-{fixture_suffix}-")
    for f in files:
        fp = Path(tmpdir) / f.path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(f.source_code)
    manifest = CandidateManifest(
        candidate_id=f"generated-springboot-call-modes-{fixture_suffix}",
        workload_id=f"call-modes-{fixture_suffix}",
        source_hash=_source_hash(fixture_suffix),
        generated_files=[f.path for f in files],
        entrypoint="com.generated.app.Application",
        java_version="21",
        dependencies=["spring-boot-starter", "spring-context"],
    )
    return tmpdir, manifest


def _workload(fixture_suffix: str):
    from engine.contracts.models import NormalizationPolicy, OrderingPolicy
    from engine.workload import WorkloadArtifact, WorkloadDefinition

    return WorkloadDefinition(
        workload_id=f"call-modes-{fixture_suffix}",
        description=(
            f"CALL {MODES[fixture_suffix][0]} differential runtime proof "
            "(caller data protected or propagated)"
        ),
        artifacts=(
            WorkloadArtifact(
                logical_name=f"call-modes-{fixture_suffix}-stdout",
                artifact_type="STDOUT",
                comparator_id="stdout-exact",
                normalization=NormalizationPolicy(
                    allowed_normalizations=("crlf_to_lf",)
                ),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name=f"call-modes-{fixture_suffix}-stderr",
                artifact_type="STDERR",
                comparator_id="stderr-exact",
                normalization=NormalizationPolicy(
                    allowed_normalizations=("crlf_to_lf",)
                ),
                ordering=OrderingPolicy(order="SEQUENTIAL"),
            ),
            WorkloadArtifact(
                logical_name=f"call-modes-{fixture_suffix}-exit-status",
                artifact_type="EXIT_STATUS",
                comparator_id="exit-status-exact",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Docker-free: per-mode parser / mapper contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_suffix,spec", MODES.items())
def test_mode_is_parsed_from_the_fixture_own_source(fixture_suffix, spec):
    mode, *_ = spec
    raw = (_cobol_dir(fixture_suffix) / "MAIN.cob").read_text().upper()
    assert f"BY {mode}" in raw  # the fixture really declares this mode
    stmt = _call_statement(fixture_suffix)
    assert list(stmt.passing_modes) == [mode]


@pytest.mark.parametrize("fixture_suffix,spec", MODES.items())
def test_caller_sync_out_exists_only_for_reference(fixture_suffix, spec):
    _, _, files = _generate_project(fixture_suffix)
    main_java = _service(files, "Main")
    _, sync_out_expected, *_ = spec
    if sync_out_expected:
        assert SYNC_OUT_LINE in main_java, main_java
    else:
        assert SYNC_OUT_LINE not in main_java, main_java


@pytest.mark.parametrize("fixture_suffix", MODES)
def test_callee_has_a_single_entry_method(fixture_suffix):
    import re

    _, _, files = _generate_project(fixture_suffix)
    modify_java = _service(files, "Modify")
    entries = re.findall(r"public (?:static )?void MAIN_LOGIC\(", modify_java)
    assert len(entries) == 1, modify_java


def test_the_three_modes_are_independently_recognized():
    """No inference across modes: the three fixtures parse to three distinct
    passing-mode sets, each read from its own source text."""
    parsed = {fx: tuple(_call_statement(fx).passing_modes) for fx in MODES}
    assert parsed == {
        "by-reference": ("REFERENCE",),
        "by-content": ("CONTENT",),
        "by-value": ("VALUE",),
    }


def test_by_value_and_by_content_protect_caller_at_mapper_level():
    """Independent per-mode mapper checks — BY VALUE is proven from the
    BY VALUE fixture's own generated code, never inferred from BY CONTENT."""
    for fx in ("by-content", "by-value"):
        _, _, files = _generate_project(fx)
        assert SYNC_OUT_LINE not in _service(files, "Main"), fx
    # ...and BY REFERENCE from its own fixture, positively.
    _, _, files = _generate_project("by-reference")
    assert SYNC_OUT_LINE in _service(files, "Main")


# ---------------------------------------------------------------------------
# Docker-gated: oracle semantics + Java build/run + full differential verdict
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker not available"
)


@needs_docker
@pytest.mark.parametrize("fixture_suffix,spec", MODES.items())
def test_oracle_cobol_semantics_per_mode(fixture_suffix, spec):
    """The independent GnuCOBOL oracle establishes the reference semantics
    for THIS mode from the original COBOL sources."""
    mode, sync_out, after_value, changed_line = spec
    adapter = DockerOracleAdapter(OracleAdapterConfig(
        oracle_id="gnucobol-3.1.2", image_digest="",
        compiler_version="3.1.2.0", timeout_seconds=120,
    ))
    outcome = adapter.execute(
        RunId(value=f"call-modes-oracle-{fixture_suffix}-001"),
        str(_cobol_dir(fixture_suffix)),
    )
    if fixture_suffix == "by-value":
        # Blocker pin (mirrors test_call_passing_mode_oracle_proof on the
        # same fixture): GnuCOBOL 3.1.2 BY VALUE aborts; no oracle behavior
        # exists, so no equivalence claim may be derived from this lane.
        assert outcome.exit_code != 0
        stderr = outcome.stderr.decode(errors="replace")
        assert "SIGSEGV" in stderr or "unallocated memory" in stderr
        assert "MODIFY CHANGED LOCAL COPY=0150" not in (
            outcome.stdout.decode(errors="replace")
        )
        return
    assert outcome.exit_code == 0, outcome.stderr.decode(errors="replace")[:800]
    stdout = outcome.stdout.decode(errors="replace")
    lines = [ln.strip() for ln in stdout.splitlines()]
    assert any(ln.endswith(f"AFTER CALL VALUE={after_value}") for ln in lines), lines
    assert any(changed_line in ln for ln in lines), lines


@needs_docker
@pytest.mark.parametrize("fixture_suffix,spec", MODES.items())
def test_generated_java_matches_oracle_behaviour_per_mode(fixture_suffix, spec):
    """Generated Spring Boot JAR runs in the digest-pinned Temurin lane and
    exhibits the same mode-specific observable behaviour as the oracle."""
    mode, sync_out, after_value, changed_line = spec
    _, _, files = _generate_project(fixture_suffix)
    tmpdir, manifest = _stage(files, fixture_suffix)
    adapter = DockerSpringBootCandidateAdapter()
    compiled = adapter.compile(candidate_path=tmpdir, manifest=manifest)
    assert compiled.success is True, compiled.compilation_errors
    result = adapter.execute(
        RunId(value=f"call-modes-exec-{fixture_suffix}-001"),
        compiled_path=tmpdir, manifest=manifest,
    )
    assert result.exit_code == 0
    stdout = result.stdout.decode(errors="replace")
    if fixture_suffix == "by-value":
        # GnuCOBOL 3.1.2 aborts on BY VALUE (see the oracle test), so the
        # Java lane is compared against the documented no-write-back
        # lowering — never against the aborted oracle run.
        assert stdout.splitlines() == list(BY_VALUE_DOCUMENTED_STDOUT)
        return
    lines = [ln.strip() for ln in stdout.splitlines()]
    assert any(ln.endswith(f"AFTER CALL VALUE={after_value}") for ln in lines), lines
    assert any(changed_line in ln for ln in lines), lines


@needs_docker
@pytest.mark.parametrize("fixture_suffix", MODES)
def test_full_differential_pipeline_is_verified_per_mode(fixture_suffix):
    """End-to-end: oracle execution vs candidate execution, declared artifact
    comparison (STDOUT/STDERR/EXIT), sealed evidence manifest.

    BY REFERENCE / BY CONTENT: the oracle and candidate both execute and the
    verdict must be VERIFIED.  BY VALUE: the oracle aborts (SIGSEGV), so the
    verdict must fail closed to UNAVAILABLE — an unavailable oracle can
    never certify equivalence.
    """
    _, _, files = _generate_project(fixture_suffix)
    tmpdir, _ = _stage(files, fixture_suffix)
    config = PipelineConfig(
        workload_id=f"call-modes-{fixture_suffix}",
        cobol_source_path=str(_cobol_dir(fixture_suffix)),
        java_candidate_path=tmpdir,
        java_entrypoint="com.generated.app.Application",
        workload=_workload(fixture_suffix),
        use_docker_java=True,
    )
    pipeline = VerticalSlicePipeline(
        config, candidate_adapter=DockerSpringBootCandidateAdapter()
    )
    result = pipeline.run()
    if fixture_suffix == "by-value":
        assert result.verdict.state == VerdictState.UNAVAILABLE, (
            result.verdict.reasons
        )
        assert result.evidence_manifest.is_complete()
        return
    assert result.verdict.state == VerdictState.VERIFIED, result.verdict.reasons
    assert result.evidence_manifest.is_complete()
