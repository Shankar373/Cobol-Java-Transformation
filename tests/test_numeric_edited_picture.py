"""Numeric-edited PIC: grammar, parser, validator and generated Java (hermetic).

The behaviour itself is pinned against GnuCOBOL by
``tests/integration/test_numeric_edited_oracle.py`` (Docker lane) and, on
every run, by ``tests/data/numeric_edited_oracle_truth.json``: 870 results
recorded from the oracle, replayed here through the real ``CobolEdit`` Java
class when a JDK is available.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParseError, CobolParser
from engine.transformation.edit_support_template import COBOL_EDIT_JAVA
from engine.transformation.numeric_edited import (
    UnsupportedEditedPicture,
    expand_picture,
    parse_numeric_edited,
)
from engine.transformation.producer import TransformationProducer
from tests.numeric_edited_fuzz import random_picture

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "data" / "numeric_edited_oracle_truth.json"


# ---------------------------------------------------------------------------
# Picture grammar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "picture,width,floating,trailing",
    [
        ("ZZ,ZZ9.99", 9, "", ""),
        ("Z(5)9.99", 9, "", ""),
        ("$$$9.99-", 8, "$", "-"),
        ("---,--9.99", 10, "-", ""),
        ("+++9", 4, "+", ""),
        ("$ZZ,ZZ9.99", 10, "", ""),
        ("***,**9.99CR", 12, "", "CR"),
        ("99B99", 5, "", ""),
        ("99/99/9999", 10, "", ""),
        ("ZZ9V99", 5, "", ""),
        ("999.99DB", 8, "", "DB"),
    ],
)
def test_certified_pictures(picture, width, floating, trailing):
    edited = parse_numeric_edited(picture)
    assert edited is not None
    assert (edited.width, edited.floating, edited.trailing) == (width, floating, trailing)


@pytest.mark.parametrize("picture", ["9(5)V99", "S9(3)", "9", "S9(5)V99", "X(10)", "XXBXX", "A(4)"])
def test_not_numeric_edited(picture):
    assert parse_numeric_edited(picture) is None


@pytest.mark.parametrize(
    "picture",
    [
        "+++9-", "-ZZ9.99CR",      # leading and trailing sign
        "-$$$9", "+$$$9.99", "$+++9.99",  # sign with currency: erratic on the oracle
        "$$ZZ9",                    # Z after a floating string (illegal)
        "ZZ9.ZZ", "ZZ9.99.99",      # fraction rules
        "9,", ",99", "$$,",         # misplaced insertion characters
        "S9.99", "ZZ9P",            # S / P with editing
        ".99", "$$$,$$$.99",        # no integer digit position
        "0099", "BBZ9",             # leading insertion characters
        "ZZZ" + "Z" * 70,           # size cap
    ],
)
def test_refused_pictures_have_a_reason(picture):
    with pytest.raises(UnsupportedEditedPicture) as info:
        parse_numeric_edited(picture)
    assert str(info.value)


def test_every_fuzz_generated_picture_is_accepted():
    """The grammar covers exactly what the oracle fuzz validates."""
    rng = random.Random(2026)
    refused = []
    for _ in range(4000):
        picture = random_picture(rng)
        if re.fullmatch(r"9+(V9+)?", picture):
            continue  # plain numeric, not edited
        try:
            assert parse_numeric_edited(picture) is not None
        except UnsupportedEditedPicture as exc:
            refused.append((picture, str(exc)))
    assert refused == []


def test_expand_picture():
    assert expand_picture("Z(3)9.9(2)") == "ZZZ9.99"


# ---------------------------------------------------------------------------
# Parser and validator
# ---------------------------------------------------------------------------

_HEAD = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 N PIC S9(5)V99.
       01 E1 PIC ZZ,ZZ9.99.
       01 E2 PIC ZZ9 BLANK WHEN ZERO.
       01 X PIC X(9).
       01 M PIC 9(5).
       PROCEDURE DIVISION.
"""


def _parse(body: str, head: str = _HEAD):
    parser = CobolParser()
    program = parser.parse(head + body + "           STOP RUN.\n")
    return program, [d.message for d in parser.diagnostics.all]


