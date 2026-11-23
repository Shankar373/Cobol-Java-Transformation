#!/usr/bin/env python3
"""Reproducible byte-identical GENERATION-HASH snapshot of every fixture app.

The regression method of ``docs/audits/CHANGE_LEDGER.md`` / ``CONTRIBUTING.md``:
generate the project of every fixture application (``fixtures/<app>/cobol``)
for each target runtime, hash every generated file, and compare before and
after a change.  Generation only: pure Python, no Docker, no oracle, no
network, no LLM.

Commands::

    python tools/generation_hashes.py --write docs/audits/generation_hashes.json
    python tools/generation_hashes.py --check docs/audits/generation_hashes.json
    # before/after in one command: regenerate at another ref, compare to a snapshot
    python tools/generation_hashes.py --check docs/audits/generation_hashes.json --ref <git-ref>
    # restrict the app set / runtimes (fast loops, tests)
    python tools/generation_hashes.py --check SNAP --apps workload-minimal,workload-cics

Exit codes: 0 identical (or written), 1 differences found, 2 tool error.

What is hashed
--------------
Each generated file is hashed as RAW BYTES (sha256) - no newline
normalisation, so a CRLF/LF change is a real difference.  Files are keyed by
their sorted project-relative POSIX path.  ``tree_sha256`` is the sha256 of
``"<path>\\0<file sha256>\\n"`` lines in sorted path order.  Symlinks are not
followed or recorded (the generators emit none); a symlink in a generated tree
is a tool error.

Generation mirrors ``api.service.Service._generate_application``: the same
suffix filter as the API ZIP upload (``.cob .cbl .cpy .jcl .txt .dat``), the
same entry-program resolution (``api.ingestion.discover_application``, declared
entry ``Main``), the same ``UniversalModernizationPipeline``.  ``docker_available``
is pinned to ``True``: the live Docker probe would make the capability plan,
and so the output, depend on the host.

Documented exclusions (the ONLY normalisations)
-----------------------------------------------
``EXCLUSIONS`` below is the complete list.  It is empty when the generated
trees contain no known non-deterministic field: ``ProducerManifest.
transformation_timestamp`` (engine/transformation/manifest.py, producer.py) is
written by the producer/verification path (``datetime.now``), which this tool
does not run, and the pipeline's generated tree contains no such file.  The
determinism test (run twice from different temporary directories, diff the
JSON) is what proves that; if a future change introduces a non-deterministic
field it surfaces there and must be added to ``EXCLUSIONS`` with a reason.
Absolute temporary paths are never hashed: refusal messages have the
per-run source directory replaced by ``<SRC>``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "generation-hashes/1"
TOOL = "tools/generation_hashes.py"
DEFAULT_RUNTIMES: tuple[str, ...] = ("spring_boot", "plain_java")
SOURCE_SUFFIXES: tuple[str, ...] = (".cob", ".cbl", ".cpy", ".jcl", ".txt", ".dat")
DECLARED_ENTRYPOINT = "Main"  # ApplicationCreate.java_entrypoint default
EXIT_OK, EXIT_DIFF, EXIT_ERROR = 0, 1, 2


@dataclass(frozen=True)
class Exclusion:
    """A known non-deterministic field removed before hashing."""

    path_glob: str  # project-relative POSIX path (fnmatch)
    json_field: str  # top-level JSON key dropped from that file
    reason: str


# Complete, explicit list. Empty on purpose - see the module docstring.
EXCLUSIONS: tuple[Exclusion, ...] = ()


class ToolError(Exception):
    """Environment/usage failure (exit 2), never a hash difference."""


# --------------------------------------------------------------------- hashing
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _apply_exclusions(rel: str, data: bytes) -> bytes:
    import fnmatch

    for ex in EXCLUSIONS:
        if fnmatch.fnmatch(rel, ex.path_glob):
            obj = json.loads(data.decode("utf-8"))
            obj.pop(ex.json_field, None)
            return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return data


def hash_tree(root: Path) -> dict[str, Any]:
    """Return ``{"files": {rel: sha256}, "tree_sha256": ...}`` for a directory."""
    files: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in list(dirnames) + list(filenames):
            full = Path(dirpath, name)
            if full.is_symlink():
                raise ToolError(f"symlink in generated tree: {full}")
        for name in filenames:
            full = Path(dirpath, name)
            rel = full.relative_to(root).as_posix()
            files[rel] = _sha256(_apply_exclusions(rel, full.read_bytes()))
    ordered = dict(sorted(files.items()))
    digest = hashlib.sha256()
    for rel, sha in ordered.items():
        digest.update(f"{rel}\0{sha}\n".encode())
    return {"files": ordered, "tree_sha256": digest.hexdigest()}


# ------------------------------------------------------------------ generation
def _import_engine(repo_root: Path) -> None:
    sys.path.insert(0, str(repo_root))
    os.chdir(repo_root)


def discover_fixtures(fixtures_dir: Path) -> list[str]:
    return sorted(p.parent.name for p in fixtures_dir.glob("*/cobol"))


def _stage_source(cobol_dir: Path, dest: Path) -> None:
    """Copy source files the way the API ZIP upload selects them."""
    for f in sorted(cobol_dir.rglob("*")):
        if f.is_file() and f.suffix.lower() in SOURCE_SUFFIXES:
            target = dest / f.relative_to(cobol_dir).as_posix()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.read_bytes())


def _resolve_entry(source: Path, app_id: str) -> str:
    """Mirror ``Service._resolve_entry_program`` (declared entry ``Main``)."""
    from api.ingestion import discover_application

    discovery = discover_application(source, app_id)
    program_ids = [
        str(p.get("program_id", "")) for p in discovery.cobol_programs if p.get("program_id")
    ]
    if not program_ids:
        return DECLARED_ENTRYPOINT

    def key(value: str) -> str:
        return re.sub(r"[-_\s'\"`]+", "", value).upper()

    keys = {key(pid): pid for pid in program_ids}
    if key(DECLARED_ENTRYPOINT) in keys:
        return keys[key(DECLARED_ENTRYPOINT)]
    called = {key(str(e.get("target", ""))) for e in discovery.call_dependencies if e.get("target")}
    roots = [pid for pid in program_ids if key(pid) not in called]
    return roots[0] if len(roots) == 1 else DECLARED_ENTRYPOINT



def _refusal_code(errors: tuple[str, ...], limitations: tuple[str, ...]) -> str:
    first = (errors or limitations or ("",))[0]
    if first.startswith("Transformation plan contains non-transformable programs"):
        return "PLAN_SKIPPED_PROGRAMS"
    if first.startswith("Transformation plan contains non-transformable CALLs"):
        return "PLAN_SKIPPED_CALLS"
    if first.startswith("Transformation plan contains non-transformable copybooks"):
        return "PLAN_SKIPPED_COPYBOOKS"
    if first.startswith("Unsupported construct in generated Java"):
        return "UNSUPPORTED_SYMBOL_IN_GENERATED_JAVA"
    if first.startswith("Assembly failed"):
        return "ASSEMBLY_FAILED"
    if first.startswith("Discovery"):
        return "DISCOVERY_INCOMPLETE"
    if first.startswith("Transformation"):
        return "TRANSFORMATION_FAILED"
    return "GENERATION_REFUSED"


def _scrub(text: str, *paths: Path) -> str:
    out = text
    for p in paths:
        for variant in {str(p), p.as_posix(), str(p.resolve()), p.resolve().as_posix()}:
            out = out.replace(variant, "<SRC>")
    return out


def generate_one(fixtures_dir: Path, app: str, runtime: str, scratch: Path) -> dict[str, Any]:
    """Generate one (app, runtime); return its snapshot record."""
    from engine.modernization.pipeline import ModernizationConfig, UniversalModernizationPipeline

    source = scratch / "src"
    output = scratch / "out"
    source.mkdir(parents=True)
    output.mkdir(parents=True)
    _stage_source(fixtures_dir / app / "cobol", source)
    try:
        config = ModernizationConfig(
            source_dir=str(source),
            output_dir=str(output),
            application_id=f"e2e-{app}",
            entrypoint=_resolve_entry(source, f"e2e-{app}"),
            docker_available=True,
            target_runtime=runtime,
        )
        report = UniversalModernizationPipeline(config).execute()
    except Exception as exc:  # recorded by name, never skipped
        return {
            "status": "exception",
            "exception": type(exc).__name__,
            "message": _scrub(str(exc), source, output).splitlines()[0][:300] if str(exc) else "",
        }
    if not report.generation_success or not report.generated_project_dir:
        errors = tuple(_scrub(e, source, output) for e in report.generation_errors)
        limits = tuple(_scrub(e, source, output) for e in report.limitations)
        return {
            "status": "refused",
            "refusal_code": _refusal_code(errors, limits),
            "unsupported_markers": sorted(
                {m for t in (*errors, *limits) for m in re.findall(r"UNSUPPORTED_[A-Z_]+", t)}
            ),
            "errors": list(errors),
            "limitations": list(limits),
        }
    tree = hash_tree(Path(report.generated_project_dir))
    return {"status": "generated", **tree}


def build_snapshot(fixtures_dir: Path, apps: list[str], runtimes: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    for app in apps:
        result[app] = {}
        for runtime in runtimes:
            with tempfile.TemporaryDirectory(prefix="genhash-") as tmp:
                result[app][runtime] = generate_one(fixtures_dir, app, runtime, Path(tmp))
    return {
        "schema": SCHEMA,
        "tool": TOOL,
        "runtimes": list(runtimes),
        "exclusions": [
            {"path_glob": e.path_glob, "json_field": e.json_field, "reason": e.reason}
            for e in EXCLUSIONS
        ],
        "apps": result,
    }


def canonical_json(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=1, sort_keys=True, ensure_ascii=True) + "\n"


# ------------------------------------------------------------------ comparison
def diff_snapshots(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Precise per-app/runtime/file differences (empty list = identical)."""
    lines: list[str] = []
    exp_apps, act_apps = expected.get("apps", {}), actual.get("apps", {})
    for app in sorted(set(exp_apps) | set(act_apps)):
        if app not in act_apps:
            lines.append(f"{app}: missing from regenerated set")
            continue
        if app not in exp_apps:
            lines.append(f"{app}: not in snapshot")
            continue
        for runtime in sorted(set(exp_apps[app]) | set(act_apps[app])):
            e, a = exp_apps[app].get(runtime), act_apps[app].get(runtime)
            tag = f"{app}/{runtime}"
            if e is None or a is None:
                lines.append(f"{tag}: runtime present only in {'snapshot' if a is None else 'regenerated'}")
            elif e.get("status") != a.get("status"):
                lines.append(f"{tag}: status {e.get('status')} -> {a.get('status')}")
            elif e["status"] == "generated":
                lines.extend(_diff_files(tag, e["files"], a["files"]))
            elif e != a:
                lines.append(f"{tag}: {e['status']} record changed: {e} -> {a}")
    return lines


