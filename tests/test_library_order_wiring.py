"""Layer 4 library order: per-program orders reach the engine and agree with discovery.

Discovery derives, per program, the JCLLIB/SYSLIB/-I order that decides a same-named copybook
(``enterprise.discovery.resolve.program_library_orders``).  The engine consumes that order as plain data
(``ApplicationGenerator.generate(orders={PROGRAM: orders})``), so each program resolves ITS copybook.
These tests pin: the derivation, the per-program engine result, engine == discovery on the same fixture,
fail-closed behaviour, and that removing the wiring changes the result.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.copybook_resolver import (
    _candidate_files,
    copybook_search_dirs,
    resolve_application_copybooks,
)
from enterprise.discovery.library_order import library_match, library_winner
from enterprise.discovery.resolve import build_graph, program_library_orders
from tests.discovery.helpers import _fixed, write_tree
from tests.discovery.test_resolve_graph import records

LIB1 = _fixed("01 RATE-REC.", "    05 RATE-X PIC 9(3) VALUE 123.")
LIB2 = _fixed("01 RATE-REC.", "    05 RATE-X PIC X(5) VALUE 'ABCDE'.")


def _program(name: str) -> str:
    return _fixed(
        "IDENTIFICATION DIVISION.", f"PROGRAM-ID. {name}.", "DATA DIVISION.", "WORKING-STORAGE SECTION.",
        "    COPY RATES.", "PROCEDURE DIVISION.", "MAIN-PARA.", "    DISPLAY RATE-X.", "    STOP RUN.")


def _jcl(job: str, program: str, order: tuple[str, ...]) -> str:
    return f"//{job} JOB\n//  JCLLIB ORDER=({','.join(order)})\n//S1 EXEC PGM={program}\n"


def _estate(**orders: tuple[str, ...]) -> dict[str, str]:
    files = {"libs/lib1/RATES.cpy": LIB1, "libs/lib2/RATES.cpy": LIB2}
    for program, order in orders.items():
        files[f"src/{program}.cbl"] = _program(program)
        files[f"jcl/J{program}.jcl"] = _jcl(f"J{program}", program, order)
    return files


L12, L21 = ("LIBS.LIB1", "LIBS.LIB2"), ("LIBS.LIB2", "LIBS.LIB1")


def _generate(root: Path, orders=()):
    app = ApplicationDiscovery().discover(str(root), application_id="orders")
    return ApplicationGenerator().generate(app, entrypoint="A", source_root=root, orders=orders)


def _java_of(result, program: str) -> str:
    return "\n".join(f.source_code for f in result.generated_files if f.class_name.lower().startswith(program.lower()))


def _all_java(result) -> str:
    return "\n".join(f.source_code for f in result.generated_files)


# --- discovery derivation -------------------------------------------------------------------------------------


def test_program_library_orders_is_per_program_and_deterministic() -> None:
    build = build_graph(records(_estate(A=L12, B=L21)))
    expected = {"A": (L12,), "B": (L21,)}
    assert program_library_orders(build) == expected
    reordered = dict(reversed(list(_estate(A=L12, B=L21).items())))
    assert program_library_orders(build_graph(records(reordered))) == expected


def test_program_without_build_facts_has_no_orders() -> None:
    files = {"libs/lib1/RATES.cpy": LIB1, "src/A.cbl": _program("A")}
    assert program_library_orders(build_graph(records(files))) == {}


def test_discovery_copybook_resolution_uses_the_same_derivation() -> None:
    """The graph's own COPY decision and ``program_library_orders`` + ``library_winner`` pick the same file."""
    for order, suffix in ((L12, "libs/lib1/RATES.cpy"), (L21, "libs/lib2/RATES.cpy")):
        build = build_graph(records(_estate(A=order)))
        node = build.graph.nodes["copybook:RATES"]
        assert node.path == suffix
        winner = library_winner(["libs/lib1/RATES.cpy", "libs/lib2/RATES.cpy"], program_library_orders(build)["A"])
        assert winner == node.path


# --- engine consumes them -------------------------------------------------------------------------------------


def test_each_program_resolves_its_own_copybook_through_the_generator(tmp_path: Path) -> None:
    files = _estate(A=L12, B=L21)
    root = write_tree(tmp_path / "estate", files)
    orders = program_library_orders(build_graph(records(files)))

    result = _generate(root, orders)
    assert result.success, result.errors
    java_a, java_b = _java_of(result, "A"), _java_of(result, "B")
    assert java_a and java_b and java_a != java_b
    # A concatenates LIB1 first (numeric 123), B LIB2 first (alphanumeric ABCDE)
    assert "123" in java_a and "ABCDE" not in java_a
    assert "ABCDE" in java_b and "123" not in java_b


