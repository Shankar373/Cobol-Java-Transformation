"""Phase 5 — final certification gates (2026-11-02).

* Every construct the registry classifies SUPPORTED must name at least one
  GnuCOBOL-backed proof: an oracle test file that really runs the GnuCOBOL
  image, or a corpus application whose source contains the construct and that
  is VERIFIED *and* independently AGREEs in the committed evidence on every
  proven runtime.  A new SUPPORTED key without proof fails this test; a proof
  that stops proving (file removed, app no longer VERIFIED) fails it too.
* Claims found false during certification stay refused: UNSTRING WITH
  POINTER / TALLYING IN and a two-pair REPLACE fail generation (GnuCOBOL's
  answer is pinned for the day they are implemented).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine.transformation.semantic_capability import (
    CONSTRUCT_REGISTRY,
    SUPPORTED_CONSTRUCTS,
    CapabilityLevel,
)

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs" / "reports" / "evidence" / "phase3"
RUNTIMES = ("spring_boot", "plain_java", "quarkus", "micronaut")
# ``ocesql-pg`` is the GnuCOBOL 3.1.2 image extended with OCESQL and PostgreSQL (embedded SQL).
_ORACLE_MARKERS = ("gnucobol-ocesql", "run_gnucobol", "DockerOracleAdapter", "ocesql-pg")

# construct -> proofs: ("test", path) | ("app", fixture, source regex)
PROOFS: dict[str, list[tuple]] = {
    "88-LEVEL": [("test", "tests/integration/test_structural_oracle_proof.py"),
                 ("app", "workload-level88", r"^\s+88\s")],
    "SET CONDITION TO TRUE": [("test", "tests/integration/test_structural_oracle_proof.py")],
    "ACCEPT": [("test", "tests/integration/test_accept_oracle_proof.py")],
    "INSPECT": [("test", "tests/integration/test_inspect_oracle.py")],
    "EXEC SQL": [("test", "tests/integration/test_sql_jdbc_oracle.py")],
    "ACCESS DYNAMIC": [("test", "tests/integration/test_indexed_relative_oracle_proof.py"),
                       ("app", "workload-indexed", r"ACCESS\s+(MODE\s+)?(IS\s+)?DYNAMIC")],
    "ORGANIZATION INDEXED": [("test", "tests/integration/test_indexed_relative_oracle_proof.py"),
                             ("app", "workload-indexed", r"ORGANIZATION\s+(IS\s+)?INDEXED")],
    "ORGANIZATION RELATIVE": [("test", "tests/test_relative_record_comparison.py"),
                              ("app", "workload-relative", r"ORGANIZATION\s+(IS\s+)?RELATIVE")],
    "RECORD KEY": [("test", "tests/integration/test_indexed_relative_oracle_proof.py"),
                   ("app", "workload-indexed", r"RECORD\s+KEY")],
    "START": [("test", "tests/integration/test_indexed_relative_oracle_proof.py"),
              ("app", "workload-indexed-rewrite-delete-start", r"\bSTART\b")],
    "INVALID KEY": [("app", "workload-start-invalidkey", r"INVALID\s+KEY")],
    "REWRITE": [("app", "workload-rewrite", r"\bREWRITE\b")],
    "DELETE": [("app", "workload-delete", r"\bDELETE\b")],
    "ADD": [("test", "tests/integration/test_numeric_oracle_proof.py"),
            ("app", "workload-add-giving-verified", r"\bADD\b")],
    "SUBTRACT": [("app", "workload-subtract", r"\bSUBTRACT\b")],
    "MULTIPLY": [("app", "workload-multiply", r"\bMULTIPLY\b")],
    "DIVIDE": [("app", "workload-divide-into-verified", r"\bDIVIDE\b")],
    "COMPUTE": [("test", "tests/test_size_error.py"),
                ("app", "workload-interest-accrual", r"\bCOMPUTE\b")],
    "ROUNDED": [("test", "tests/test_binary_usage_values.py"),
                ("test", "tests/test_size_error.py")],
    "SIZE ERROR": [("test", "tests/test_size_error.py"),
                   ("app", "workload-interest-accrual", r"SIZE\s+ERROR")],
    "BY CONTENT": [("test", "tests/integration/test_call_passing_mode_oracle_proof.py"),
                   ("app", "workload-by-content", r"BY\s+CONTENT")],
    "CALL": [("test", "tests/integration/test_call_chain_runtime.py"),
             ("app", "workload-call-chain", r"\bCALL\b")],
    "EXIT PROGRAM": [("test", "tests/transformation/test_false_success_regressions.py")],
    "GOBACK": [("test", "tests/transformation/test_false_success_regressions.py")],
    "OPEN": [("app", "workload-file-write-read", r"\bOPEN\b")],
    "CLOSE": [("app", "workload-file-write-read", r"\bCLOSE\b")],
    "READ": [("app", "workload-file-write-read", r"\bREAD\b")],
    "WRITE": [("app", "workload-file-write-read", r"\bWRITE\b"),
              ("test", "tests/test_record_sequential_files.py")],
    "DISPLAY": [("app", "workload-minimal", r"\bDISPLAY\b")],
    "MOVE": [("app", "workload-universal", r"\bMOVE\b")],
    "STOP RUN": [("app", "workload-minimal", r"STOP\s+RUN")],
    "IF/ELSE": [("app", "workload-arithmetic", r"\bELSE\b")],
    "PERFORM": [("app", "workload-batch-rc", r"\bPERFORM\b")],
    # No corpus application uses it: proven by this file's own oracle pin.
    "PERFORM TIMES": [("test", "tests/test_phase5_certification.py")],
    "EVALUATE": [("app", "workload-evaluate", r"\bEVALUATE\b")],
    "INITIALIZE": [("test", "tests/integration/test_initialize_oracle_proof.py"),
                   ("app", "workload-binary-values", r"\bINITIALIZE\b")],
    "FIGURATIVE CONSTANT": [("app", "workload-universal", r"\b(SPACES?|ZEROS?|ZEROES)\b")],
    "STRING": [("test", "tests/transformation/test_line_sequential_and_string_numeric.py")],
    "UNSTRING": [("test", "tests/integration/test_unstring_oracle_proof.py")],
}


def _jsonl(name: str) -> list[dict]:
    path = EVIDENCE / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _certified_apps() -> set[str]:
    """Apps VERIFIED and independently AGREE on every proven runtime."""
    apps: set[str] | None = None
    for runtime in RUNTIMES:
        verified = {r["app"] for r in _jsonl(f"runtime_corpus_{runtime}.jsonl")
                    if r.get("verdict") == "VERIFIED"}
        agree = {r["app"] for r in _jsonl(f"runtime_corpus_{runtime}_independent.jsonl")
                 if r.get("verdict") == "AGREE"}
        both = verified & agree
        apps = both if apps is None else apps & both
    return apps or set()


def _fixture_source(app: str) -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in sorted((REPO / "fixtures" / app).rglob("*"))
        if p.is_file() and p.suffix.lower() in (".cob", ".cbl", ".cpy")
    )


def test_every_supported_construct_has_a_proof_entry():
    assert set(PROOFS) == set(SUPPORTED_CONSTRUCTS), (
        "SUPPORTED without proof: " + str(sorted(set(SUPPORTED_CONSTRUCTS) - set(PROOFS)))
        + "; stale proof entries: " + str(sorted(set(PROOFS) - set(SUPPORTED_CONSTRUCTS)))
    )


@pytest.mark.parametrize("construct", sorted(PROOFS))
def test_supported_construct_is_proven_against_gnucobol(construct):
    certified = _certified_apps()
    assert certified, "no certified corpus evidence"
    reasons = []
    for proof in PROOFS[construct]:
        if proof[0] == "test":
            path = REPO / proof[1]
            assert path.is_file(), f"{construct}: proof file missing: {proof[1]}"
            text = path.read_text(encoding="utf-8")
            assert any(m in text for m in _ORACLE_MARKERS), (
                f"{construct}: {proof[1]} never runs the GnuCOBOL oracle")
        else:
            _, app, pattern = proof
            apps = sorted(certified) if app is None else [app]
            hits = [a for a in apps if a in certified
                    and re.search(pattern, _fixture_source(a), re.I | re.M)]
            assert hits, (
                f"{construct}: no certified application ({app or 'any'}) whose "
                f"source matches {pattern!r}")
            reasons.append(hits[0])


def test_certified_corpus_is_the_accepted_one():
    # 44 of 54 on each of the four runtimes, all re-checked AGREE.
    certified = _certified_apps()
    assert len(certified) == 44
    for runtime in RUNTIMES:
        assert len(_jsonl(f"runtime_corpus_{runtime}.jsonl")) == 54


def test_partial_claims_found_false_are_not_supported():
    assert CONSTRUCT_REGISTRY["REPLACE"].level is CapabilityLevel.PARTIAL
    evidence = CONSTRUCT_REGISTRY["UNSTRING"].evidence
    assert "oracle-proven" not in evidence
    assert "WITH POINTER" in evidence and "fail closed" in evidence


# GnuCOBOL 3.1.2 output for the probes (measured 2026-11-02), pinned so an
# implementation can be checked against it; today generation must refuse.
_UNSPTR_ORACLE = (
    "A=[ALPHA   ] B=[BETA]\nPTR=012 CNT=002\nC=[GAMMA   ]\n"
    "PTR=018 CNT=003\nA=[BETA    ] PTR=012 CNT=001\n"
)
_REPL_ORACLE = "TOTAL=0015\nLIMIT 5\n"


@pytest.mark.parametrize(("name", "oracle"), [("UNSPTR", _UNSPTR_ORACLE), ("REPL", _REPL_ORACLE)])
def test_unproven_forms_fail_generation_closed(name, oracle):
    from engine.transformation.producer import TransformationProducer

    source = (REPO / "tests" / "data" / "phase5" / f"{name}.cob").read_text(encoding="utf-8")
    result = TransformationProducer().transform(source, name)
    assert result.success is False, "generation must refuse, not approximate"
    assert result.errors


@pytest.mark.docker
@pytest.mark.parametrize(("name", "oracle"), [("UNSPTR", _UNSPTR_ORACLE), ("REPL", _REPL_ORACLE)])
def test_probe_oracle_pins(tmp_path, name, oracle):
    from tests.oracle_java_helpers import run_gnucobol

    source = (REPO / "tests" / "data" / "phase5" / f"{name}.cob").read_text(encoding="utf-8")
    assert run_gnucobol(source, name, tmp_path) == oracle


# PERFORM <paragraph> n TIMES (literal, field, zero) and inline PERFORM n
# TIMES: GnuCOBOL 3.1.2 output, matched by the generated Java (2026-11-02).
_PTIMES_ORACLE = "LITERAL 004\nFIELD 007\nZERO 007\nINLINE 027\n"


def _ptimes_source() -> str:
    return (REPO / "tests" / "data" / "phase5" / "PTIMES.cob").read_text(encoding="utf-8")


def test_perform_times_generated_java_matches_the_pin(tmp_path):
    from tests.oracle_java_helpers import run_generated_java

    assert run_generated_java(_ptimes_source(), "PTIMES", tmp_path) == _PTIMES_ORACLE


@pytest.mark.docker
def test_perform_times_oracle_pin(tmp_path):
    from tests.oracle_java_helpers import run_gnucobol

    assert run_gnucobol(_ptimes_source(), "PTIMES", tmp_path) == _PTIMES_ORACLE


def test_one_product_version_everywhere():
    # Release traceability: the engine, the API and the frontend report one
    # version, and the release manifest records it (productVersion).
    import json as _json

    from engine import __version__

    api_text = (REPO / "api" / "app.py").read_text(encoding="utf-8")
    assert f'version="{__version__}"' in api_text
    package = _json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == __version__
    manifest = (REPO / "scripts" / "supply-chain" / "build_release_manifest.py").read_text(encoding="utf-8")
    assert '"productVersion": product_version()' in manifest


def test_ci_image_builds_retry_transient_registry_errors():
    # A single 502 from Maven Central failed a certification job twice
    # (run 41494148954); every workflow builds images through the retrying
    # script, never a bare `docker build`.
    for workflow in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        assert "docker build" not in text, workflow.name
    script = (REPO / "scripts" / "ci" / "build-image.sh").read_text(encoding="utf-8")
    assert "for attempt in 1 2 3" in script and "set -euo pipefail" in script


def test_workflow_pipelines_into_tee_keep_the_command_status():
    # GitHub's default `run` shell is `bash -e` without pipefail: in
    # `cmd | tee log` a failing cmd is masked by tee. The first certification
    # run passed although the verifier crashed. Every step that pipes into
    # tee must run with pipefail (explicit, or shell: bash). PyYAML is in
    # the backend lock, not in the pytest-only gate job: skip there, the
    # backend job runs it.
    yaml = pytest.importorskip("yaml")

    for workflow in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        default_shell = (data.get("defaults") or {}).get("run", {}).get("shell")
        for job in data["jobs"].values():
            job_shell = (job.get("defaults") or {}).get("run", {}).get("shell", default_shell)
            for step in job["steps"]:
                run = step.get("run", "")
                if "| tee" not in run:
                    continue
                shell = step.get("shell", job_shell)
                assert "pipefail" in run or shell == "bash", (workflow.name, step.get("name"))
