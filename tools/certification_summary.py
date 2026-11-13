"""Machine-readable corpus certification summary, derived from evidence (G-17).

Published certification numbers (applications, VERIFIED, refused, independent
AGREE) used to be typed into documents by hand, with nothing to catch a
number that no longer matched the evidence.  This tool

* ``build``: derives a versioned summary from the accepted corpus evidence,
  the independent re-check and the validation summaries, tied to an exact
  commit SHA and workflow run id supplied by the caller;
* ``check``: recomputes everything from the evidence files and fails on any
  difference, and fails when documentation states counts that the summary
  does not support.

Nothing here runs an application or contacts a service; the output is a pure
function of the files it reads.  Hashes are taken over content with CRLF
normalised to LF so a Windows checkout and a Linux checkout agree.

Usage::

    python tools/certification_summary.py build --commit SHA --run-id ID --out FILE
    python tools/certification_summary.py check [FILE]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "systemaops.certification_summary"
SCHEMA_VERSION = 1
RUNTIMES = ("plain_java", "spring_boot", "quarkus", "micronaut")
CORPUS_DIR = "docs/reports/evidence/phase3"
SUMMARIES_DIR = "docs/reports/evidence/validation_summaries"
DEFAULT_SUMMARY = "docs/reports/evidence/certification/certification_summary.json"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def sha256_normalised(path: Path) -> str:
    """SHA-256 of a file with CRLF normalised to LF."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fixture_manifest(repo: Path, applications: list[str]) -> dict:
    """Hash every file of every corpus application's fixture directory."""
    entries: list[str] = []
    for app in sorted(applications):
        root = repo / "fixtures" / app
        files = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []
        entries.append(f"{app}\0<dir:{'present' if root.is_dir() else 'missing'}>")
        for path in files:
            rel = path.relative_to(repo / "fixtures").as_posix()
            entries.append(f"{rel}\0{sha256_normalised(path)}")
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return {"manifest_sha256": digest, "application_count": len(applications),
            "applications": sorted(applications)}


def _runtime_block(repo: Path, runtime: str) -> tuple[dict, list[str]]:
    corpus_path = repo / CORPUS_DIR / f"runtime_corpus_{runtime}.jsonl"
    indep_path = repo / CORPUS_DIR / f"runtime_corpus_{runtime}_independent.jsonl"
    summaries_path = repo / SUMMARIES_DIR / f"validation_summaries_{runtime}.jsonl"
    corpus = _load(corpus_path)
    independent = _load(indep_path)
    summaries = _load(summaries_path)

    verdicts = collections.Counter(str(r.get("verdict")) for r in corpus)
    verified = sorted(r["app"] for r in corpus if r.get("verdict") == "VERIFIED")
    indep = {r["app"]: r.get("verdict") for r in independent}
    indep_counts = collections.Counter(str(v) for v in indep.values())
    jdks = sorted({
        (row["validation_summary"].get("compilation", {}).get("jdk", {}) or {}).get("version")
        for row in summaries
    } - {None})
    references = sorted({row["validation_summary"].get("reference") for row in summaries} - {None})

    refused = [{"app": r["app"], "reason": r.get("error") or ""}
               for r in corpus if r.get("verdict") is None]
    unavailable = [{"app": r["app"], "reason": r.get("error") or r.get("verdict_differences") or ""}
                   for r in corpus if r.get("verdict") == "UNAVAILABLE"]
    other = {k: v for k, v in verdicts.items() if k not in ("VERIFIED", "UNAVAILABLE", "None")}
    independent_ok = (sorted(a for a, v in indep.items() if v == "AGREE") == verified
                      and set(indep) == set(verified))
    block = {
        "totals": {
            "applications": len(corpus),
            "verified": verdicts.get("VERIFIED", 0),
            "refused_by_name": verdicts.get("None", 0),
            "unavailable": verdicts.get("UNAVAILABLE", 0),
            "other": other,
        },
        "refused": sorted(refused, key=lambda r: r["app"]),
        "unavailable": sorted(unavailable, key=lambda r: r["app"]),
        "independent": {"checked": len(indep), "agree": indep_counts.get("AGREE", 0),
                        "other": {k: v for k, v in indep_counts.items() if k != "AGREE"}},
        "independent_covers_exactly_the_verified": independent_ok,
        "validation_summary_rows": len(summaries),
        "jdk_versions": jdks,
        "reference": references,
        "evidence_sha256": {
            f"{CORPUS_DIR}/{corpus_path.name}": sha256_normalised(corpus_path),
            f"{CORPUS_DIR}/{indep_path.name}": sha256_normalised(indep_path),
            f"{SUMMARIES_DIR}/{summaries_path.name}": sha256_normalised(summaries_path),
        },
    }
    block["status"] = (
        "CERTIFIED" if independent_ok and not other and block["totals"]["verified"] > 0
        else "NOT_CERTIFIED")
    return block, [r["app"] for r in corpus]


