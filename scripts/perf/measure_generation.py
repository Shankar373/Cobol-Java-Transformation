"""Deterministic performance baseline: in-process generation of the corpus.

Usage::

    python scripts/perf/measure_generation.py [--runs 3] [--out baseline.json]

For every fixture application (``fixtures/<app>/cobol``) the universal
modernization pipeline runs discovery -> analysis -> plan -> generation ->
assembly in-process (no Docker, no JVM, no network), one application at a
time, into a temporary directory that is deleted afterwards.  Records the
median wall time of ``--runs`` runs per application, the outcome (generated
or refused) and the peak traced Python memory of the whole run.  Execution
and oracle timings are deliberately excluded: they depend on Docker and the
host, so they are reported, not asserted.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from engine.modernization.pipeline import (  # noqa: E402
    ModernizationConfig,
    UniversalModernizationPipeline,
)


def corpus() -> list[Path]:
    return sorted(p for p in (REPO / "fixtures").glob("*/cobol") if p.is_dir())


def generate(app_dir: Path, target: str = "spring_boot") -> tuple[float, bool]:
    import logging

    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory() as out:
        started = time.perf_counter()
        report = UniversalModernizationPipeline(ModernizationConfig(
            source_dir=str(app_dir), output_dir=out,
            application_id=app_dir.parent.name, docker_available=True,
            target_runtime=target,
        )).execute()
        elapsed = time.perf_counter() - started
    logging.disable(logging.NOTSET)
    return elapsed, bool(report.generation_success and report.generated_project_dir)


def measure(runs: int = 3, target: str = "spring_boot") -> dict:
    tracemalloc.start()
    apps = {}
    for app_dir in corpus():
        times = []
        generated = False
        for _ in range(runs):
            elapsed, generated = generate(app_dir, target)
            times.append(elapsed)
        apps[app_dir.parent.name] = {
            "median_seconds": round(statistics.median(times), 4),
            "generated": generated,
        }
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    medians = [a["median_seconds"] for a in apps.values()]
    return {
        "target_runtime": target,
        "runs_per_app": runs,
        "applications": len(apps),
        "generated": sum(a["generated"] for a in apps.values()),
        "total_median_seconds": round(sum(medians), 3),
        "max_median_seconds": round(max(medians), 4),
        "peak_traced_mib": round(peak / 2**20, 1),
        "apps": apps,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--target", default="spring_boot")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = measure(args.runs, args.target)
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
    summary = {k: v for k, v in result.items() if k != "apps"}
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