def test_items_are_edited_text_fields():
    program, diagnostics = _parse("           MOVE N TO E1\n")
    items = {i.name: i for i in program.working_storage}
    assert (items["E1"].edit_pic, items["E1"].pic_length, items["E1"].is_alphanumeric) == (
        "ZZ,ZZ9.99", 9, True)
    assert items["E2"].blank_when_zero is True
    assert items["N"].edit_pic is None
    assert not [d for d in diagnostics if "edited" in d]


@pytest.mark.parametrize(
    "body",
    [
        "           MOVE N TO E1\n           MOVE 12.5 TO E1\n           MOVE -3 TO E1\n"
        "           MOVE ZERO TO E1\n           DISPLAY E1 '|' E2\n           MOVE E1 TO X\n",
        "           STRING 'T=' DELIMITED BY SIZE E1 DELIMITED BY SIZE INTO X\n",
        "           MOVE M TO E2\n",
    ],
)
def test_certified_uses_have_no_edited_diagnostics(body):
    _, diagnostics = _parse(body)
    assert [d for d in diagnostics if "numeric-edited" in d] == []


@pytest.mark.parametrize(
    "body,reason",
    [
        ("           ADD 1 TO E1\n", "ADD writing it"),
        ("           COMPUTE E1 = N * 2\n", "COMPUTE writing it"),
        ("           MOVE X TO E1\n", "MOVE of text"),
        ("           MOVE 'ABC' TO E1\n", "MOVE of text"),
        ("           ACCEPT E1\n", "ACCEPT writing it"),
        ("           MOVE E1 TO M\n", "de-editing"),
        ("           MOVE E1 TO E2\n", "de-editing"),
        ("           IF E1 = 5\n               DISPLAY 'Y'\n           END-IF\n", "use in IF"),
        ("           ADD E1 TO M\n", "use in ADD"),
        ("           INITIALIZE E1\n", "writing it"),
    ],
)
def test_other_uses_are_refused(body, reason):
    _, diagnostics = _parse(body)
    hits = [d for d in diagnostics if "numeric-edited item" in d]
    assert hits, diagnostics
    assert any(reason in d for d in hits), hits


def test_initialize_of_a_group_holding_an_edited_item_is_refused():
    head = _HEAD.replace(
        "       01 X PIC X(9).\n",
        "       01 X PIC X(9).\n       01 G.\n          05 G-E PIC ZZ9.\n          05 G-N PIC 9(3).\n",
    )
    _, diagnostics = _parse("           INITIALIZE G\n", head)
    assert any("INITIALIZE" in d for d in diagnostics)


@pytest.mark.parametrize(
    "line",
    [
        "       01 E3 PIC ZZ9 VALUE 5.",
        "       01 E3 PIC ZZ9 OCCURS 3 TIMES.",
        "       01 E3 PIC ZZ9 USAGE DISPLAY COMP.",
    ],
)
def test_clauses_without_a_certified_lowering_are_refused(line):
    head = _HEAD.replace("       01 X PIC X(9).\n", "       01 X PIC X(9).\n" + line + "\n")
    _, diagnostics = _parse("           MOVE N TO E1\n", head)
    assert any("has no certified lowering" in d and "E3" in d for d in diagnostics)


def test_blank_when_zero_with_asterisk_is_not_certified():
    head = _HEAD.replace("       01 X PIC X(9).\n", "       01 X PIC X(9).\n       01 E3 PIC **9 BLANK WHEN ZERO.\n")
    _, diagnostics = _parse("           MOVE N TO E1\n", head)
    assert any("BLANK WHEN ZERO" in d for d in diagnostics)


def test_picture_outside_the_subset_fails_the_parse():
    head = _HEAD.replace("       01 X PIC X(9).\n", "       01 X PIC X(9).\n       01 E3 PIC $$ZZ9.\n")
    with pytest.raises(CobolParseError, match="numeric-edited PIC"):
        CobolParser().parse(head + "           STOP RUN.\n")


# ---------------------------------------------------------------------------
# Generated Java
# ---------------------------------------------------------------------------

