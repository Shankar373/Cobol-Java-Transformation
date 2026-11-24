"""Layer 9: the Java generation record that the sealed evidence manifest carries.

The record states, as content addresses, what generation produced from which plan:

* ``output_digest`` - sha256 of the generated project tree as written by assembly (``"<posix path>\\0<file sha256>\\n"`` lines in sorted
  path order: the algorithm of ``tools/generation_hashes.py``' ``tree_sha256``, so the two can be compared byte for byte).  It is the
  digest of the project *as generated*; a tree that has since been built (``target/``) legitimately differs;
* ``program_map_digest`` - sha256 of the sorted ``(program id, Java class)`` rows: the COBOL-program to Java-class identity map;
* ``plan_digest`` / ``plan_id`` / ``ir_id`` - the Layer 8 plan record the generation was authorised by (the generation record is
  refused when it names a different plan, IR, source or application than the plan record beside it);
* ``entry_program`` / ``entry_class`` - the plan's entry and the Java class it was generated as;
* ``target_runtime`` (closed: ``runtime_registry.RUNTIME_KEYS``), ``application_id`` and ``source_hash``.

Pure functions of the generated tree, the plan record and the program map: deterministic, no clock, no randomness, no LLM.  With any
input missing there is no record (``()``), never a partial one.  The record is advisory lineage: it never changes generation or a
verdict.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from engine.transformation.runtime_registry import RUNTIME_KEYS
from enterprise.discovery.graph import canonical_bytes

KEYS = ("application_id", "entry_class", "entry_program", "ir_id", "output_digest", "plan_digest", "plan_id",
        "program_map_digest", "source_hash", "target_runtime")
DIGEST_KEYS = ("ir_id", "output_digest", "plan_digest", "plan_id", "program_map_digest", "source_hash")
#: Keys the generation record and the plan record must hold with equal values (one plan, one analysis, one source).
SHARED_WITH_PLAN = ("application_id", "ir_id", "plan_digest", "plan_id", "source_hash")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def tree_digest(project_dir: "str | Path") -> str:
    """sha256 of the project tree, or ``""`` when the directory does not exist or holds a symlink (no record is built from one)."""
    root = Path(project_dir)
    if not root.is_dir():
        return ""
    files: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if any(Path(dirpath, name).is_symlink() for name in (*dirnames, *filenames)):
            return ""
        for name in filenames:
            full = Path(dirpath, name)
            files[full.relative_to(root).as_posix()] = hashlib.sha256(full.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for rel, sha in sorted(files.items()):
        digest.update(f"{rel}\0{sha}\n".encode())
    return digest.hexdigest()


def program_map_digest_of(rows: Iterable[tuple[str, str]]) -> str:
    return hashlib.sha256(canonical_bytes({"programs": sorted([program, java_class] for program, java_class in rows)})).hexdigest()


def build_record(application_id: str, plan: Any, plan_pairs: tuple[tuple[str, str], ...], program_classes: Iterable[tuple[str, str]],
                 entry_class: str, target_runtime: str, project_dir: "str | Path") -> tuple[tuple[str, str], ...]:
    """The sorted ``(key, value)`` record, or ``()`` when any input is missing or inconsistent (no partial record).

    ``plan_pairs`` is the Layer 8 plan record of ``plan``; ``program_classes`` the ``(program id, Java class)`` rows of what was
    generated, which must be exactly the plan's approved programs."""
    rows = tuple(program_classes)
    plan_record = dict(plan_pairs)
    output_digest = tree_digest(project_dir)
    if (not application_id or plan is None or not plan_record or not rows or not entry_class or not output_digest
            or target_runtime not in RUNTIME_KEYS or plan_record.get("application_id") != application_id):
        return ()
    from engine.transformation.entrypoint import normalise

    if sorted(normalise(program) for program, _cls in rows) != sorted(normalise(p) for p in _approved(plan)):
        return ()
    values = {"application_id": application_id, "entry_class": entry_class, "entry_program": plan.oracle.entry_program,
              "ir_id": plan_record.get("ir_id", ""), "output_digest": output_digest,
              "plan_digest": plan_record.get("plan_digest", ""), "plan_id": plan_record.get("plan_id", ""),
              "program_map_digest": program_map_digest_of(rows), "source_hash": plan_record.get("source_hash", ""),
              "target_runtime": target_runtime}
    return tuple(sorted(values.items()))


def _approved(plan: Any) -> tuple[str, ...]:
    from engine.transformation.generation_authority import approved_program_ids

    return approved_program_ids(plan)


def shape_problems(pairs: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    """``(field, problem)`` for every way ``pairs`` is not a well-formed record (used by the evidence validator)."""
    keys = sorted(key for key, _value in pairs)
    if keys != sorted(KEYS):
        return [("java_generation", f"must hold exactly {','.join(sorted(KEYS))}; got {','.join(keys)}")]
    values = dict(pairs)
    problems = [(f"java_generation.{key}", "is not a sha256 hex digest") for key in DIGEST_KEYS
                if not _SHA256_HEX.fullmatch(values[key])]
    if values["target_runtime"] not in RUNTIME_KEYS:
        problems.append(("java_generation.target_runtime", "is not a runtime target"))
    for key in ("application_id", "entry_class", "entry_program"):
        if not values[key]:
            problems.append((f"java_generation.{key}", "is empty"))
    return problems


def disagreements_with_plan(pairs: tuple[tuple[str, str], ...], plan_pairs: tuple[tuple[str, str], ...]) -> list[str]:
    """Shared keys on which a well-formed generation record and plan record differ."""
    generation, plan = dict(pairs), dict(plan_pairs)
    return [key for key in SHARED_WITH_PLAN if generation.get(key) != plan.get(key)]


def verify_record(pairs: tuple[tuple[str, str], ...], application_id: str, plan: Any, plan_pairs: tuple[tuple[str, str], ...],
                  program_classes: Iterable[tuple[str, str]], entry_class: str, target_runtime: str,
                  project_dir: "str | Path") -> list[str]:
    """Problems found re-deriving the record from its inputs (empty when it is exactly the record of those inputs)."""
    if not pairs:
        return ["java_generation: no record"]
    malformed = shape_problems(pairs)
    if malformed:
        return [f"{field}: {problem}" for field, problem in malformed]
    expected = dict(build_record(application_id, plan, plan_pairs, program_classes, entry_class, target_runtime, project_dir))
    if not expected:
        return ["java_generation: the inputs cannot produce a record"]
    return [f"{key}: recorded {value[:16]} but the inputs give {expected[key][:16]}"
            for key, value in sorted(dict(pairs).items()) if value != expected[key]]
