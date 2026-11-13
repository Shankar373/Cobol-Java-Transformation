"""Exact-run certification summary: aggregate the four runtime artifacts of ONE workflow run.

``tools/certification_summary.py`` derives a summary from committed evidence.  This tool is
the CI side of G-25: inside ``certification.yml`` each runtime job writes ``run_identity.json``
(``runtime-identity``) next to its evidence, and a final job downloads the four artifacts and
runs ``run-summary``, which refuses unless every runtime is complete and consistent.

Identity is taken from the workflow environment only (``GITHUB_SHA``, ``GITHUB_RUN_ID``,
``GITHUB_RUN_NUMBER`` ...).  There is no argument for it: a typed commit or run id would be an
assertion, not proof.  Each runtime artifact carries the identity it saw and must equal the
aggregating job's.  Nothing here pushes, signs or contacts a service; the summary is a pure
function of the artifact files, the checkout being certified and the environment.

Usage (inside the workflow)::

    python -m tools.certification_run_summary runtime-identity --runtime quarkus --out-dir certification
    python -m tools.certification_run_summary run-summary --artifacts artifacts --out certification_summary.json
    python -m tools.certification_run_summary verify --summary certification_summary.json --artifacts artifacts

Exit codes: 0 certified / consistent, 1 problems found (the summary is still written, for
diagnosis), 2 identity missing or malformed (nothing is written).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from tools.certification_summary import (
    CORPUS_DIR, RUNTIMES, _load, fixture_manifest, runtime_block_from_files,
)

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "systemaops.certification_run_summary"
SCHEMA_VERSION = 1
ARTIFACT_PREFIX = "certification-"
PROVENANCE_FIELDS = ("build_identity", "build_image_id", "runtime_identity", "runtime_image_id")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_REPO_IDENTITY = re.compile(r"[\w./-]+@sha256:[0-9a-f]{64}")
_CERTIFIED_LINE = re.compile(r"; CERTIFIED$")
_SHA = re.compile(r"[0-9a-f]{40}")


class IdentityError(ValueError):
    """The workflow identity (commit SHA, run id) is missing or malformed."""


def identity_from_env(env: Mapping[str, str]) -> dict:
    sha = env.get("GITHUB_SHA", "")
    run_id = env.get("GITHUB_RUN_ID", "")
    if not _SHA.fullmatch(sha):
        raise IdentityError("GITHUB_SHA is missing or is not a full 40-character lowercase hex SHA")
    if not run_id.isdigit():
        raise IdentityError("GITHUB_RUN_ID is missing or is not numeric")
    attempt = env.get("GITHUB_RUN_ATTEMPT", "")
    if not attempt.isdigit():
        raise IdentityError("GITHUB_RUN_ATTEMPT is missing or is not numeric")
    return {
        "commit_sha": sha, "run_id": run_id,
        "run_number": env.get("GITHUB_RUN_NUMBER", ""), "run_attempt": attempt,
        "workflow": env.get("GITHUB_WORKFLOW", ""), "repository": env.get("GITHUB_REPOSITORY", ""),
    }


def _expected_applications(repo: Path) -> list[str]:
    path = repo / CORPUS_DIR / f"runtime_corpus_{RUNTIMES[0]}.jsonl"
    return [row["app"] for row in _load(path)]


def write_runtime_identity(out_dir: Path, runtime: str, env: Mapping[str, str], repo: Path = REPO) -> dict:
    """Write ``run_identity.json`` for one runtime job from its own environment and checkout."""
    if runtime not in RUNTIMES:
        raise ValueError(f"unknown runtime {runtime!r}")
    identity = identity_from_env(env)
    data = {
        "runtime": runtime, "commit_sha": identity["commit_sha"], "run_id": identity["run_id"],
        "run_number": identity["run_number"], "run_attempt": identity["run_attempt"],
        "fixture_manifest": fixture_manifest(repo, _expected_applications(repo)),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run_identity.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return data


def _required_files(runtime: str) -> tuple[str, ...]:
    return (
        "summary.txt", "e2e.jsonl", "independent.jsonl", "run_identity.json", "oracle_image.json",
        "provenance/docker-image-provenance.json",
        f"evidence/certification_corpus_{runtime}.jsonl",
        f"evidence/certification_corpus_{runtime}_independent.jsonl",
        f"evidence/validation_summaries_{runtime}.jsonl",
    )


def _identity_matches_kind(provenance: dict, prefix: str, allowed: dict[str, re.Pattern[str]]) -> bool:
    """The ``<prefix>_identity`` has the form its declared ``<prefix>_identity_kind`` requires.

    A locally built image has no repo digest: its identity is its image id (kind ``image-id``) and must
    equal ``<prefix>_image_id``.  A registry image is pinned by ``name@sha256:...`` (kind ``repo-digest``).
    """
    kind = str(provenance.get(f"{prefix}_identity_kind") or "")
    value = str(provenance.get(f"{prefix}_identity") or "")
    pattern = allowed.get(kind)
    if pattern is None or not pattern.fullmatch(value):
        return False
    return kind != "image-id" or value == provenance.get(f"{prefix}_image_id")


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _runtime_result(artifacts: Path, runtime: str, identity: dict, expected_apps: list[str],
                    expected_manifest: dict, accepted: dict[str, object]) -> tuple[dict | None, list[str]]:
    problems: list[str] = []
    root = artifacts / f"{ARTIFACT_PREFIX}{runtime}"
    if not root.is_dir():
        return None, [f"{runtime}: runtime artifact is missing"]
    missing = [name for name in _required_files(runtime) if not (root / name).is_file()]
    if missing:
        problems.append(f"{runtime}: partial upload, missing {', '.join(missing)}")
        return None, problems

    stored = _read_json(root / "run_identity.json")
    if stored is None:
        problems.append(f"{runtime}: run_identity.json is unreadable")
    else:
        if stored.get("runtime") != runtime:
            problems.append(f"{runtime}: run_identity.json names runtime {stored.get('runtime')!r}")
        if stored.get("commit_sha") != identity["commit_sha"]:
            problems.append(f"{runtime}: artifact was produced for commit {stored.get('commit_sha')!r}, "
                            f"this run certifies {identity['commit_sha']}")
        if stored.get("run_id") != identity["run_id"]:
            problems.append(f"{runtime}: artifact belongs to run id {stored.get('run_id')!r}, "
                            f"this is run {identity['run_id']}")
        if stored.get("run_attempt") != identity["run_attempt"]:
            problems.append(f"{runtime}: artifact is from attempt {stored.get('run_attempt')!r} of the run, "
                            f"this is attempt {identity['run_attempt']}")
        if stored.get("fixture_manifest") != expected_manifest:
            problems.append(f"{runtime}: fixture manifest differs from the checkout being certified")

    verdict_line = (root / "summary.txt").read_text(encoding="utf-8").strip().splitlines()
    last = verdict_line[-1] if verdict_line else ""
    if not _CERTIFIED_LINE.search(last):
        problems.append(f"{runtime}: the runtime job did not certify ({last or 'empty summary.txt'})")

    evidence = root / "evidence"
    names = tuple(f"{ARTIFACT_PREFIX}{runtime}/evidence/{n}" for n in (
        f"certification_corpus_{runtime}.jsonl", f"certification_corpus_{runtime}_independent.jsonl",
        f"validation_summaries_{runtime}.jsonl"))
    try:
        block, apps = runtime_block_from_files(
            evidence / f"certification_corpus_{runtime}.jsonl",
            evidence / f"certification_corpus_{runtime}_independent.jsonl",
            evidence / f"validation_summaries_{runtime}.jsonl", names)
        run_verdicts = {r["app"]: r.get("verdict")
                        for r in _load(evidence / f"certification_corpus_{runtime}.jsonl")}
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        problems.append(f"{runtime}: evidence is unreadable ({type(exc).__name__}: {str(exc)[:80]})")
        return None, problems

    counts = collections.Counter(apps)
    duplicates = sorted(a for a, n in counts.items() if n > 1)
    if duplicates:
        problems.append(f"{runtime}: duplicate application rows: {', '.join(duplicates)}")
    if sorted(counts) != sorted(expected_apps):
        absent = sorted(set(expected_apps) - set(counts))
        extra = sorted(set(counts) - set(expected_apps))
        problems.append(f"{runtime}: application set differs from the accepted evidence "
                        f"(missing {absent[:5]}, unexpected {extra[:5]})")
    differing = sorted(a for a in set(run_verdicts) & set(accepted) if run_verdicts[a] != accepted[a])
    if differing:
        problems.append(f"{runtime}: verdicts differ from the accepted evidence for {', '.join(differing[:5])}")
    if not block["independent_covers_exactly_the_verified"]:
        problems.append(f"{runtime}: the independent re-check does not AGREE for exactly the VERIFIED applications")
    if block["totals"]["other"]:
        problems.append(f"{runtime}: unexpected verdict values {block['totals']['other']}")

    provenance = _read_json(root / "provenance" / "docker-image-provenance.json") or {}
    missing_fields = [f for f in ("build_image_id", "runtime_image_id")
                      if not _IMAGE_ID.fullmatch(str(provenance.get(f) or ""))]
    if not _identity_matches_kind(provenance, "build", {"repo-digest": _REPO_IDENTITY, "image-id": _IMAGE_ID}):
        missing_fields.append("build_identity")
    # the runtime image is always pinned by repo digest (the adapter refuses anything else)
    if not _identity_matches_kind(provenance, "runtime", {"repo-digest": _REPO_IDENTITY}):
        missing_fields.append("runtime_identity")
    if missing_fields:
        problems.append(f"{runtime}: image provenance lacks a valid digest for {', '.join(missing_fields)}")
    oracle = _read_json(root / "oracle_image.json") or {}
    oracle_ok = bool(_IMAGE_ID.fullmatch(str(oracle.get("id", ""))))
    if not oracle_ok:
        problems.append(f"{runtime}: oracle image identity is missing or is not a sha256 digest")
    jdks = block["jdk_versions"]
    if not jdks:
        problems.append(f"{runtime}: JDK version is not recorded in the validation summaries")
    elif len(jdks) > 1:
        problems.append(f"{runtime}: several JDK versions recorded: {jdks}")

    block["toolchain"] = {
        "build_image": provenance.get("build_image"), "build_identity": provenance.get("build_identity"),
        "build_image_id": provenance.get("build_image_id"),
        "build_identity_kind": provenance.get("build_identity_kind"),
        "runtime_image": provenance.get("runtime_image"), "runtime_identity": provenance.get("runtime_identity"),
        "runtime_identity_kind": provenance.get("runtime_identity_kind"),
        "runtime_image_id": provenance.get("runtime_image_id"),
        "oracle_image": oracle.get("image"), "oracle_image_id": oracle.get("id"),
        "jdk": jdks[0] if len(jdks) == 1 else None,
        "complete": not missing_fields and oracle_ok and len(jdks) == 1,
    }
    return block, problems


def build_run_summary(artifacts: Path, env: Mapping[str, str], repo: Path = REPO) -> dict:
    """Aggregate the runtime artifacts under ``artifacts`` for the run described by ``env``."""
    identity = identity_from_env(env)
    expected_apps = _expected_applications(repo)
    expected_manifest = fixture_manifest(repo, expected_apps)
    problems: list[str] = []
    runtimes: dict[str, dict | None] = {}
    for runtime in RUNTIMES:
        accepted = {r["app"]: r.get("verdict")
                    for r in _load(repo / CORPUS_DIR / f"runtime_corpus_{runtime}.jsonl")}
        if sorted(accepted) != sorted(expected_apps):
            problems.append(f"{runtime}: the accepted evidence covers a different application set than "
                            f"{RUNTIMES[0]}'s; the runtimes cannot be certified against one fixture manifest")
        block, found = _runtime_result(artifacts, runtime, identity, list(accepted), expected_manifest, accepted)
        runtimes[runtime] = block
        problems += found
    provenance_complete = all(b is not None and b["toolchain"]["complete"] for b in runtimes.values())
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "identity": identity,
        "fixtures": expected_manifest,
        "runtimes": runtimes,
        "toolchain_provenance_complete": provenance_complete,
        "problems": problems,
        "certified": not problems,
        "not_proven": [
            "the evidence is self-attested by this workflow's own jobs and is not independently signed or tamper-proof",
            "no IBM runtime evidence; equivalence is against GnuCOBOL 3.1.2 for the recorded inputs",
            "quarkus and micronaut are certified in command mode only; jakarta_ee is not certified",
        ],
    }


def verify_run_summary(summary: dict, artifacts: Path, env: Mapping[str, str], repo: Path = REPO) -> list[str]:
    """Problems found when recomputing ``summary`` from the artifacts and the environment."""
    if summary.get("schema") != SCHEMA or summary.get("schema_version") != SCHEMA_VERSION:
        return [f"unsupported schema {summary.get('schema')!r} v{summary.get('schema_version')!r}"]
    rebuilt = build_run_summary(artifacts, env, repo)
    problems: list[str] = []
    for key in sorted(set(rebuilt) | set(summary)):
        if summary.get(key) != rebuilt.get(key):
            problems.append(f"{key}: differs from the value recomputed from the artifacts")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ident = sub.add_parser("runtime-identity")
    ident.add_argument("--runtime", required=True, choices=RUNTIMES)
    ident.add_argument("--out-dir", required=True, type=Path)
    run = sub.add_parser("run-summary")
    run.add_argument("--artifacts", required=True, type=Path)
    run.add_argument("--out", required=True, type=Path)
    ver = sub.add_parser("verify")
    ver.add_argument("--summary", required=True, type=Path)
    ver.add_argument("--artifacts", required=True, type=Path)
    args = parser.parse_args(argv)
    env = os.environ

    try:
        if args.command == "runtime-identity":
            write_runtime_identity(args.out_dir, args.runtime, env)
            print(f"wrote {args.out_dir / 'run_identity.json'}")
            return 0
        if args.command == "run-summary":
            summary = build_run_summary(args.artifacts, env)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            for problem in summary["problems"]:
                print("PROBLEM:", problem)
            print(f"certified={summary['certified']} toolchain_provenance_complete={summary['toolchain_provenance_complete']}")
            return 0 if summary["certified"] else 1
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        problems = verify_run_summary(summary, args.artifacts, env)
        for problem in problems:
            print("PROBLEM:", problem)
        print("summary consistent with the artifacts" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    except IdentityError as exc:
        print(f"IDENTITY: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
