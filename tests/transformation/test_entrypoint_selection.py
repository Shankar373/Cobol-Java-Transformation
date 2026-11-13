"""G-15: the application entrypoint is never guessed.

Before, ``ApplicationGenerator._resolve_entrypoint`` returned the first
generated program class whenever the requested entrypoint did not match,
or none was requested.  File order, class order and name order are not
semantics.  The contract locked here:

* a requested entrypoint must match exactly one generated program class;
* with none requested, the entrypoint is the only program, or the only
  program no other program CALLs; several roots (or none) is refused with
  a diagnostic naming the candidates;
* ``ServiceRegistry`` and copybook model classes are never entrypoints,
  even when explicitly requested;
* ``generate()`` fails (success False, no entrypoint) instead of picking.

Dependency-free on purpose (pytest only), like the other capability-gate
tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.java_generator import GeneratedFile

select = ApplicationGenerator._select_entrypoint


def _files(*classes: str) -> tuple[GeneratedFile, ...]:
    return tuple(
        GeneratedFile(filename=f"{c}.java", source_code="", class_name=c) for c in classes
    )


# --- selection rules --------------------------------------------------------

def test_requested_entrypoint_must_match_exactly():
    assert select(_files("Alpha", "Beta"), "Beta") == ("Beta", "")


def test_requested_entrypoint_is_compared_case_dash_underscore_insensitively():
    assert select(_files("Alpha1", "Beta"), "ALPHA-1")[0] == "Alpha1"
    assert select(_files("Alpha1", "Beta"), "alpha_1")[0] == "Alpha1"


def test_requested_entrypoint_that_matches_nothing_is_refused_not_replaced():
    entry, error = select(_files("Alpha", "Beta"), "Gamma")
    assert entry == ""
    assert "Gamma" in error and "Alpha" in error and "Beta" in error


def test_requested_entrypoint_matching_several_programs_is_ambiguous():
    entry, error = select(_files("Calc", "Calc", "Main"), "calc")
    assert entry == "" and "ambiguous" in error


def test_requested_helper_or_model_class_is_never_an_entrypoint():
    files = _files("ServiceRegistry", "CustomerRecord", "Main")
    assert select(files, "ServiceRegistry", exclude={"CustomerRecord"})[0] == ""
    assert select(files, "CustomerRecord", exclude={"CustomerRecord"})[0] == ""


def test_only_helpers_and_models_leaves_no_entrypoint():
    entry, error = select(_files("ServiceRegistry", "CustomerRecord"), "", exclude={"CustomerRecord"})
    assert entry == "" and error


def test_single_program_is_the_entrypoint_without_a_request():
    assert select(_files("ServiceRegistry", "Only"), "") == ("Only", "")


def test_single_call_root_is_derived_from_the_call_graph():
    files = _files("Zeta", "Alpha", "Mid")
    edges = (("Zeta", "Mid"), ("Mid", "Alpha"))
    # file order puts Zeta first, lexical order puts Alpha first; the graph says Zeta
    assert select(files, "", call_edges=edges) == ("Zeta", "")
    assert select(tuple(reversed(files)), "", call_edges=edges) == ("Zeta", "")


def test_several_roots_without_a_request_is_refused_and_names_them():
    entry, error = select(_files("Beta", "Alpha"), "", call_edges=())
    assert entry == ""
    assert "ambiguous" in error and "Alpha" in error and "Beta" in error


def test_a_call_cycle_has_no_root_and_is_refused():
    entry, error = select(_files("A", "B"), "", call_edges=(("A", "B"), ("B", "A")))
    assert entry == "" and "every program is the target of a CALL" in error


def test_result_never_depends_on_class_order():
    forward = select(_files("Beta", "Alpha"), "", call_edges=())
    backward = select(_files("Alpha", "Beta"), "", call_edges=())
    assert forward[0] == backward[0] == ""


# --- through generate() on real discovered sources --------------------------

def _program(pid: str, body: str = "    DISPLAY 'X'.\n") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {pid}.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        f"       {body}"
        "           STOP RUN.\n"
    )


def _generate(tmp_path: Path, programs: dict[str, str], entrypoint: str):
    for name, text in programs.items():
        (tmp_path / f"{name.lower()}.cob").write_text(text, encoding="utf-8")
    app = ApplicationDiscovery().discover(tmp_path)
    return ApplicationGenerator().generate(app, entrypoint=entrypoint, source_root=tmp_path)


def test_generate_two_independent_programs_without_request_is_refused(tmp_path):
    result = _generate(tmp_path, {"first": _program("FIRST"), "second": _program("SECOND")}, "")
    assert result.success is False and result.entrypoint == ""
    assert any("ambiguous" in e and "First" in e and "Second" in e for e in result.errors)


def test_generate_unknown_requested_entrypoint_is_refused(tmp_path):
    result = _generate(tmp_path, {"first": _program("FIRST")}, "NOPE")
    assert result.success is False
    assert any("NOPE" in e for e in result.errors)


def test_generate_requested_entrypoint_among_several_is_honoured(tmp_path):
    result = _generate(tmp_path, {"first": _program("FIRST"), "second": _program("SECOND")}, "SECOND")
    assert result.success is True and result.entrypoint.upper() == "SECOND"


def test_generate_single_program_needs_no_request(tmp_path):
    result = _generate(tmp_path, {"only": _program("ONLY")}, "")
    assert result.success is True and result.entrypoint.upper() == "ONLY"


def test_generate_derives_the_root_of_a_call_chain(tmp_path):
    caller = _program("ZMAIN", "    CALL 'ALEAF'.\n")
    result = _generate(tmp_path, {"zmain": caller, "aleaf": _program("ALEAF")}, "")
    assert result.success is True and result.entrypoint.upper() == "ZMAIN"


@pytest.mark.parametrize("requested", ["", "Main"])
def test_placeholder_does_not_rescue_an_ambiguous_application(tmp_path, requested):
    result = _generate(tmp_path, {"first": _program("FIRST"), "second": _program("SECOND")}, requested)
    assert result.success is False and result.entrypoint == ""


def test_a_self_calling_program_is_still_a_root():
    files = _files("Zeta", "Alpha")
    # Alpha calls itself (recursion) and nothing else calls Alpha; Zeta calls Alpha.
    # Alpha is called by Zeta, so Zeta is the single root even with the self edge.
    assert select(files, "", call_edges=(("Alpha", "Alpha"), ("Zeta", "Alpha"))) == ("Zeta", "")
    # Only a self edge: both programs are uncalled roots, so this stays ambiguous (never guessed).
    entry, error = select(files, "", call_edges=(("Alpha", "Alpha"),))
    assert entry == "" and "ambiguous" in error
    # A lone recursive root with a callee: the recursion must not hide it.
    assert select(_files("Main", "Leaf"), "", call_edges=(("Main", "Main"), ("Main", "Leaf"))) == ("Main", "")
