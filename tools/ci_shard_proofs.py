"""Prove that a sharded Docker-lane run is COMPLETE and that its required proofs actually ran.

Sharding (tools/ci_shards.py) must never turn into "fewer tests ran".  After every shard has uploaded its JUnit
report, this check fails unless ALL of the following hold:

  1. exactly one report per shard, numbered 1..N, and no unexpected extra report;
  2. no test case failed or errored, in any shard;
  3. every test file that ran belongs to the shard that ran it (the partition was honoured, nothing ran twice);
  4. the number of executed test cases (passed + failed + skipped) equals the number pytest COLLECTS for the whole
     tree (``--collected N``), so no test was dropped or duplicated by the split;
  5. the proof modules the lane exists for (VSAM, s390x oracle, PostgreSQL, ...) ran and none of their cases was
     skipped (the former single-process check, now across shards).

    python tools/ci_shard_proofs.py --junit-dir artifacts --shards 6 --collected 8160

Exit 0 when complete, 1 with one line per defect otherwise.  Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_shards  # noqa: E402  (tools/ is not a package)

REPORT = re.compile(r"backend-junit-shard-(\d+)\.xml$")
REQUIRED_PROOFS = ("test_vsam_api_to_java", "test_vsam_s390x_oracle", "test_vsam_java_consumer",
                   "test_vsam_consumer_oracle", "tests.enterprise.test_database", "tests.enterprise.test_vsam_worker")


def file_of(classname: str) -> str:
    parts = [p for p in classname.split(".") if p and not p.startswith("Test")]
    return "/".join(parts) + ".py"


def read_reports(junit_dir: Path) -> dict[int, list[ET.Element]]:
    reports: dict[int, list[ET.Element]] = {}
    for path in sorted(junit_dir.rglob("backend-junit-shard-*.xml")):
        match = REPORT.search(path.name)
        if match:
            reports[int(match.group(1))] = list(ET.parse(path).getroot().iter("testcase"))
    return reports


def verify(reports: dict[int, list[ET.Element]], shards: int, collected: int,
           assignment: list[list[str]]) -> list[str]:
    problems = []
    missing = sorted(set(range(1, shards + 1)) - set(reports))
    extra = sorted(set(reports) - set(range(1, shards + 1)))
    if missing:
        problems.append(f"missing JUnit report for shard(s) {missing}")
    if extra:
        problems.append(f"unexpected JUnit report for shard(s) {extra}")
    executed = 0
    seen = {name: [0, 0] for name in REQUIRED_PROOFS}  # executed, skipped
    for shard, cases in sorted(reports.items()):
        owned = set(assignment[shard - 1]) if 1 <= shard <= len(assignment) else set()
        for case in cases:
            executed += 1
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            if any(child.tag in ("failure", "error") for child in case):
                problems.append(f"shard {shard}: {name} did not pass")
            if owned and file_of(case.get("classname", "")) not in owned:
                problems.append(f"shard {shard} ran a test of a file it does not own: {name}")
            for proof in REQUIRED_PROOFS:
                if proof in case.get("classname", ""):
                    seen[proof][0] += 1
                    seen[proof][1] += any(child.tag == "skipped" for child in case)
    if executed != collected:
        problems.append(f"{executed} test cases executed across the shards but pytest collects {collected}: "
                        "a test was dropped or run twice")
    bad = sorted(name for name, (ran, skipped) in seen.items() if ran == 0 or skipped)
    if bad:
        problems.append(f"required Docker-lane proofs missing or skipped: {bad}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--junit-dir", type=Path, required=True)
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--collected", type=int, required=True, help="test cases pytest collects for the whole tree")
    args = parser.parse_args(argv)
    assignment = ci_shards.partition(ci_shards.discover(), args.shards, ci_shards.load_durations())
    reports = read_reports(args.junit_dir)
    problems = verify(reports, args.shards, args.collected, assignment)
    total = sum(len(cases) for cases in reports.values())
    print(f"{len(reports)}/{args.shards} shard reports, {total} test cases executed, {args.collected} collected")
    for problem in problems:
        print(f"DEFECT: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
