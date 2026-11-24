"""Layer 11: the oracle is handed the entry the Layer 8 plan (and so the generated Java) enters.

``Service._resolve_entry_program`` feeds ``oracle_entry_program``; it must apply the same rule as ``engine.transformation.entrypoint``.  A self-CALL
(recursion) once made the service see its own program as called, so it resolved nothing while the plan resolved that program, and the oracle fell back to
its ``main.cob`` convention and ran another program than the Java did.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.service import Service
from engine.oracle.docker_adapter import DockerOracleAdapter
from engine.transformation.entrypoint import resolve_entrypoint

HEADER = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. {pid}.\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n{body}           GOBACK.\n"


def _program(pid: str, *calls: str) -> str:
    return HEADER.format(pid=pid, body="".join(f"           CALL '{c}'.\n" for c in calls))


ESTATES = {
    "self-call-root": {"driver.cob": _program("DRIVER", "DRIVER", "SUB"), "main.cob": _program("SUB")},
    "plain-root": {"driver.cob": _program("DRIVER", "SUB"), "main.cob": _program("SUB")},
    "single": {"only.cob": _program("ONLY", "ONLY")},
    "two-roots": {"a.cob": _program("A"), "b.cob": _program("B")},
    "cycle": {"a.cob": _program("A", "B"), "b.cob": _program("B", "A")},
}


def _service_entry(directory) -> str:
    app = SimpleNamespace(java_entrypoint="Main", cobol_source_path=str(directory), id="x")
    return Service._resolve_entry_program(Service.__new__(Service), app, str(directory))


@pytest.mark.parametrize("estate", sorted(ESTATES))
def test_the_service_entry_agrees_with_the_shared_rule(tmp_path, estate):
    for name, text in ESTATES[estate].items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    ids = [text.split("PROGRAM-ID. ")[1].split(".")[0] for text in ESTATES[estate].values()]
    edges = [(pid, target) for pid, text in zip(ids, ESTATES[estate].values(), strict=True)
             for target in [line.split("'")[1] for line in text.splitlines() if "CALL '" in line]]
    expected, _reason = resolve_entrypoint(ids, "", edges)
    served = _service_entry(tmp_path)
    assert served == expected  # "" (a refusal) on both sides, or the same program


def test_the_oracle_given_that_entry_runs_the_program_the_plan_names(tmp_path):
    for name, text in ESTATES["self-call-root"].items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    entry = _service_entry(tmp_path)
    assert entry == "DRIVER"
    assert DockerOracleAdapter.select_modules(tmp_path, entry)[0] == "driver.cob"
