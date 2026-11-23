"""tools/ci_shard_proofs.py: a sharded Docker-lane run is only accepted when it is complete and its proofs ran."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import ci_shard_proofs as proofs  # noqa: E402  (tools/ is not a package)

# two shards; the proof modules live in shard 1 (VSAM) and shard 2 (database, worker)
ASSIGNMENT = [
    ["tests/integration/test_vsam_api_to_java.py", "tests/integration/test_vsam_s390x_oracle.py",
     "tests/integration/test_vsam_java_consumer.py", "tests/integration/test_vsam_consumer_oracle.py",
     "tests/test_plain.py"],
    ["tests/enterprise/test_database.py", "tests/enterprise/test_vsam_worker.py", "tests/test_other.py"],
]


def case(classname: str, name: str = "t", *, outcome: str = "") -> ET.Element:
    element = ET.Element("testcase", classname=classname, name=name)
    if outcome:
        ET.SubElement(element, outcome)
    return element


def complete() -> dict[int, list[ET.Element]]:
    return {
        1: [case("tests.integration.test_vsam_api_to_java"), case("tests.integration.test_vsam_s390x_oracle"),
            case("tests.integration.test_vsam_java_consumer"), case("tests.integration.test_vsam_consumer_oracle"),
            case("tests.test_plain.TestX", "a")],
        2: [case("tests.enterprise.test_database"), case("tests.enterprise.test_vsam_worker"),
            case("tests.test_other")],
    }


def run(reports, collected=8):
    return proofs.verify(reports, 2, collected, ASSIGNMENT)


def test_a_complete_run_is_accepted():
    assert run(complete()) == []


def test_file_of_maps_a_classname_to_its_file():
    assert proofs.file_of("tests.integration.test_x.TestY") == "tests/integration/test_x.py"
    assert proofs.file_of("tests.test_z") == "tests/test_z.py"


def test_a_missing_shard_report_is_rejected():
    reports = complete()
    del reports[2]
    problems = run(reports, collected=8)
    assert any("missing JUnit report" in p for p in problems)
    assert any("collects 8" in p for p in problems)  # and the executed count no longer adds up


def test_an_unexpected_extra_report_is_rejected():
    reports = complete()
    reports[3] = [case("tests.test_other")]
    assert any("unexpected JUnit report" in p for p in run(reports, collected=9))


def test_a_failed_or_errored_case_is_rejected():
    for outcome in ("failure", "error"):
        reports = complete()
        reports[1][4] = case("tests.test_plain.TestX", "a", outcome=outcome)
        assert any("did not pass" in p for p in run(reports))


def test_a_test_that_ran_in_the_wrong_shard_is_rejected():
    reports = complete()
    reports[2].append(case("tests.test_plain.TestX", "b"))   # a shard-1 file executed by shard 2
    assert any("does not own" in p for p in run(reports, collected=9))


def test_a_dropped_or_duplicated_test_is_rejected_by_the_collected_count():
    assert any("dropped or run twice" in p for p in run(complete(), collected=9))   # one test was lost
    assert any("dropped or run twice" in p for p in run(complete(), collected=7))   # one ran twice


@pytest.mark.parametrize("proof_class", ["tests.integration.test_vsam_s390x_oracle", "tests.enterprise.test_database"])
def test_a_skipped_required_proof_is_rejected(proof_class):
    reports = complete()
    for cases in reports.values():
        for index, element in enumerate(cases):
            if element.get("classname") == proof_class:
                cases[index] = case(proof_class, outcome="skipped")
    assert any("missing or skipped" in p and proof_class.split(".")[-1] in p for p in run(reports))


def test_a_required_proof_that_never_ran_is_rejected():
    reports = complete()
    reports[1] = [c for c in reports[1] if "vsam_java_consumer" not in c.get("classname", "")]
    problems = run(reports, collected=7)
    assert any("test_vsam_java_consumer" in p for p in problems)


def test_reports_are_read_by_shard_number(tmp_path):
    for number in (1, 2):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite")
        suite.append(case("tests.test_plain", f"n{number}"))
        ET.ElementTree(root).write(tmp_path / f"backend-junit-shard-{number}.xml")
    (tmp_path / "other.xml").write_text("<testsuites/>", encoding="utf-8")
    nested = tmp_path / "backend-oracle-results-shard-3"
    nested.mkdir()
    root = ET.Element("testsuites")
    ET.SubElement(root, "testsuite").append(case("tests.test_plain", "n3"))
    ET.ElementTree(root).write(nested / "backend-junit-shard-3.xml")
    reports = proofs.read_reports(tmp_path)
    assert sorted(reports) == [1, 2, 3] and all(len(cases) == 1 for cases in reports.values())
