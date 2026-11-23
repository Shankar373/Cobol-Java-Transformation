"""Deterministic test sharding for the full-validation Docker lane.

The Docker/oracle lane is one serial pytest process (about 68 minutes, measured on run 45050810212): a few dozen
oracle files of 30-40 s per test dominate it.  This tool splits the test FILES (never individual tests: file-scoped
fixtures and ordering stay intact) across N runners.

    python tools/ci_shards.py --shards 6 --index 3        # files of shard 3 (1-based), one per line
    python tools/ci_shards.py --shards 6 --check          # partition proof + balance report (exit 1 on a defect)
    python tools/ci_shards.py --refresh-durations a.xml   # rewrite tools/ci_test_durations.json from JUnit reports

Determinism: the files are the sorted ``tests/**/test_*.py`` paths (pytest.ini ``python_files``); each file weighs its
measured seconds (``tools/ci_test_durations.json``; unknown files weigh ``DEFAULT_WEIGHT``); files are assigned
greedily, heaviest first, to the currently lightest shard (ties: lowest index, then path order).  The same tree and
the same manifest always give the same shards, whatever the host or the file system order.  Stale manifest entries
(a renamed or deleted file) are ignored; a new file is assigned like any other, so no test file is ever dropped.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DURATIONS = Path(__file__).resolve().with_name("ci_test_durations.json")
TESTS = REPO / "tests"
DEFAULT_WEIGHT = 2.0   # seconds assumed for a file the manifest has not measured (a hermetic file is far cheaper)
MIN_WEIGHT = 1.0       # per-file floor: collection and import cost is never zero
SKIPPED_DIRS = {"__pycache__", "tmp", "test-artifacts"}  # pytest.ini norecursedirs, plus bytecode


def discover(root: Path = REPO) -> list[str]:
    """Every pytest test file under ``tests/``, as sorted repo-relative POSIX paths."""
    found = []
    for path in (root / "tests").rglob("test_*.py"):
        rel = path.relative_to(root)
        if SKIPPED_DIRS.intersection(rel.parts):
            continue
        found.append(rel.as_posix())
    return sorted(found)


def load_durations(path: Path = DURATIONS) -> dict[str, float]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(name): float(seconds) for name, seconds in raw["seconds"].items()}


def weight(name: str, durations: dict[str, float]) -> float:
    return max(durations.get(name, DEFAULT_WEIGHT), MIN_WEIGHT)


def partition(files: list[str], shards: int, durations: dict[str, float]) -> list[list[str]]:
    """Greedy longest-processing-time assignment; the result is independent of the order ``files`` arrives in."""
    if shards < 1:
        raise ValueError("shards must be >= 1")
    buckets: list[list[str]] = [[] for _ in range(shards)]
    loads = [0.0] * shards
    for name in sorted(files, key=lambda f: (-weight(f, durations), f)):
        target = min(range(shards), key=lambda i: (loads[i], i))
        buckets[target].append(name)
        loads[target] += weight(name, durations)
    return [sorted(bucket) for bucket in buckets]


def loads_of(buckets: list[list[str]], durations: dict[str, float]) -> list[float]:
    return [sum(weight(f, durations) for f in bucket) for bucket in buckets]


def check(files: list[str], buckets: list[list[str]], durations: dict[str, float]) -> list[str]:
    """Defects of a partition: a file missing, duplicated or invented, or a shard that is empty."""
    problems = []
    flat = [name for bucket in buckets for name in bucket]
    if sorted(flat) != sorted(files):
        problems.append(f"partition does not cover the test files exactly once: "
                        f"missing={sorted(set(files) - set(flat))} extra={sorted(set(flat) - set(files))}")
    if len(flat) != len(set(flat)):
        problems.append("a test file is assigned to more than one shard")
    problems += [f"shard {i + 1} is empty" for i, bucket in enumerate(buckets) if not bucket]
    return problems


def refresh_durations(reports: list[Path], out: Path = DURATIONS) -> dict[str, float]:
    """Sum the JUnit ``time`` of every test case per test file (classname ``tests.pkg.test_mod.TestCls``)."""
    seconds: dict[str, float] = {}
    existing = set(discover())
    for report in reports:
        for case in ET.parse(report).getroot().iter("testcase"):
            parts = [p for p in case.get("classname", "").split(".") if p]
            module = [p for p in parts if not p.startswith("Test")]
            name = "/".join(module) + ".py"
            if name in existing:
                seconds[name] = seconds.get(name, 0.0) + float(case.get("time", 0.0))
    payload = {"schema": "systemaops.ci-test-durations/1",
               "note": "seconds per test file in the Docker-lane run; regenerate with --refresh-durations",
               "seconds": {name: round(value, 1) for name, value in sorted(seconds.items())}}
    out.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return {k: float(v) for k, v in payload["seconds"].items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--index", type=int, help="1-based shard to print")
    parser.add_argument("--check", action="store_true", help="prove the partition and print the balance")
    parser.add_argument("--refresh-durations", nargs="+", metavar="JUNIT_XML")
    args = parser.parse_args(argv)

    if args.refresh_durations:
        data = refresh_durations([Path(p) for p in args.refresh_durations])
        print(f"wrote {DURATIONS.relative_to(REPO)}: {len(data)} files, {sum(data.values()):.0f} s")
        return 0
    files = discover()
    durations = load_durations()
    if args.shards < 1:
        print("error: --shards must be >= 1", file=sys.stderr)
        return 2
    buckets = partition(files, args.shards, durations)
    if args.check:
        problems = check(files, buckets, durations)
        loads = loads_of(buckets, durations)
        print(f"{len(files)} test files, {args.shards} shards; estimated seconds per shard: "
              + ", ".join(f"{load:.0f}" for load in loads))
        for problem in problems:
            print(f"DEFECT: {problem}", file=sys.stderr)
        return 1 if problems else 0
    if args.index is None or not 1 <= args.index <= args.shards:
        print("error: --index must be between 1 and --shards", file=sys.stderr)
        return 2
    print("\n".join(buckets[args.index - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
