"""Discovery over the repository's own fixture workloads: a real corpus, so scanner false positives show up here, not at a customer."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from enterprise.discovery.classify import classify
from enterprise.discovery.compilers import ToolchainConfig
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.model import rmtree_force

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
WORKLOADS = sorted(p for p in FIXTURES.glob("workload-*") if p.is_dir())

#: Fixtures that are incomplete or use unsupported constructs *on purpose*; anything else must be READY.
EXPECTED_BLOCKED = {"workload-jcl"}  # references programs and a procedure that are deliberately not in the fixture


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    store = tmp_path_factory.mktemp("corpus-store")
    out = {}
    for index, directory in enumerate(WORKLOADS):
        source = directory / "cobol" if (directory / "cobol").is_dir() else directory
        out[directory.name] = discover(DiscoveryRequest("directory", str(source)), store / f"s{index}", toolchain=ToolchainConfig(backend="none"))
    yield out
    rmtree_force(store)


def test_the_corpus_is_present() -> None:
    assert len(WORKLOADS) >= 50


def test_no_scanner_ever_fails_and_only_the_known_incomplete_fixture_is_blocked(results) -> None:
    states = {name: r.report["readiness"]["status"] for name, r in results.items()}
    assert {name for name, state in states.items() if state == "BLOCKED"} == EXPECTED_BLOCKED, states
    for name, result in results.items():
        assert "SCANNER_FAILED" not in {p["code"] for p in result.report["scanner_problems"]}, name
        assert result.report["completeness"]["checks"][0]["passed"], name  # the checkpoint verified


def test_corpus_readiness_counts_are_stable(results) -> None:
    counts = Counter(r.report["readiness"]["status"] for r in results.values())
    assert counts["BLOCKED"] == 1 and counts["READY"] + counts["NOT_SUPPORTED"] == len(WORKLOADS) - 1
    assert counts["NOT_SUPPORTED"] >= 1, "the corpus contains constructs open-source tooling cannot check"


def test_every_program_of_the_corpus_is_found_in_an_application(results) -> None:
    for name, result in results.items():
        programs = {p["name"] for p in result.report["programs"]}
        in_apps = {p for a in result.report["applications"]["applications"] for p in a["programs"]}
        assert programs <= in_apps, (name, programs - in_apps)


def test_java_and_markdown_files_that_mention_cobol_keywords_are_not_cobol() -> None:
    assert classify("CLAIMS.java", "// PROGRAM-ID. X\n IDENTIFICATION DIVISION.").cls == "java-source"
    assert classify("NOTES.md", "//J JOB\n").cls == "doc"
    assert classify("MEMBER", "//J JOB\n//S EXEC PGM=X\n").cls == "jcl-job"
