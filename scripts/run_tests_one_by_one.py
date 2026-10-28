#!/usr/bin/env python3
"""Run every pytest test file individually (one file per pytest process).

Rationale (Master README §76.5 / §50): a single monolithic `pytest tests`
invocation hides per-file provenance and makes one hung or contended file
opaque. This driver executes each discovered test file in its own process,
records pass/fail/skip/error counts and duration per file, and emits an
aggregate evidence report.

Design rules:
- Sequential by default (one worker): concurrent suites historically caused
  documented contention flakes (see docs/BACKLOG.md BL-010), so parallelism
  is opt-in and never the default.
- Failures never abort the run; every file is attempted.
- Docker-gated tests keep the standard `RUN_DOCKER_TESTS=1` opt-in unless
  `--no-docker` is passed.
- Evidence is written under `test-artifacts/one-by-one/`, which is never
  staged (D-4/BL-093 invariant).

Usage:
    python scripts/run_tests_one_by_one.py
    python scripts/run_tests_one_by_one.py --filter api
    python scripts/run_tests_one_by_one.py --no-docker --workers 1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "test-artifacts" / "one-by-one"
PYTEST = [sys.executable, "-m", "pytest"]


def discover_test_files() -> list[Path]:
    """Return sorted repo-relative test files pytest would collect from."""
    files = [
        p
        for p in (REPO_ROOT / "tests").rglob("test_*.py")
        if p.is_file() and "__pycache__" not in p.parts
    ]
    return sorted(files, key=lambda p: p.relative_to(REPO_ROOT).as_posix())


def parse_junit(path: Path) -> dict[str, int]:
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not path.is_file():
        return counts
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return counts
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    for suite in suites:
        for key in counts:
            value = suite.get(key)
            if value:
                counts[key] += int(value)
    return counts


def run_one(rel_path: str, out_dir: Path, env: dict[str, str], timeout: int) -> dict:
    started = time.monotonic()
    junit_path = out_dir / (rel_path.replace("/", "_").replace("\\", "_") + ".junit.xml")
    cmd = PYTEST + [rel_path, "-q", "-ra", f"--junitxml={junit_path}"]
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        returncode = proc.returncode
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        out_bytes = exc.stdout or b""
        err_bytes = exc.stderr or b""
        if isinstance(out_bytes, bytes):
            out_bytes = out_bytes.decode("utf-8", "replace")
        if isinstance(err_bytes, bytes):
            err_bytes = err_bytes.decode("utf-8", "replace")
        output = out_bytes + err_bytes

    duration = time.monotonic() - started
    counts = parse_junit(junit_path)

    status = "PASS"
    if timed_out:
        status = "TIMEOUT"
    elif counts["errors"]:
        status = "ERROR"
    elif counts["failures"]:
        status = "FAIL"
    elif counts["tests"] == 0 and returncode in (0, 5):
        # pytest exits 5 when a run collects nothing; that is a zero-test
        # file (renamed/moved/mis-imported), not a crash, but it must
        # never read as PASS (audit D-3).  Any other non-zero exit with
        # zero tests (4 = usage/collection error) stays ERROR.
        status = "NO_TESTS"
    elif returncode != 0:
        status = "ERROR"
    elif counts["skipped"] == counts["tests"]:
        # Every test in the file was gated away: the file verified nothing,
        # so it must not read as a clean PASS (audit D-3).
        status = "ALL_SKIP"

    tail = "\n".join(output.splitlines()[-40:])
    return {
        "file": rel_path,
        "status": status,
        "returncode": returncode,
        "duration_s": round(duration, 2),
        "tests": counts["tests"],
        "failures": counts["failures"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "junit": junit_path.name,
        "tail": tail,
    }


def write_reports(results: list[dict], out_dir: Path, started_at: str) -> dict:
    totals = {
        "files": len(results),
        "tests": sum(r["tests"] for r in results),
        "failures": sum(r["failures"] for r in results),
        "errors": sum(r["errors"] for r in results),
        "skipped": sum(r["skipped"] for r in results),
    }
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    payload = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totals": totals,
        "by_status": by_status,
        "results": results,
    }
    (out_dir / "results.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    lines = [
        "# Per-file test run (one pytest process per test file)",
        "",
        f"- Started: {started_at}",
        f"- Finished: {payload['finished_at']}",
        f"- Files: {totals['files']} | tests: {totals['tests']} | "
        f"failures: {totals['failures']} | errors: {totals['errors']} | "
        f"skipped: {totals['skipped']}",
        f"- By status: {by_status}",
        "",
        "| status | file | tests | fail | err | skip | seconds |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        lines.append(
            f"| {r['status']} | {r['file']} | {r['tests']} | {r['failures']} | "
            f"{r['errors']} | {r['skipped']} | {r['duration_s']} |"
        )
    # NO_TESTS is a problem, not a pass: a file that collected zero tests
    # (renamed, moved, mis-imported) silently vanished from the suite, and
    # treating it as benign let the driver exit 0 while reporting nothing
    # ran (audit D-3).  ALL_SKIP is likewise reported in diagnostics: every
    # test in the file was gated away, so the file verified nothing.
    problems = [r for r in results if r["status"] != "PASS"]
    if problems:
        lines += ["", "## Diagnostics (last output lines)", ""]
        for r in problems:
            lines += [f"### {r['file']} — {r['status']}", "```", r["tail"], "```", ""]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filter", default="", help="substring filter on file path")
    parser.add_argument("--no-docker", action="store_true", help="unset RUN_DOCKER_TESTS")
    parser.add_argument("--workers", type=int, default=1, help="parallel workers (default 1)")
    parser.add_argument("--timeout", type=int, default=2400, help="per-file timeout seconds")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--start-at", default="", help="skip files before this path")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip files already recorded in <out-dir>/results.partial.jsonl",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    if args.no_docker:
        env.pop("RUN_DOCKER_TESTS", None)
    else:
        env.setdefault("RUN_DOCKER_TESTS", "1")

    files = discover_test_files()
    rel_files = [p.relative_to(REPO_ROOT).as_posix() for p in files]
    if args.filter:
        rel_files = [f for f in rel_files if args.filter in f]
    if args.start_at:
        idx = next((i for i, f in enumerate(rel_files) if args.start_at in f), None)
        if idx is None:
            # A --start-at needle that matches nothing used to silently
            # restart the whole suite from the beginning (default 0),
            # hiding the typo behind a full run (audit D-3).
            print(
                f"ERROR: --start-at {args.start_at!r} matched no test file.",
                file=sys.stderr,
            )
            return 2
        rel_files = rel_files[idx:]

    if not rel_files:
        print("No test files matched.", file=sys.stderr)
        return 2

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Incremental persistence: one JSON line per finished file so an
    # interrupted run (restart/crash) can resume without losing evidence.
    progress_path = out_dir / "results.partial.jsonl"
    results: list[dict] = []
    done: set[str] = set()
    if args.resume and progress_path.is_file():
        for line in progress_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("file"):
                results.append(row)
                done.add(row["file"])
    if done:
        rel_files = [f for f in rel_files if f not in done]
        print(
            f"Resuming: {len(done)} file(s) already recorded, "
            f"{len(rel_files)} remaining.",
            flush=True,
        )

    print(f"Running {len(rel_files)} test files individually -> {out_dir}", flush=True)

    def record(row: dict) -> None:
        results.append(row)
        done.add(row["file"])
        with progress_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    try:
        if args.workers > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [
                    pool.submit(run_one, rel, out_dir, env, args.timeout)
                    for rel in rel_files
                ]
                for i, fut in enumerate(futures, 1):
                    r = fut.result()
                    record(r)
                    print(
                        f"[{i}/{len(rel_files)}] {r['status']:9} {r['file']} "
                        f"({r['tests']} tests, {r['duration_s']}s)",
                        flush=True,
                    )
        else:
            for i, rel in enumerate(rel_files, 1):
                r = run_one(rel, out_dir, env, args.timeout)
                record(r)
                print(
                    f"[{i}/{len(rel_files)}] {r['status']:9} {r['file']} "
                    f"({r['tests']} tests, {r['duration_s']}s)",
                    flush=True,
                )
    except KeyboardInterrupt:
        # An interrupted run is NOT a passing run: report it distinctly
        # (audit D-3) instead of exiting 0 off partial results.
        print("\nInterrupted — writing partial report...", flush=True)
        results.sort(key=lambda r: r["file"])
        payload = write_reports(results, out_dir, started_at)
        t = payload["totals"]
        print(
            f"\nINTERRUPTED: {t['files']} files recorded before interrupt "
            f"(of {len(rel_files)} remaining+done)",
            flush=True,
        )
        print(f"Report: {out_dir / 'summary.md'}", flush=True)
        return 130

    results.sort(key=lambda r: r["file"])
    payload = write_reports(results, out_dir, started_at)
    t = payload["totals"]
    print(
        f"\nDONE: {t['files']} files | {t['tests']} tests | "
        f"{t['failures']} failed | {t['errors']} errors | {t['skipped']} skipped",
        flush=True,
    )
    print(f"Report: {out_dir / 'summary.md'}", flush=True)
    # Fail on FAIL/ERROR/TIMEOUT as before, and additionally on:
    #  - NO_TESTS: a file that collected zero tests silently vanished;
    #  - ALL_SKIP:  every test in the file was gated away, proving nothing;
    #  - a run that recorded zero files (empty collection).
    # All three previously exited 0 while reporting that nothing ran
    # (audit D-3).
    by_status = payload["by_status"]
    bad = (
        by_status.get("FAIL", 0)
        + by_status.get("ERROR", 0)
        + by_status.get("TIMEOUT", 0)
        + by_status.get("NO_TESTS", 0)
        + by_status.get("ALL_SKIP", 0)
    )
    if not results:
        print("ERROR: no test files were recorded — empty run.", flush=True)
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