def build_summary(*, commit_sha: str, run_id: str, repo: Path = REPO,
                  image_provenance: dict | None = None) -> dict:
    if not _SHA.match(commit_sha):
        raise ValueError("commit_sha must be a full 40-character lowercase hex SHA")
    if not str(run_id).isdigit():
        raise ValueError("run_id must be a numeric workflow run id")
    runtimes: dict[str, dict] = {}
    app_sets: dict[str, list[str]] = {}
    for runtime in RUNTIMES:
        runtimes[runtime], app_sets[runtime] = _runtime_block(repo, runtime)
    first = sorted(app_sets[RUNTIMES[0]])
    same_apps = all(sorted(v) == first for v in app_sets.values())
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "source": {
            "commit_sha": commit_sha,
            "workflow": "certification.yml",
            "workflow_run_id": str(run_id),
            "workflow_run_url": f"https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/{run_id}",
            "assertion_note": (
                "commit_sha and workflow_run_id are asserted by whoever built this summary; no evidence file "
                "records them, so `check` cannot recompute them. Verify with `gh run view <run id> --json "
                "headSha,conclusion`."),
        },
        "fixtures": {**fixture_manifest(repo, first), "same_applications_on_every_runtime": same_apps},
        "runtimes": runtimes,
        "toolchain": {
            "reference_runtime": "GnuCOBOL 3.1.2",
            "image_identities": image_provenance,
            "image_identities_note": (
                None if image_provenance else
                "not captured: the committed evidence of this run does not include "
                "docker-image-provenance.json; later runs record it with --provenance"),
        },
        "not_proven": [
            "no IBM runtime evidence; equivalence is against GnuCOBOL 3.1.2 for the recorded inputs",
            "quarkus and micronaut are certified in command mode only; jakarta_ee is not certified",
        ],
    }


