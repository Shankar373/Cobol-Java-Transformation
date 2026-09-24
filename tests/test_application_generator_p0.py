"""P0 regression tests — program/file-level COBOL -> Java transformation.

Proves the application-level transformation boundary:

    COBOL APPLICATION
    -> discover individual COBOL PROGRAMS (ApplicationDiscovery)
    -> transform each program independently (ApplicationGenerator)
    -> one Java artifact per program
    -> assemble those artifacts into ONE Java application

These tests are Docker-free by construction: they exercise only the
discovery -> mapping -> generation boundary. They never touch the
GnuCOBOL oracle, comparators, verdict derivation, or the API layer.

Regression proofs:
  TEST 1  Two programs -> two independent Java files, no COBOL concatenation.
  TEST 2  Distinct program logic -> distinct Java classes, no cross-bleed.
  TEST 3  Application assembly -> one artifact dir with both program classes.
  TEST 4  Copybooks are dependencies, not executable Java programs.
  TEST 5  Deterministic entrypoint selection (explicit + fallback).
  TEST 6  Empty/invalid application -> controlled failure, never silent.
  TEST 7  No concatenation proof with incompatible PROGRAM-IDs.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import (
    ApplicationGenerationResult,
    ApplicationGenerator,
)
from engine.transformation.ir import CobolApplication, CobolProgramUnit
from engine.transformation.java_generator import GeneratedFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cobol(program_id: str, working_storage: str, body: str) -> str:
    """Build a minimal, parseable COBOL program with a unique marker."""
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {program_id}.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        f"{working_storage}\n"
        "       PROCEDURE DIVISION.\n"
        f"{body}\n"
    )


PROGRAM_A = _cobol(
    "PROGRAM-A",
    "       01 WS-A-TOTAL PIC 9(5) VALUE 0.",
    "       MAIN-A.\n"
    "           MOVE 100 TO WS-A-TOTAL.\n"
    '           DISPLAY "ALPHA-MARKER-111" WS-A-TOTAL.\n'
    "           STOP RUN.",
)

PROGRAM_B = _cobol(
    "PROGRAM-B",
    "       01 WS-B-FLAG PIC X(10) VALUE 'N'.",
    "       MAIN-B.\n"
    "           MOVE 'Y' TO WS-B-FLAG.\n"
    '           DISPLAY "BETA-MARKER-222" WS-B-FLAG.\n'
    "           STOP RUN.",
)

CLAIMS_PROGRAM = _cobol(
    "CLAIM-S",
    "       01 WS-CLAIM-TOTAL PIC 9(5) VALUE 0.",
    "       MAIN-CLAIM.\n"
    "           MOVE 10 TO WS-CLAIM-TOTAL.\n"
    '           DISPLAY "CLAIM-MARKER-333" WS-CLAIM-TOTAL.\n'
    "           STOP RUN.",
)

PAYMENT_PROGRAM = _cobol(
    "PAYMENT",
    "       01 WS-PAY-AMT PIC 9(5) VALUE 0.",
    "       MAIN-PAY.\n"
    "           MOVE 20 TO WS-PAY-AMT.\n"
    '           DISPLAY "PAYMENT-MARKER-444" WS-PAY-AMT.\n'
    "           STOP RUN.",
)

MAIN_WITH_COPY = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAINPROG.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       COPY COMMON.\n"
    "       01 WS-X PIC X(5) VALUE 'X'.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    '           DISPLAY "MAINPROG-MARKER" WS-X.\n'
    "           STOP RUN.\n"
)

COMMON_COPYBOOK = (
    "       01 COMMON-REC PIC X(20).\n"
)


def _discover(tmp_path: Path, files: dict[str, str], app_id: str = "TEST-APP") -> CobolApplication:
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return ApplicationDiscovery().discover(str(tmp_path), application_id=app_id)


def _program_files(result: ApplicationGenerationResult) -> list[GeneratedFile]:
    """Generated files excluding the ServiceRegistry assembly helper."""
    return [f for f in result.generated_files if f.class_name != "ServiceRegistry"]


# ---------------------------------------------------------------------------
# TEST 1 — two programs, independent transformation, no concatenation
# ---------------------------------------------------------------------------

class TestTwoProgramsIndependent:
    def test_discovery_sees_two_programs(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        assert len(app.programs) == 2
        assert {u.program_id for u in app.programs} == {"PROGRAM-A", "PROGRAM-B"}

    def test_generator_emits_two_separate_java_files(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        result = ApplicationGenerator().generate(app)

        assert result.success
        assert result.errors == ()
        program_files = _program_files(result)
        assert len(program_files) == 2
        filenames = {f.filename for f in program_files}
        assert len(filenames) == 2
        assert all(name.endswith(".java") for name in filenames)

    def test_no_combined_cobol_source_created(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        ApplicationGenerator().generate(app)

        # The source tree is untouched: exactly the two input files remain.
        cobol_files = sorted(p.name for p in tmp_path.glob("*.cob"))
        assert cobol_files == ["A.cob", "B.cob"]
        for name in ("A.cob", "B.cob"):
            content = (tmp_path / name).read_text(encoding="utf-8")
            assert "PROGRAM-A" in content or "PROGRAM-B" in content
        # Neither input file contains both programs (no concatenation).
        assert "PROGRAM-B" not in (tmp_path / "A.cob").read_text(encoding="utf-8")
        assert "PROGRAM-A" not in (tmp_path / "B.cob").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TEST 2 — distinct logic produces distinct classes
# ---------------------------------------------------------------------------

class TestDistinctProgramLogic:
    def test_each_program_produces_own_class(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        result = ApplicationGenerator().generate(app)

        assert result.success
        assert set(result.program_ids) == {"PROGRAM-A", "PROGRAM-B"}
        class_names = {f.class_name for f in _program_files(result)}
        assert len(class_names) == 2

    def test_no_cross_program_source_bleed(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        result = ApplicationGenerator().generate(app)

        by_id = {pid: f for pid, f in zip(result.program_ids, _program_files(result))}
        src_a = by_id["PROGRAM-A"].source_code
        src_b = by_id["PROGRAM-B"].source_code

        assert src_a != src_b
        assert "ALPHA-MARKER-111" in src_a
        assert "BETA-MARKER-222" not in src_a
        assert "BETA-MARKER-222" in src_b
        assert "ALPHA-MARKER-111" not in src_b


# ---------------------------------------------------------------------------
# TEST 3 — application assembly into ONE Java application
# ---------------------------------------------------------------------------

class TestApplicationAssembly:
    def test_single_artifact_dir_contains_both_classes(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        result = ApplicationGenerator().generate(app)
        assert result.success

        out_dir = tmp_path / "generated-app"
        ApplicationGenerator.write_to_directory(result, out_dir)

        written = sorted(p.name for p in out_dir.glob("*.java"))
        program_files = _program_files(result)
        for f in program_files:
            assert f.filename in written
        # Assembly helper present for multi-program applications.
        assert "ServiceRegistry.java" in written

    def test_classes_not_merged_into_one_file(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        result = ApplicationGenerator().generate(app)

        for f in _program_files(result):
            # One self-contained program unit per file.
            assert f.source_code.count("public class") == 1

    def test_each_program_keeps_valid_java_entrypoint(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        result = ApplicationGenerator().generate(app)

        for f in _program_files(result):
            assert "public static void main" in f.source_code


# ---------------------------------------------------------------------------
# TEST 4 — copybook handling
# ---------------------------------------------------------------------------

class TestCopybookHandling:
    def test_cpy_file_is_not_a_program(self, tmp_path: Path) -> None:
        app = _discover(
            tmp_path,
            {"MAIN.cob": MAIN_WITH_COPY, "COMMON.cpy": COMMON_COPYBOOK},
        )
        # The .cpy file is not discovered as an executable program.
        assert len(app.programs) == 1
        assert app.programs[0].program_id == "MAINPROG"
        # ... but the COPY dependency is recorded on the application model.
        assert "COMMON" in app.copybooks

    def test_copybook_produces_no_java_program(self, tmp_path: Path) -> None:
        app = _discover(
            tmp_path,
            {"MAIN.cob": MAIN_WITH_COPY, "COMMON.cpy": COMMON_COPYBOOK},
        )
        result = ApplicationGenerator().generate(app, source_root=tmp_path)

        assert result.success
        assert result.program_ids == ("MAINPROG",)
        class_names = [f.class_name for f in result.generated_files]
        # No EXECUTABLE program class for the copybook ...
        assert "Common" not in class_names
        # ... but the shared data model exists and carries no main method.
        assert "CommonRecord" in class_names
        model_file = next(
            f for f in result.generated_files if f.class_name == "CommonRecord"
        )
        assert "static void main" not in model_file.source_code


# ---------------------------------------------------------------------------
# TEST 5 — deterministic entrypoint selection
# ---------------------------------------------------------------------------

class TestEntrypointSelection:
    def test_explicit_entrypoint_selects_requested_program(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"C.cob": CLAIMS_PROGRAM, "P.cob": PAYMENT_PROGRAM})
        gen = ApplicationGenerator()

        assert gen.generate(app, entrypoint="PAYMENT").entrypoint == "Payment"
        assert gen.generate(app, entrypoint="payment").entrypoint == "Payment"
        assert gen.generate(app, entrypoint="CLAIM-S").entrypoint == "Claim_S"

    def test_entrypoint_normalisation_variants(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"C.cob": CLAIMS_PROGRAM, "P.cob": PAYMENT_PROGRAM})
        gen = ApplicationGenerator()

        expected = gen.generate(app, entrypoint="CLAIM-S").entrypoint
        for variant in ("CLAIM-S", "claim-s", "Claim_S", "CLAIMS", "claims"):
            assert gen.generate(app, entrypoint=variant).entrypoint == expected

    def test_fallback_entrypoint_is_deterministic(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"C.cob": CLAIMS_PROGRAM, "P.cob": PAYMENT_PROGRAM})
        gen = ApplicationGenerator()

        first = gen.generate(app).entrypoint
        for _ in range(3):
            assert gen.generate(app).entrypoint == first
        # Fallback resolves to the first discovered program's class.
        assert first == "Claim_S"

    def test_entrypoint_is_never_service_registry(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        result = ApplicationGenerator().generate(app)

        assert result.entrypoint != "ServiceRegistry"
        assert ApplicationGenerator().generate(app, entrypoint="no-such-program").entrypoint != "ServiceRegistry"


# ---------------------------------------------------------------------------
# TEST 6 — empty/invalid application handling
# ---------------------------------------------------------------------------

class TestEmptyInvalidApplication:
    def test_empty_application_fails_controlled(self) -> None:
        empty = CobolApplication(application_id="EMPTY", programs=(), copybooks=(), edges=())
        result = ApplicationGenerator().generate(empty)

        assert not result.success
        assert result.generated_files == ()
        assert len(result.errors) > 0

    def test_unit_without_program_fails_controlled(self) -> None:
        unit = CobolProgramUnit(program_id="GHOST", source_path="ghost.cob", program=None)
        app = CobolApplication(
            application_id="GHOST-APP",
            programs=(unit,),
            copybooks=(),
            edges=(),
        )
        result = ApplicationGenerator().generate(app)

        assert not result.success
        assert result.generated_files == ()
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# TEST 7 — no-concatenation proof with incompatible PROGRAM-IDs
# ---------------------------------------------------------------------------

class TestNoConcatenationProof:
    def test_two_classes_never_one(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        result = ApplicationGenerator().generate(app)

        assert result.success
        program_files = _program_files(result)
        assert len(program_files) == 2

        combined = "\n".join(f.source_code for f in program_files)
        # Each marker appears exactly once across the whole output.
        assert combined.count("ALPHA-MARKER-111") == 1
        assert combined.count("BETA-MARKER-222") == 1

        # No single generated class represents both programs.
        for f in program_files:
            assert not ("ALPHA-MARKER-111" in f.source_code and "BETA-MARKER-222" in f.source_code)


# ---------------------------------------------------------------------------
# Write-to-directory contract (section 8 support)
# ---------------------------------------------------------------------------

class TestWriteToDirectory:
    def test_accepts_result_or_file_tuple(self, tmp_path: Path) -> None:
        app = _discover(tmp_path, {"A.cob": PROGRAM_A, "B.cob": PROGRAM_B})
        result = ApplicationGenerator().generate(app)
        assert result.success

        out_result = tmp_path / "from-result"
        out_tuple = tmp_path / "from-tuple"
        ApplicationGenerator.write_to_directory(result, out_result)
        ApplicationGenerator.write_to_directory(result.generated_files, out_tuple)

        assert sorted(p.name for p in out_result.glob("*.java")) == sorted(
            p.name for p in out_tuple.glob("*.java")
        )

    def test_filenames_cannot_escape_output_dir(self, tmp_path: Path) -> None:
        evil = GeneratedFile(
            filename="../evil-escape.java",
            source_code="public class Evil {}",
            class_name="Evil",
        )
        out_dir = tmp_path / "safe-out"
        ApplicationGenerator.write_to_directory((evil,), out_dir)

        assert (out_dir / "evil-escape.java").exists()
        assert not (tmp_path / "evil-escape.java").exists()
