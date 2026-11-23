"""tools/ci_shards.py: deterministic, complete, balanced test sharding (a dropped test file must be impossible)."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import ci_shards  # noqa: E402  (tools/ is not a package)

SHARD_COUNTS = (1, 2, 4, 6, 8)


@pytest.fixture(scope="module")
def files() -> list[str]:
    return ci_shards.discover()


@pytest.fixture(scope="module")
def durations() -> dict[str, float]:
    return ci_shards.load_durations()


def test_discovery_finds_this_file_and_only_test_modules(files):
    assert "tests/tools/test_ci_shards.py" in files
    assert files == sorted(files)
    assert all(f.startswith("tests/") and f.rsplit("/", 1)[1].startswith("test_") for f in files)
    assert not any("__pycache__" in f for f in files)


@pytest.mark.parametrize("count", SHARD_COUNTS)
def test_every_test_file_is_in_exactly_one_shard(files, durations, count):
    buckets = ci_shards.partition(files, count, durations)
    assert len(buckets) == count
    flat = [name for bucket in buckets for name in bucket]
    assert sorted(flat) == files and len(flat) == len(set(flat))
    assert ci_shards.check(files, buckets, durations) == []


def test_the_partition_does_not_depend_on_discovery_order(files, durations):
    shuffled = list(files)
    random.Random(7).shuffle(shuffled)
    assert ci_shards.partition(shuffled, 6, durations) == ci_shards.partition(files, 6, durations)
    assert ci_shards.partition(list(reversed(files)), 6, durations) == ci_shards.partition(files, 6, durations)


def test_the_assignment_is_stable_across_runs(files, durations):
    first = ci_shards.partition(files, 6, durations)
    assert ci_shards.partition(files, 6, durations) == first
    # a changed manifest weight moves work, an unchanged one does not: stability is real, not constant output
    heaviest = max(files, key=lambda f: ci_shards.weight(f, durations))
    skewed = dict(durations, **{heaviest: durations.get(heaviest, 1.0) * 10})
    assert ci_shards.partition(files, 6, skewed) != first


def test_shards_are_balanced_by_measured_time(files, durations):
    for count in (4, 6, 8):
        loads = ci_shards.loads_of(ci_shards.partition(files, count, durations), durations)
        largest_file = max(ci_shards.weight(f, durations) for f in files)
        assert max(loads) - min(loads) <= largest_file   # the LPT guarantee: spread is at most one file
        assert max(loads) <= 1.1 * sum(loads) / count + largest_file


def test_a_new_unmeasured_file_is_assigned_not_dropped(files, durations):
    extra = [*files, "tests/new/test_brand_new.py"]
    buckets = ci_shards.partition(extra, 6, durations)
    assert sum("tests/new/test_brand_new.py" in b for b in buckets) == 1


def test_check_rejects_a_dropped_a_duplicated_and_an_empty_shard(files, durations):
    buckets = ci_shards.partition(files, 4, durations)
    dropped = [list(b) for b in buckets]
    dropped[0] = dropped[0][1:]
    assert any("exactly once" in p for p in ci_shards.check(files, dropped, durations))
    duplicated = [list(b) for b in buckets]
    duplicated[1].append(duplicated[0][0])
    assert ci_shards.check(files, duplicated, durations)
    assert any("empty" in p for p in ci_shards.check(files, [*buckets, []], durations))


def test_the_manifest_matches_the_tree_closely_enough_to_balance(files, durations):
    measured = [f for f in files if f in durations]
    assert len(measured) >= 0.9 * len(files), "regenerate tools/ci_test_durations.json (--refresh-durations)"
    assert sum(durations.values()) > 1000  # the Docker lane's real cost, not a placeholder


def test_cli_prints_the_shard_and_checks_the_partition(capsys):
    assert ci_shards.main(["--shards", "6", "--check"]) == 0
    report = capsys.readouterr().out
    assert f"{len(ci_shards.discover())} test files, 6 shards" in report
    assert ci_shards.main(["--shards", "6", "--index", "2"]) == 0
    printed = capsys.readouterr().out.split()
    assert printed and all(p.startswith("tests/") for p in printed)
    assert ci_shards.main(["--shards", "6", "--index", "7"]) == 2
    assert ci_shards.main(["--shards", "0", "--check"]) == 2


def test_refresh_rebuilds_the_manifest_from_junit(tmp_path):
    junit = tmp_path / "r.xml"
    junit.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="tests.tools.test_ci_shards.TestX" name="a" time="1.5"/>'
        '<testcase classname="tests.tools.test_ci_shards" name="b" time="2.25"/>'
        '<testcase classname="tests.gone.test_missing" name="c" time="9"/>'
        '</testsuite></testsuites>', encoding="utf-8")
    out = tmp_path / "d.json"
    data = ci_shards.refresh_durations([junit], out)
    assert data == {"tests/tools/test_ci_shards.py": 3.8}   # summed; a file that no longer exists is ignored
    assert ci_shards.load_durations(out) == data
