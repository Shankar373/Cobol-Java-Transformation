"""The claims program through statement lowering equals GnuCOBOL (audit T5).

CLAIMS used to take a heuristic "decision" template lane; the template
tests asserted its strings (``THRESHOLD = 500``, input/output directory
arguments). The lanes are gone and every program is generated from its
lowered statements, so this test pins behaviour instead: the original
program and source mutations of it (outcome label, threshold, renamed input
and result fields) run on the GnuCOBOL 3.1.2 oracle and as generated Java,
and stdout, stderr, the exit status and both output files must be equal.

The program reads ``/workspace/input`` and writes ``/workspace/output`` (its
ASSIGN clauses), so both sides run in containers with those mounts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.producer import TransformationProducer
from tests.oracle_java_helpers import ORACLE_IMAGE

FIXTURE = Path("fixtures/workload-claims")
JAVA_IMAGE = "eclipse-temurin:21-jdk"

MUTATIONS = {
    "original": (),
    "pass-label": (("APPROVED", "ELIGIBLE"),),
    "threshold": (("< 500", "< 1000"),),
    "input-fields": (("WS-CR-AMOUNT-STR", "INPUT-VALUE"),
                     ("WS-CR-STATUS", "INPUT-STATE"),
                     ("WS-CLAIM-AMOUNT", "WORK-VALUE")),
    "result-field": (("WS-SETTLEMENT-STATUS", "DECISION-TEXT"),),
}


def _source(name: str) -> str:
    source = (FIXTURE / "cobol" / "CLAIMS.cob").read_text(encoding="utf-8")
    for old, new in MUTATIONS[name]:
        assert old in source, old
        source = source.replace(old, new)
    return source


def _run(root: Path, image: str, command: str, files: dict[str, str]):
    (root / "src").mkdir(parents=True)
    shutil.copytree(FIXTURE / "input", root / "input")
    (root / "output").mkdir()
    for name, text in files.items():
        (root / "src" / name).write_text(text, encoding="utf-8", newline="\n")
    for path in (root, root / "src", root / "input", root / "output"):
        os.chmod(path, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none",
         "-v", f"{root / 'src'}:/src",
         "-v", f"{root / 'input'}:/workspace/input",
         "-v", f"{root / 'output'}:/workspace/output",
         image, "sh", "-c", command],
        capture_output=True, timeout=600,
    )
    outputs = {p.name: p.read_bytes() for p in sorted((root / "output").iterdir())}
    return run.returncode, run.stdout, run.stderr, outputs


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_generated_java_matches_the_oracle(tmp_path, mutation):
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 to run it")
    source = _source(mutation)
    result = TransformationProducer().transform(source, "CLAIMS")
    assert result.success is True, result.errors
    java = {g.filename: g.source_code for g in result.generated_files}
    main = result.generated_files[0].class_name

    oracle = _run(tmp_path / "cobol", ORACLE_IMAGE,
                  "cd /tmp && cobc -x /src/CLAIMS.cob -o p && ./p",
                  {"CLAIMS.cob": source})
    generated = _run(tmp_path / "java", JAVA_IMAGE,
                     "mkdir -p /tmp/c && javac -nowarn -encoding UTF-8 -d /tmp/c /src/*.java"
                     f" && java -cp /tmp/c {main}", java)

    assert oracle[0] == 0, oracle[2].decode(errors="replace")
    assert generated[0] == oracle[0], generated[2].decode(errors="replace")
    assert generated[1] == oracle[1]
    assert generated[2] == oracle[2]
    assert sorted(oracle[3]) == ["report.txt", "settlement.dat"]
    assert generated[3] == oracle[3]


def test_mutations_change_the_behaviour():
    """The mutations are not no-ops: each changes the generated Java."""
    sources = {name: _source(name) for name in MUTATIONS}
    java = {
        name: "".join(g.source_code for g in TransformationProducer().transform(src, "CLAIMS").generated_files)
        for name, src in sources.items()
    }
    assert "< 1000" in java["threshold"] and "< 1000" not in java["original"]
    assert '"ELIGIBLE"' in java["pass-label"] and '"ELIGIBLE"' not in java["original"]
    assert "INPUT_VALUE" in java["input-fields"]
    assert "DECISION_TEXT" in java["result-field"]
    assert '"/workspace/input/claims.dat"' in java["original"]
    assert '"/workspace/output/settlement.dat"' in java["original"]
