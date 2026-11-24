"""Layer 10: the build-artifact record that the sealed evidence manifest carries.

The record content-addresses the runnable artifact a build produced and the project it was built from:

* ``artifact_digest`` - sha256 of the jar the lane built and then executed (the bytes of the one jar the build produced; the
  execution stages exactly those bytes);
* ``artifact_name`` - the jar's file name (a bare name, never a path);
* ``built_tree_digest`` - the digest of the project tree the build ran on, build outputs excluded (the Layer 9 algorithm,
  ``generation_record.tree_digest``).  When the run also carries a Layer 9 generation record, the two must be equal: what was built
  is what was generated.

Pure functions of the build's output and the tree: deterministic, no clock, no randomness, no LLM.  A build that produced no jar
or more than one has no record (``()``), never a partial one.  The record is advisory lineage: it never changes a verdict.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path

from engine.modernization.generation_record import BUILD_OUTPUT_DIRS, tree_digest

KEYS = ("artifact_digest", "artifact_name", "built_tree_digest")
DIGEST_KEYS = ("artifact_digest", "built_tree_digest")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def build_record(class_files: Mapping[str, bytes], project_dir: "str | Path") -> tuple[tuple[str, str], ...]:
    """The sorted ``(key, value)`` record of a build that produced exactly one jar from a hashable project, else ``()``."""
    jars = {name: data for name, data in class_files.items() if name.endswith(".jar")}
    built = tree_digest(project_dir, BUILD_OUTPUT_DIRS)
    if len(jars) != 1 or len(class_files) != 1 or not built:
        return ()
    (name, data), = jars.items()
    if not name or name != Path(name).name:
        return ()
    values = {"artifact_digest": hashlib.sha256(data).hexdigest(), "artifact_name": name, "built_tree_digest": built}
    return tuple(sorted(values.items()))


def shape_problems(pairs: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    """``(field, problem)`` for every way ``pairs`` is not a well-formed record (used by the evidence validator)."""
    keys = sorted(key for key, _value in pairs)
    if keys != sorted(KEYS):
        return [("build_artifact", f"must hold exactly {','.join(sorted(KEYS))}; got {','.join(keys)}")]
    values = dict(pairs)
    problems = [(f"build_artifact.{key}", "is not a sha256 hex digest") for key in DIGEST_KEYS
                if not _SHA256_HEX.fullmatch(values[key])]
    name = values["artifact_name"]
    if not name.endswith(".jar") or name != Path(name).name or "\\" in name:
        problems.append(("build_artifact.artifact_name", "is not a bare jar file name"))
    return problems


def disagrees_with_generation(pairs: tuple[tuple[str, str], ...], generation_pairs: tuple[tuple[str, str], ...]) -> bool:
    """True when a generation record exists and the built tree is not the tree it recorded."""
    generation = dict(generation_pairs)
    return bool(generation) and dict(pairs).get("built_tree_digest") != generation.get("output_digest")