def _diff_files(tag: str, exp: dict[str, str], act: dict[str, str]) -> list[str]:
    out = []
    for rel in sorted(set(exp) | set(act)):
        if rel not in act:
            out.append(f"{tag}: file removed: {rel}")
        elif rel not in exp:
            out.append(f"{tag}: file added: {rel}")
        elif exp[rel] != act[rel]:
            out.append(f"{tag}: file changed: {rel} ({exp[rel][:12]} -> {act[rel][:12]})")
    return out


def summarize(snapshot: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for app in snapshot["apps"].values():
        for rec in app.values():
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    total = sum(counts.values())
    parts = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
    return f"{len(snapshot['apps'])} apps x {len(snapshot['runtimes'])} runtimes = {total} builds ({parts})"


# ------------------------------------------------------------------------- CLI
def _git(*args: str, cwd: Path) -> None:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ToolError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")


def _generate_at_ref(repo_root: Path, ref: str, apps: list[str] | None, runtimes: tuple[str, ...]) -> dict[str, Any]:
    """Run this tool against ``ref`` inside a temporary ``git worktree``."""
    tmp = Path(tempfile.mkdtemp(prefix="genhash-ref-"))
    wt = tmp / "wt"
    out = tmp / "snapshot.json"
    try:
        _git("worktree", "add", "--detach", str(wt), ref, cwd=repo_root)
        cmd = [sys.executable, str(Path(__file__).resolve()), "--repo-root", str(wt),
               "--write", str(out), "--runtimes", ",".join(runtimes)]
        if apps:
            cmd += ["--apps", ",".join(apps)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ToolError(f"generation at ref {ref} failed:\n{proc.stdout}{proc.stderr}")
        return json.loads(out.read_text(encoding="utf-8"))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo_root, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _load_snapshot(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read snapshot {path}: {exc}") from exc
    if data.get("schema") != SCHEMA:
        raise ToolError(f"unsupported snapshot schema {data.get('schema')!r} (expected {SCHEMA})")
    return data


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", metavar="PATH", help="generate and write a snapshot")
    mode.add_argument("--check", metavar="PATH", help="regenerate and compare to a snapshot")
    p.add_argument("--ref", help="generate at this git ref via a temporary git worktree")
    p.add_argument("--apps", help="comma-separated fixture names (default: all)")
    p.add_argument("--runtimes", default=",".join(DEFAULT_RUNTIMES))
    p.add_argument("--repo-root", help=argparse.SUPPRESS)
    p.add_argument("--fixtures-dir", help="fixture root (default: <repo>/fixtures); tests use a mutated copy")
    return p.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]
    runtimes = tuple(r for r in args.runtimes.split(",") if r)
    wanted = [a for a in (args.apps or "").split(",") if a]
    expected = _load_snapshot(Path(args.check)) if args.check else None
    if args.ref:
        snapshot = _generate_at_ref(repo_root, args.ref, wanted or None, runtimes)
    else:
        _import_engine(repo_root)
        fixtures_dir = Path(args.fixtures_dir).resolve() if args.fixtures_dir else repo_root / "fixtures"
        available = discover_fixtures(fixtures_dir)
        unknown = [a for a in wanted if a not in available]
        if unknown:
            raise ToolError(f"unknown fixture(s): {', '.join(unknown)}")
        snapshot = build_snapshot(fixtures_dir, wanted or available, runtimes)
    if expected is None:
        Path(args.write).write_text(canonical_json(snapshot), encoding="utf-8", newline="\n")
        print(f"wrote {args.write}: {summarize(snapshot)}")
        return EXIT_OK
    if wanted:  # restricted check: compare only the selected apps
        expected = {**expected, "apps": {k: v for k, v in expected["apps"].items() if k in wanted}}
    diffs = diff_snapshots(expected, snapshot)
    if diffs:
        print(f"DIFFERENCES ({len(diffs)}): {summarize(snapshot)}")
        for line in diffs:
            print("  " + line)
        return EXIT_DIFF
    print(f"identical: {summarize(snapshot)}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except ToolError as exc:
        print(f"tool error: {exc}", file=sys.stderr)
    except Exception:  # noqa: BLE001 - exit 2 with the traceback, never a false "identical"
        traceback.print_exc()
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