_PROGRAM = _HEAD + (
    "           MOVE N TO E1\n"
    "           MOVE 7 TO E2\n"
    "           DISPLAY E1 '|' E2\n"
    "           STOP RUN.\n"
)


def test_plain_java_calls_the_helper_and_ships_it():
    result = TransformationProducer().transform(_PROGRAM, "T")
    assert result.success is True, result.errors
    source = result.generated_files[0].source_code
    assert 'static String E1 = CobolEdit.edit(new java.math.BigDecimal("0"), 0, "ZZ,ZZ9.99", false);' in source
    assert 'static String E2 = CobolEdit.edit(new java.math.BigDecimal("0"), 0, "ZZ9", true);' in source
    assert 'E1 = CobolEdit.edit(' in source and "N" in source
    assert "final class CobolEdit {" in source


def test_program_without_edited_items_does_not_ship_the_helper():
    plain = _HEAD.replace("       01 E1 PIC ZZ,ZZ9.99.\n", "").replace(
        "       01 E2 PIC ZZ9 BLANK WHEN ZERO.\n", "")
    result = TransformationProducer().transform(plain + "           DISPLAY N\n           STOP RUN.\n", "T")
    assert result.success is True, result.errors
    assert "CobolEdit" not in result.generated_files[0].source_code


@pytest.mark.parametrize("target", ["spring_boot", "plain_java", "quarkus", "micronaut"])
def test_every_runtime_ships_the_helper(tmp_path, target):
    from tests.test_framework_runtimes import _generate

    _, project, _ = _generate(tmp_path, target, source=_PROGRAM, program="T")
    # Spring Boot ships a separate CobolEdit.java; the other runtimes embed
    # the helper in the program file. Either way: exactly one definition.
    definitions = [
        path for path in Path(project).rglob("*.java")
        if "final class CobolEdit {" in path.read_text(encoding="utf-8")
    ]
    assert len(definitions) == 1, definitions


def test_refused_program_is_not_generated():
    bad = _HEAD + "           ADD 1 TO E1\n           STOP RUN.\n"
    result = TransformationProducer().transform(bad, "T")
    assert result.success is False


# ---------------------------------------------------------------------------
# The Java helper against recorded oracle results
# ---------------------------------------------------------------------------

def test_java_helper_reproduces_the_recorded_oracle_results(tmp_path):
    if not (shutil.which("javac") and shutil.which("java")):
        pytest.skip("javac/java not on PATH")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = golden["cases"]
    (tmp_path / "CobolEdit.java").write_text(COBOL_EDIT_JAVA, encoding="utf-8")
    (tmp_path / "Drv.java").write_text(
        "import java.math.BigDecimal; import java.nio.file.*;\n"
        "public class Drv { public static void main(String[] a) throws Exception {\n"
        "  for (String line : Files.readAllLines(Paths.get(a[0]))) {\n"
        "    String[] p = line.split(\"\\t\", -1);\n"
        "    System.out.println(CobolEdit.edit(new BigDecimal(p[1]), Integer.parseInt(p[2]), p[0], false));\n"
        "  } } }\n",
        encoding="utf-8",
    )
    (tmp_path / "cases.tsv").write_text(
        "\n".join(f"{pic}\t{value}\t{golden['sender_scale']}" for pic, value, _ in cases) + "\n",
        encoding="utf-8", newline="\n",
    )
    compiled = subprocess.run(
        ["javac", "-nowarn", "-d", str(tmp_path), str(tmp_path / "CobolEdit.java"), str(tmp_path / "Drv.java")],
        capture_output=True, timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    run = subprocess.run(
        ["java", "-Dline.separator=\n", "-cp", str(tmp_path), "Drv", str(tmp_path / "cases.tsv")],
        capture_output=True, timeout=120,
    )
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    got = run.stdout.decode("utf-8").split("\n")[: len(cases)]
    wrong = [(c[0], c[1], c[2], g) for c, g in zip(cases, got) if c[2] != g]
    assert wrong == [], wrong[:5]
    assert len(cases) >= 800