def test_engine_pick_equals_discovery_pick_per_program(tmp_path: Path) -> None:
    files = _estate(A=L12, B=L21)
    root = write_tree(tmp_path / "estate", files)
    build = build_graph(records(files))
    orders = program_library_orders(build)
    candidates = [c.as_posix() for c in _candidate_files(tuple(copybook_search_dirs(root)), "RATES")]
    resolved, missing = resolve_application_copybooks(
        (("A", "RATES"), ("B", "RATES")), tuple(copybook_search_dirs(root)), orders=orders)
    assert not missing
    picked = {r.program_id: r.path.as_posix() for r in resolved}
    for program in ("A", "B"):
        authority = library_winner(candidates, orders[program])
        assert authority and picked[program] == authority
    assert picked["A"].endswith("libs/lib1/RATES.cpy") and picked["B"].endswith("libs/lib2/RATES.cpy")


def test_single_program_engine_layout_equals_the_discovery_graph_node(tmp_path: Path) -> None:
    for order in (L12, L21):
        files = _estate(A=order)
        root = write_tree(tmp_path / f"estate-{order[0][-1]}", files)
        build = build_graph(records(files))
        result = _generate(root, program_library_orders(build))
        assert result.success, result.errors
        node_path = build.graph.nodes["copybook:RATES"].path
        marker = "123" if node_path.endswith("lib1/RATES.cpy") else "ABCDE"
        assert marker in _all_java(result)


def test_removing_the_wiring_changes_the_result(tmp_path: Path) -> None:
    """Mutation check: with ``orders={}`` the same estate is ambiguous and generation fails closed."""
    files = _estate(A=L12, B=L21)
    root = write_tree(tmp_path / "estate", files)
    wired = _generate(root, program_library_orders(build_graph(records(files))))
    unwired = _generate(root, {})
    assert wired.success
    assert not unwired.success
    assert any("RATES" in message for message in unwired.errors)
    assert _all_java(wired) != _all_java(unwired)


def test_tuple_form_still_applies_to_every_program(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "estate", _estate(A=L12, B=L12))
    result = _generate(root, [list(L21)])
    assert result.success, result.errors
    assert "ABCDE" in _java_of(result, "A") and "ABCDE" in _java_of(result, "B")


def test_disagreement_or_missing_program_entry_fails_closed(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "estate", _estate(A=L12, B=L21))
    # B has no entry: only A is decided, B stays ambiguous (never silently picked)
    partial = _generate(root, {"A": (L12,)})
    assert not partial.success and any("RATES" in m for m in partial.errors)
    # contradictory orders for one program never decide
    contradictory = _generate(root, {"A": (L12, L21), "B": (L21,)})
    assert not contradictory.success
    assert library_winner(["libs/lib1/RATES.cpy", "libs/lib2/RATES.cpy"], [L12, L21]) == ""


# --- dataset-name mapping -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "library", "expected"),
    [
        ("prod/copylib/A.cpy", "PROD.COPYLIB", 2),
        ("estate/prod/copylib/A.cpy", "prod.copylib", 2),
        ("test/copylib/A.cpy", "PROD.COPYLIB", 1),
        ("xprod/copylib/A.cpy", "PROD.COPYLIB", 1),
        ("prod/other/A.cpy", "PROD.COPYLIB", 0),
        ("prod/copylib/A.cpy", "PROD.COPYLIB(RATES)", 2),
        ("libs/lib1/A.cpy", "./libs/lib1", 2),
    ],
)
def test_library_match_strength(path: str, library: str, expected: int) -> None:
    assert library_match(path, library) == expected


def test_real_dsn_maps_to_its_directory_and_never_claims_a_sibling_library() -> None:
    candidates = ["prod/copylib/RATES.cpy", "test/copylib/RATES.cpy"]
    assert library_winner(candidates, [["PROD.COPYLIB", "TEST.COPYLIB"]]) == "prod/copylib/RATES.cpy"
    assert library_winner(candidates, [["TEST.COPYLIB", "PROD.COPYLIB"]]) == "test/copylib/RATES.cpy"
    # two directories that only share the last qualifier: undecided, never a guess
    assert library_winner(["a/copylib/R.cpy", "b/copylib/R.cpy"], [["SYS1.COPYLIB"]]) == ""


def test_digest_of_generation_is_stable_for_equal_orders(tmp_path: Path) -> None:
    files = _estate(A=L12, B=L21)
    root = write_tree(tmp_path / "estate", files)
    orders = program_library_orders(build_graph(records(files)))
    digests = {hashlib.sha256(_all_java(_generate(root, orders)).encode()).hexdigest() for _ in range(2)}
    assert len(digests) == 1