def check_summary(summary: dict, repo: Path = REPO) -> list[str]:
    """Problems found when recomputing ``summary`` from the evidence files."""
    problems: list[str] = []
    for app in summary.get("fixtures", {}).get("applications", []):
        root = repo / "fixtures" / app
        if not root.is_dir() or not any(p.is_file() for p in root.rglob("*")):
            problems.append(f"fixtures/{app}: directory is missing or empty, so its content is not covered by the manifest hash")
    if summary.get("schema") != SCHEMA or summary.get("schema_version") != SCHEMA_VERSION:
        return [f"unsupported schema {summary.get('schema')!r} v{summary.get('schema_version')!r}"]
    source = summary.get("source", {})
    try:
        rebuilt = build_summary(commit_sha=source.get("commit_sha", ""),
                                run_id=source.get("workflow_run_id", ""), repo=repo,
                                image_provenance=summary.get("toolchain", {}).get("image_identities"))
    except (ValueError, FileNotFoundError, KeyError) as exc:
        return [f"cannot recompute from evidence: {exc}"]
    for runtime in RUNTIMES:
        have, want = summary.get("runtimes", {}).get(runtime), rebuilt["runtimes"][runtime]
        if have != want:
            for key in sorted(set(want) | set(have or {})):
                if (have or {}).get(key) != want.get(key):
                    problems.append(f"{runtime}.{key}: summary {(have or {}).get(key)!r} != evidence {want.get(key)!r}")
    if summary.get("fixtures") != rebuilt["fixtures"]:
        problems.append("fixtures: manifest hash or application list differs from the fixtures directory")
    if not summary.get("not_proven"):
        problems.append("not_proven is empty: a summary must state what it does not prove")
    for section in ("source", "toolchain", "not_proven", "schema", "schema_version"):
        if summary.get(section) != rebuilt[section]:
            problems.append(f"{section}: differs from the value rebuilt from the evidence")
    for runtime in RUNTIMES:
        block = rebuilt["runtimes"][runtime]
        if block["status"] != "CERTIFIED":
            problems.append(f"{runtime}: evidence does not certify (status {block['status']})")
    return problems


def corpus_claim(summary: dict) -> dict | None:
    """The single set of numbers every runtime shares, or ``None`` if they differ."""
    totals = {json.dumps(b["totals"], sort_keys=True) for b in summary["runtimes"].values()}
    agree = {b["independent"]["agree"] for b in summary["runtimes"].values()}
    if len(totals) != 1 or len(agree) != 1:
        return None
    t = next(iter(summary["runtimes"].values()))["totals"]
    return {**t, "independent_agree": next(iter(agree))}


def check_documentation(summary: dict, text: str, name: str) -> list[str]:
    """Counts a document states must equal what the evidence supports."""
    claim = corpus_claim(summary)
    if claim is None:
        return [f"{name}: runtimes disagree, so no single corpus count can be published"]
    problems = []
    if not re.search(r"\d+ of \d+ (?:fixture )?applications? VERIFIED", text):
        problems.append(f"{name}: states no corpus VERIFIED count, so nothing was validated against the evidence")
    for found in re.finditer(r"(\d+) of (\d+) (?:fixture )?applications? VERIFIED", text):
        if (int(found.group(1)), int(found.group(2))) != (claim["verified"], claim["applications"]):
            problems.append(f"{name}: states {found.group(0)!r}, evidence says "
                            f"{claim['verified']} of {claim['applications']}")
    for found in re.finditer(r"AGREE (\d+)/(\d+)", text):
        if (int(found.group(1)), int(found.group(2))) != (claim["independent_agree"], claim["verified"]):
            problems.append(f"{name}: states {found.group(0)!r}, evidence says "
                            f"AGREE {claim['independent_agree']}/{claim['verified']}")
    for found in re.finditer(r"(\d+) refused by name", text):
        if int(found.group(1)) != claim["refused_by_name"]:
            problems.append(f"{name}: states {found.group(0)!r}, evidence says {claim['refused_by_name']}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--commit", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--provenance", type=Path, help="docker-image-provenance.json of the run")
    build.add_argument("--out", type=Path, default=REPO / DEFAULT_SUMMARY)
    check = sub.add_parser("check")
    check.add_argument("summary", nargs="?", type=Path, default=REPO / DEFAULT_SUMMARY)
    args = parser.parse_args(argv)

    if args.command == "build":
        provenance = json.loads(args.provenance.read_text(encoding="utf-8")) if args.provenance else None
        summary = build_summary(commit_sha=args.commit, run_id=args.run_id, image_provenance=provenance)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
        return 0

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    problems = check_summary(summary)
    for doc in ("README.md",):
        problems += check_documentation(summary, (REPO / doc).read_text(encoding="utf-8"), doc)
    for problem in problems:
        print("PROBLEM:", problem)
    print("certification summary consistent with evidence" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
