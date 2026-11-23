"""The three CI levels stay distinct, and the optimisation never drops a proof (docs/operations/CI_LEVELS.md).

A  fast checks            .github/workflows/ci.yml             every push / PR
B  full validation        .github/workflows/ci-full.yml        scheduled, main, release candidates, [full]
C  corpus certification   .github/workflows/certification.yml  exact-SHA release evidence, [certify]
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # PyYAML is in the backend lock, not in the pytest-only capability gate

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _load(name: str) -> dict:
    return yaml.safe_load(_text(name))


FAST, FULL, CERT, SUPPLY = (_load(n) for n in ("ci.yml", "ci-full.yml", "certification.yml", "supply-chain.yml"))


def _steps_text(job: dict) -> str:
    return "\n".join(str(step) for step in job["steps"])


# --- level A: fast, and never mistaken for more -------------------------------------------------------------------


def test_the_fast_workflow_keeps_its_gates_and_says_it_is_not_full_or_certification():
    assert FAST["name"] == "CI fast checks"
    assert {"capability-truth", "capability-truth-windows", "lint", "typecheck", "generation-hashes", "fast-backend",
            "frontend", "frontend-windows"} <= set(FAST["jobs"])
    header = _text("ci.yml").split("jobs:", 1)[0]
    assert "NOT FULL VALIDATION AND NOT CERTIFICATION" in header
    for forbidden in ("coverage", "backend-oracle", "certif"):
        assert not [k for k in FAST["jobs"] if forbidden in k], forbidden
        assert not [j["name"] for j in FAST["jobs"].values() if forbidden in j["name"].lower()], forbidden
    assert "certif" not in FAST["name"].lower() and "full" not in FAST["name"].lower()


def test_the_fast_gates_run_the_same_commands_as_before():
    text = _text("ci.yml")
    assert "tests/capability_truth.txt" in text and "python tools/dependency_map.py --check" in text
    assert "tools/generation_hashes.py --check docs/audits/generation_hashes.json" in text
    assert "tools/mypy_gate.py --check" in text and "ruff check ." in text
    assert "npm run build" in text and "npm test" in text
    assert FAST["jobs"]["capability-truth-windows"]["runs-on"] == "windows-2022"
    assert FAST["jobs"]["frontend-windows"]["runs-on"] == "windows-2022"


def test_the_fast_backend_groups_are_a_named_subset_of_the_suite():
    groups = FAST["jobs"]["fast-backend"]["strategy"]["matrix"]["include"]
    paths = " ".join(g["paths"] for g in groups).split()
    assert {"tests/discovery", "tests/evidence", "tests/tools", "tests/transformation"} == set(paths)
    assert all((REPO / p).is_dir() for p in paths)
    assert "-W error::pytest.PytestWarning" in _steps_text(FAST["jobs"]["fast-backend"])


# --- level B: complete, sharded, proven complete -----------------------------------------------------------------


def test_full_validation_is_due_only_for_scheduled_main_release_and_marked_runs():
    assert FULL["name"] == "Full integration validation"
    triggers = FULL.get("on") or FULL[True]
    assert "schedule" in triggers and "workflow_dispatch" in triggers
    # No always-running job: when the validation is not due, EVERY job is skipped and the run shows as skipped. A
    # 'plan' job that succeeds would make a validation that never ran look green.
    assert "plan" not in FULL["jobs"]
    due = ("github.event_name == 'schedule'", "github.event_name == 'workflow_dispatch'",
           "github.ref == 'refs/heads/main'", "startsWith(github.ref, 'refs/heads/release/')",
           "startsWith(github.ref, 'refs/tags/')", "contains(github.event.head_commit.message, '[full]')")
    for key, job in FULL["jobs"].items():
        assert "if" in job, f"{key} runs unconditionally"
        for token in due:
            assert token in job["if"], (key, token)
    # nothing interpolates the commit message into a shell: it is only an expression in `if:`
    assert "head_commit.message" not in _text("ci-full.yml").replace(
        "contains(github.event.head_commit.message, '[full]')", "")


def test_full_validation_keeps_every_required_proof():
    jobs = FULL["jobs"]
    cov = _steps_text(jobs["coverage"])
    assert "coverage run -m pytest -q tests" in cov and "--fail-under=" in cov
    assert int(cov.split("--fail-under=")[1].split()[0]) >= 88
    hermetic = _steps_text(jobs["backend-hermetic"])
    assert "-W error::pytest.PytestWarning tests" in hermetic            # the whole tree, warnings as errors
    assert jobs["backend-hermetic-windows"]["runs-on"] == "windows-2022"
    assert "-W error::pytest.PytestWarning tests" in _steps_text(jobs["backend-hermetic-windows"])
    oracle = jobs["backend-oracle"]
    steps = _steps_text(oracle)
    for token in ("RUN_DOCKER_TESTS", "SYSTEMAOPS_TEST_POSTGRES_DSN", "VSAM_EVIDENCE_DIR", "linux/s390x",
                  "test \"$arch\" = \"s390x\"", "record_docker_image_provenance.py", "docker-images.json",
                  "Dockerfile.ocesql-pg", "Dockerfile.maven-offline", "Dockerfile.gnucobol"):
        assert token in steps, token
    assert "postgres@sha256:" in str(oracle["services"])                 # throwaway PostgreSQL, pinned by digest


def test_the_shard_count_matches_the_matrix_and_the_lane_is_reassembled_and_proven():
    shards = int(FULL["env"]["SHARDS"])
    assert FULL["jobs"]["backend-oracle"]["strategy"]["matrix"]["shard"] == list(range(1, shards + 1))
    assert FULL["jobs"]["backend-oracle"]["strategy"]["fail-fast"] is False
    assert f"/{shards})" in FULL["jobs"]["backend-oracle"]["name"]
    run = _steps_text(FULL["jobs"]["backend-oracle"])
    assert 'tools/ci_shards.py --shards "$SHARDS" --check' in run and "--index" in run
    assert "backend-junit-shard-${SHARD}.xml" in run
    done = FULL["jobs"]["backend-oracle-complete"]
    text = _steps_text(done)
    assert "needs.backend-oracle.result" in text and "tools/ci_shard_proofs.py" in text
    assert "--collected" in text and "--collect-only" in text
    assert "always()" in done["if"]  # it must still run (and fail) when a shard failed


# --- level C: certification is unchanged ---------------------------------------------------------------------------


def test_certification_is_still_the_exact_sha_four_runtime_corpus():
    job = CERT["jobs"]["certify"]
    assert job["strategy"]["matrix"]["runtime"] == ["spring_boot", "plain_java", "quarkus", "micronaut"]
    assert "[certify]" in job["if"] and "workflow_dispatch" in job["if"]
    text = _steps_text(job)
    for token in ("run_fixture_apps.py", "verify_independent.py", "certify_corpus.py"):
        assert token in text, token
    assert CERT["jobs"]["summarize"]["needs"] == "certify"


# --- image caching: faster, never different ------------------------------------------------------------------------


def test_the_layer_cache_is_opt_in_and_the_retry_and_pin_behaviour_is_intact():
    script = (REPO / "scripts" / "ci" / "build-image.sh").read_text(encoding="utf-8")
    assert 'cache_root="${DOCKER_BUILDX_CACHE_ROOT:-}"' in script
    assert "--cache-from" in script and "--cache-to" in script and "mode=max" in script
    assert "docker buildx build --load --pull" in script and "docker build --pull" in script  # plain path remains
    assert 'attempts=5' in script and "--network host" in script and "--allow network.host" in script
    assert "--build-arg APT_MIRROR" in script and "dns_report" in script and "exit 1" in script
    for name in ("Dockerfile.gnucobol", "Dockerfile.ocesql-pg", "Dockerfile.maven-offline"):
        assert re.search(r"FROM [^\n]*@sha256:[0-9a-f]{64}", (REPO / name).read_text(encoding="utf-8")), name


@pytest.mark.parametrize("workflow,job", [(FULL, "backend-oracle"), (CERT, "certify"), (SUPPLY, "image-scan")])
def test_every_image_building_job_sets_up_a_pinned_buildx_and_cache(workflow, job):
    steps = workflow["jobs"][job]["steps"]
    uses = [s.get("uses", "") for s in steps]
    assert any(u.startswith("docker/setup-buildx-action@") for u in uses)
    assert any(u.startswith("actions/cache@") for u in uses)
    buildx = next(s for s in steps if s.get("uses", "").startswith("docker/setup-buildx-action@"))
    assert "network.host" in buildx["with"]["buildkitd-flags"]            # the retry fallback keeps working
    assert any("DOCKER_BUILDX_CACHE_ROOT" in str(s.get("run", "")) for s in steps)
    first_build = next(i for i, s in enumerate(steps) if "build-image.sh" in str(s.get("run", "")))
    assert first_build > max(i for i, s in enumerate(steps) if "DOCKER_BUILDX_CACHE_ROOT" in str(s.get("run", ""))
                             and "build-image.sh" not in str(s.get("run", "")))


# --- the report-only scan moved; the gating audits did not ---------------------------------------------------------


def test_trivy_is_scheduled_or_release_only_and_the_gating_audits_still_run_on_every_push():
    scan = SUPPLY["jobs"]["image-scan"]
    for event in ("schedule", "workflow_dispatch", "refs/tags/"):
        assert event in scan["if"]
    assert "push" not in scan["if"]
    for gating in ("python-audit", "frontend-audit", "release-manifest"):
        assert "if" not in SUPPLY["jobs"][gating], gating
    for job in SUPPLY["jobs"].values():
        assert "continue-on-error" not in job and not [s for s in job["steps"] if "continue-on-error" in s]
    assert re.search(r"aquasec/trivy@sha256:[0-9a-f]{64}", _text("supply-chain.yml"))
    assert "pip_audit" in _steps_text(SUPPLY["jobs"]["python-audit"])
    assert "npm audit --omit=dev" in _steps_text(SUPPLY["jobs"]["frontend-audit"])
