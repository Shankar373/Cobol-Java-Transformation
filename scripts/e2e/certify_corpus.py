"""Certify one runtime's corpus run against the accepted evidence.

Usage::

    python scripts/e2e/certify_corpus.py --runtime quarkus \
        --results e2e.jsonl --independent verify.jsonl --out-dir evidence/

Fails (exit 1) unless
* the run covers exactly the applications of the accepted evidence
  (``docs/reports/evidence/phase3/runtime_corpus_<runtime>.jsonl``),
* every application's verdict equals the accepted one,
* every VERIFIED application was re-checked by ``verify_independent.py``
  and the re-check AGREEs.
Writes the run and the re-check to ``--out-dir`` without host paths
(``generated_app_path`` dropped) and prints a one-line summary.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--independent", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)

    accepted = {r["app"]: r.get("verdict") for r in _load(
        REPO / "docs" / "reports" / "evidence" / "phase3" / f"runtime_corpus_{args.runtime}.jsonl")}
    results = _load(args.results)
    recheck = {r["app"]: r.get("verdict") for r in _load(args.independent)}
    run = {r["app"]: r.get("verdict") for r in results}

    problems = []
    if set(run) != set(accepted):
        problems.append(f"application set differs: missing {sorted(set(accepted) - set(run))}, "
                        f"extra {sorted(set(run) - set(accepted))}")
    for app in sorted(set(run) & set(accepted)):
        if run[app] != accepted[app]:
            problems.append(f"{app}: verdict {run[app]} != accepted {accepted[app]}")
    verified = sorted(a for a, v in run.items() if v == "VERIFIED")
    for app in verified:
        if recheck.get(app) != "AGREE":
            problems.append(f"{app}: independent re-check {recheck.get(app)}")

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        summaries = [{"app": r["app"], "target_runtime": args.runtime, "validation_summary": r["validation_summary"]}
                     for r in results if r.get("validation_summary")]
        with (args.out_dir / f"validation_summaries_{args.runtime}.jsonl").open(
                "w", encoding="utf-8", newline="\n") as fh:
            for row in summaries:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        with (args.out_dir / f"certification_corpus_{args.runtime}.jsonl").open(
                "w", encoding="utf-8", newline="\n") as fh:
            for record in results:
                record.pop("generated_app_path", None)
                record.pop("validation_summary", None)  # kept in validation_summaries_<runtime>.jsonl
                fh.write(json.dumps(record) + "\n")
        (args.out_dir / f"certification_corpus_{args.runtime}_independent.jsonl").write_text(
            args.independent.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")

    counts = collections.Counter(str(v) for v in run.values())
    agree = sum(1 for app in verified if recheck.get(app) == "AGREE")
    print(f"{args.runtime}: {len(run)} apps {dict(sorted(counts.items()))}; "
          f"independent AGREE {agree}/{len(verified)}; "
          f"{'CERTIFIED' if not problems else 'NOT CERTIFIED'}")
    for problem in problems:
        print("  " + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
