"""Library-order parity: one authority, two faces (layer 4, acceptance criterion 9).

Discovery records what an estate contains; generation materialises what a
program copies in.  Criterion 9 requires that same-named copybooks resolve
in JCLLIB/SYSLIB order, that the loser is listed in ``candidates``, and that
engine and discovery pick the same file.

The structural reason the two faces cannot drift: both call the single
authority :func:`enterprise.discovery.library_order.library_winner`.  This
fixture proves the agreement over both order directions and the refusal to
decide when no order applies, rather than trusting the wiring by
documentation.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.copybook_resolver import (
    copybook_search_dirs,
    resolve_copybook,
)
from engine.transformation.copybook_resolver import _candidate_files
from enterprise.discovery.library_order import in_library, library_winner


def test_in_library_recognises_dataset_and_directory_forms() -> None:
    assert in_library("libs/lib1/RATES.cpy", "LIBS.LIB1")
    assert in_library("libs/lib1/RATES.cpy", "libs/lib1")
    assert not in_library("libs/lib1/RATES.cpy", "LIBS.LIB2")


def test_library_winner_prefers_the_first_library_in_order() -> None:
    candidates = ["libs/lib1/RATES.cpy", "libs/lib2/RATES.cpy"]
    assert library_winner(candidates, [["LIBS.LIB2", "LIBS.LIB1"]]).endswith("libs/lib2/RATES.cpy")
    assert library_winner(candidates, [["LIBS.LIB1", "LIBS.LIB2"]]).endswith("libs/lib1/RATES.cpy")


def test_library_winner_refuses_to_decide_without_an_order() -> None:
    candidates = ["libs/lib1/RATES.cpy", "libs/lib2/RATES.cpy"]
    assert library_winner(candidates, []) == ""


def test_engine_and_authority_agree_on_the_winner(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "libs" / "lib1").mkdir(parents=True)
    (root / "libs" / "lib2").mkdir(parents=True)
    (root / "libs" / "lib1" / "RATES.cpy").write_text("       01 R PIC X.\n", encoding="utf-8")
    (root / "libs" / "lib2" / "RATES.cpy").write_text("       01 R PIC X.\n", encoding="utf-8")

    dirs = copybook_search_dirs(root)
    candidates = _candidate_files(tuple(dirs), "RATES")
    posix_candidates = [str(c).replace("\\", "/") for c in candidates]

    for first, second, expected_suffix in (
        ("LIB2", "LIB1", "libs/lib2/RATES.cpy"),
        ("LIB1", "LIB2", "libs/lib1/RATES.cpy"),
    ):
        orders = [[f"LIBS.{first}", f"LIBS.{second}"]]
        authority_winner = library_winner(posix_candidates, orders)
        assert authority_winner.endswith(expected_suffix), (authority_winner, expected_suffix)
        resolved = resolve_copybook("RATES", dirs, orders=orders)
        assert str(resolved.path).replace("\\", "/").endswith(expected_suffix), (resolved.path, expected_suffix)
        assert str(resolved.path).replace("\\", "/") == authority_winner, (resolved.path, authority_winner)


def test_engine_falls_back_to_ambiguous_without_an_order(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "libs" / "lib1").mkdir(parents=True)
    (root / "libs" / "lib2").mkdir(parents=True)
    (root / "libs" / "lib1" / "RATES.cpy").write_text("       01 R PIC X.\n", encoding="utf-8")
    (root / "libs" / "lib2" / "RATES.cpy").write_text("       01 R PIC X.\n", encoding="utf-8")

    dirs = copybook_search_dirs(root)
    raised = False
    try:
        resolve_copybook("RATES", dirs)
    except Exception as exc:
        raised = True
        assert "RATES" in str(exc)
    assert raised, "without an order the ambiguous pick must stay an error"
