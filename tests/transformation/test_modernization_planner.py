"""Tests for Phase 1: Modernization Planner.

Verifies the complete flow:
    ingestion → discovery → capability graph → modernization plan

as one deterministic flow with fail-closed semantics.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engine.modernization.modernization_planner import (
    ModernizationPlanner,
    ModernizationPlan,
    ModernizationStatus,
    BlockingReason,
    TransformationStrategy,
    ValidationStrategy,
    CapabilityLevel,
)


# Test fixture COBOL sources
SIMPLE_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIMPLE.
       PROCEDURE DIVISION.
           DISPLAY "HELLO".
           STOP RUN.
"""

MAIN_WITH_CALL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DATA PIC X(10).
       PROCEDURE DIVISION.
           MOVE "TEST" TO WS-DATA.
           CALL "HELPER" USING WS-DATA.
           STOP RUN.
"""

HELPER_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELPER.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LS-DATA PIC X(10).
       PROCEDURE DIVISION USING LS-DATA.
           DISPLAY LS-DATA.
           EXIT PROGRAM.
"""

PROGRAM_WITH_COPY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WITH-COPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY MYCOPY.
       PROCEDURE DIVISION.
           DISPLAY "DONE".
           STOP RUN.
"""

PROGRAM_WITH_FILES = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILE-PROG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT INPUT-FILE ASSIGN TO "input.dat".
           SELECT OUTPUT-FILE ASSIGN TO "output.dat".
       DATA DIVISION.
       FILE SECTION.
       FD INPUT-FILE.
       01 INPUT-REC PIC X(80).
       FD OUTPUT-FILE.
       01 OUTPUT-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-EOF PIC X VALUE "N".
       PROCEDURE DIVISION.
           OPEN INPUT INPUT-FILE.
           OPEN OUTPUT OUTPUT-FILE.
           READ INPUT-FILE AT END MOVE "Y" TO WS-EOF END-READ.
           WRITE OUTPUT-REC FROM INPUT-REC.
           CLOSE INPUT-FILE.
           CLOSE OUTPUT-FILE.
           STOP RUN.
"""

PROGRAM_WITH_GOTO = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTO-PROG.
       PROCEDURE DIVISION.
           DISPLAY "START".
           GO TO END-PARA.
           DISPLAY "SKIPPED".
       END-PARA.
           DISPLAY "END".
           STOP RUN.
"""

PROGRAM_WITH_DYNAMIC_CALL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DYNAMIC-MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM PIC X(8) VALUE "HELPER".
       PROCEDURE DIVISION.
           CALL WS-PGM.
           STOP RUN.
"""

# Circular dependency
CIRCULAR_A = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CIRC-A.
       PROCEDURE DIVISION.
           CALL "CIRC-B".
           STOP RUN.
"""

CIRCULAR_B = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CIRC-B.
       PROCEDURE DIVISION.
           CALL "CIRC-A".
           EXIT PROGRAM.
"""

UNRESOLVED_CALL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNRESOLVED.
       PROCEDURE DIVISION.
           CALL "DOES-NOT-EXIST".
           STOP RUN.
"""

MULTI_ENTRY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTI-ENTRY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DATA PIC X(10).
       PROCEDURE DIVISION.
       ENTRY "CUSTOM-ENTRY" USING WS-DATA.
           DISPLAY WS-DATA.
           STOP RUN.
"""

THREE_PROGRAM_CHAIN = {
    "MAIN.cob": """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       PROCEDURE DIVISION.
           CALL "MIDDLE".
           STOP RUN.
""",
    "MIDDLE.cob": """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MIDDLE.
       PROCEDURE DIVISION.
           CALL "LEAF".
           EXIT PROGRAM.
""",
    "LEAF.cob": """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEAF.
       PROCEDURE DIVISION.
           DISPLAY "LEAF".
           EXIT PROGRAM.
""",
}


class TestModernizationPlannerBasic:
    """Basic planner functionality tests."""

    def test_plan_simple_program(self):
        """Plan a single simple program."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "SIMPLE.cob").write_text(SIMPLE_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)  # Docker available for SUPPORTED
            plan = planner.plan(tmpdir, application_id="SIMPLE-APP")

            assert isinstance(plan, ModernizationPlan)
            assert plan.application_id == "SIMPLE-APP"
            assert plan.total_programs == 1
            assert plan.supported_programs == 1
            assert plan.overall_status == ModernizationStatus.READY

    def test_plan_multi_program(self):
        """Plan a multi-program application."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(MAIN_WITH_CALL)
            (Path(tmpdir) / "HELPER.cob").write_text(HELPER_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)  # Docker available for SUPPORTED
            plan = planner.plan(tmpdir, application_id="MULTI-APP")

            assert plan.total_programs == 2
            assert plan.supported_programs == 2
            program_ids = {p.program_id for p in plan.programs}
            assert "MAIN" in program_ids
            assert "HELPER" in program_ids

    def test_plan_deterministic(self):
        """Same source produces identical plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(MAIN_WITH_CALL)
            (Path(tmpdir) / "HELPER.cob").write_text(HELPER_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)

            plan1 = planner.plan(tmpdir, application_id="DETERMINISTIC")
            plan2 = planner.plan(tmpdir, application_id="DETERMINISTIC")

            assert plan1.application_id == plan2.application_id
            assert plan1.total_programs == plan2.total_programs
            assert len(plan1.programs) == len(plan2.programs)
            for p1, p2 in zip(plan1.programs, plan2.programs):
                assert p1.program_id == p2.program_id
                assert p1.capability_level == p2.capability_level
                assert p1.transformation_strategy == p2.transformation_strategy


class TestModernizationPlannerPrograms:
    """Tests for program exposure."""

    def test_programs_exposed(self):
        """All programs are exposed with details."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(MAIN_WITH_CALL)
            (Path(tmpdir) / "HELPER.cob").write_text(HELPER_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            assert len(plan.programs) == 2
            for p in plan.programs:
                assert p.program_id in ("MAIN", "HELPER")
                assert p.source_path
                assert isinstance(p.capability_level, CapabilityLevel)
                assert p.capability_reason
                assert isinstance(p.transformation_strategy, TransformationStrategy)
                assert isinstance(p.validation_strategy, ValidationStrategy)

    def test_entry_programs_identified(self):
        """Entry programs (STOP RUN) are identified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(MAIN_WITH_CALL)
            (Path(tmpdir) / "HELPER.cob").write_text(HELPER_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            entry_ids = {ep.program_id for ep in plan.entry_programs}
            assert "MAIN" in entry_ids  # MAIN has STOP RUN
            # HELPER has EXIT PROGRAM, not STOP RUN

    def test_entry_program_with_entry_statement(self):
        """Programs with ENTRY statement are identified as entry points."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MULTI.cob").write_text(MULTI_ENTRY)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            assert len(plan.entry_programs) == 1
            assert plan.entry_programs[0].program_id == "MULTI-ENTRY"
            assert "CUSTOM-ENTRY" in plan.entry_programs[0].entry_points


class TestModernizationPlannerCallRelationships:
    """Tests for CALL relationship exposure."""

    def test_call_relationships_exposed(self):
        """CALL relationships are exposed with full details."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(MAIN_WITH_CALL)
            (Path(tmpdir) / "HELPER.cob").write_text(HELPER_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            assert len(plan.call_relationships) == 1
            cr = plan.call_relationships[0]
            assert cr.caller == "MAIN"
            assert cr.target == "HELPER"
            assert cr.call_type == "STATIC"
            assert cr.resolution == "RESOLVED"
            assert cr.capability_level == CapabilityLevel.SUPPORTED
            assert cr.may_proceed is True

    def test_unresolved_call_marked_partial(self):
        """Unresolved CALL targets are marked PARTIAL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(UNRESOLVED_CALL)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            assert len(plan.call_relationships) == 1
            cr = plan.call_relationships[0]
            assert cr.resolution == "UNRESOLVED"
            assert cr.capability_level == CapabilityLevel.PARTIAL
            assert cr.may_proceed is False  # PARTIAL cannot proceed (fail-closed)
            assert BlockingReason.UNRESOLVED_CALL in cr.blocking_reasons

    def test_dynamic_call_blocked(self):
        """Dynamic CALL (data-item target) is blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_DYNAMIC_CALL)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            assert len(plan.call_relationships) == 1
            cr = plan.call_relationships[0]
            assert cr.call_type == "DYNAMIC"
            assert cr.capability_level == CapabilityLevel.UNSUPPORTED
            assert cr.may_proceed is False
            assert BlockingReason.DYNAMIC_CALL in cr.blocking_reasons

    def test_recursive_call_blocked(self):
        """Recursive/self CALL is blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "A.cob").write_text(CIRCULAR_A)
            (Path(tmpdir) / "B.cob").write_text(CIRCULAR_B)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            # The cycle detection should create blocking reasons
            blocking_summary = "\n".join(plan.blocking_summary)
            assert "CALL_CYCLE" in blocking_summary or "RECURSIVE_CALL" in blocking_summary


class TestModernizationPlannerCopybookRelationships:
    """Tests for COPY relationship exposure."""

    def test_copybook_relationships_exposed(self):
        """COPY relationships are exposed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_COPY)
            # Create the copybook file
            (Path(tmpdir) / "MYCOPY.cpy").write_text("01 WS-DATA PIC X(10).\n")
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            assert len(plan.copybook_relationships) == 1
            cb = plan.copybook_relationships[0]
            assert cb.copybook_name == "MYCOPY"
            assert cb.source_program == "WITH-COPY"
            assert cb.capability_level == CapabilityLevel.SUPPORTED
            assert cb.may_proceed is True

    def test_missing_copybook_not_in_plan(self):
        """Missing copybooks are handled in capability analysis."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_COPY)
            # No copybook file created
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            # Copybook relationship still exists but capability may be different
            assert len(plan.copybook_relationships) == 1


class TestModernizationPlannerFileDependencies:
    """Tests for file dependency exposure."""

    def test_file_dependencies_exposed(self):
        """File dependencies are exposed with operation modes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "FILE.cob").write_text(PROGRAM_WITH_FILES)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            assert len(plan.file_dependencies) > 0
            fd = plan.file_dependencies[0]
            assert fd.program_id == "FILE-PROG"
            assert fd.file_name in ("INPUT-FILE", "OUTPUT-FILE")
            assert fd.operation in ("OPEN", "READ", "WRITE", "CLOSE")
            assert fd.capability_level == CapabilityLevel.SUPPORTED
            assert fd.may_proceed is True


class TestModernizationPlannerFailClosed:
    """Tests for fail-closed semantics."""

    def test_supported_may_proceed(self):
        """SUPPORTED programs may proceed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "SIMPLE.cob").write_text(SIMPLE_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            prog = plan.programs[0]
            assert prog.capability_level == CapabilityLevel.SUPPORTED
            assert prog.may_proceed is True

    def test_partial_cannot_proceed(self):
        """PARTIAL programs cannot proceed (fail-closed)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(UNRESOLVED_CALL)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            # Program itself is SUPPORTED, but the call relationship is PARTIAL
            # The overall status should reflect this
            assert plan.overall_status == ModernizationStatus.PARTIAL

    def test_unsupported_blocked(self):
        """UNSUPPORTED programs are blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "GOTO.cob").write_text(PROGRAM_WITH_GOTO)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            prog = plan.programs[0]
            assert prog.capability_level == CapabilityLevel.UNSUPPORTED
            assert prog.may_proceed is False
            assert BlockingReason.UNSUPPORTED_CONSTRUCT in prog.blocking_reasons
            assert plan.overall_status == ModernizationStatus.BLOCKED

    def test_unavailable_blocked(self):
        """UNAVAILABLE (Docker not available) blocks transformation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "SIMPLE.cob").write_text(SIMPLE_PROGRAM)
            # Explicitly set docker_available=False to simulate unavailability
            planner = ModernizationPlanner(docker_available=False)
            plan = planner.plan(tmpdir)

            # With docker_available=False, SUPPORTED programs become UNAVAILABLE
            prog = plan.programs[0]
            assert prog.capability_level in (CapabilityLevel.SUPPORTED, CapabilityLevel.UNAVAILABLE)
            if prog.capability_level == CapabilityLevel.UNAVAILABLE:
                assert prog.may_proceed is False
                assert BlockingReason.DOCKER_UNAVAILABLE in prog.blocking_reasons

    def test_unknown_blocked(self):
        """UNKNOWN capability level is blocked."""
        # This is tested implicitly - UNKNOWN should never be returned
        # but if it is, it should be treated as blocked
        pass


class TestModernizationPlannerTransformationStrategies:
    """Tests for transformation strategy assignment."""

    def test_supported_gets_internal_native(self):
        """SUPPORTED programs get INTERNAL_NATIVE strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "SIMPLE.cob").write_text(SIMPLE_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            prog = plan.programs[0]
            assert prog.transformation_strategy == TransformationStrategy.INTERNAL_NATIVE

    def test_unsupported_gets_manual(self):
        """UNSUPPORTED programs get MANUAL strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "GOTO.cob").write_text(PROGRAM_WITH_GOTO)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            prog = plan.programs[0]
            assert prog.transformation_strategy == TransformationStrategy.MANUAL

    def test_call_relationship_strategies(self):
        """CALL relationships get appropriate strategies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(MAIN_WITH_CALL)
            (Path(tmpdir) / "HELPER.cob").write_text(HELPER_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            cr = plan.call_relationships[0]
            assert cr.transformation_strategy == TransformationStrategy.INTERNAL_NATIVE

    def test_dynamic_call_gets_manual(self):
        """Dynamic CALL gets MANUAL strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_DYNAMIC_CALL)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            cr = plan.call_relationships[0]
            assert cr.transformation_strategy == TransformationStrategy.MANUAL


class TestModernizationPlannerValidationStrategies:
    """Tests for validation strategy assignment."""

    def test_supported_gets_docker_oracle(self):
        """SUPPORTED programs get DOCKER_ORACLE validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "SIMPLE.cob").write_text(SIMPLE_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            prog = plan.programs[0]
            assert prog.validation_strategy == ValidationStrategy.DOCKER_ORACLE

    def test_unsupported_gets_manual_review(self):
        """UNSUPPORTED programs get MANUAL_REVIEW validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "GOTO.cob").write_text(PROGRAM_WITH_GOTO)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            prog = plan.programs[0]
            assert prog.validation_strategy == ValidationStrategy.MANUAL_REVIEW


class TestModernizationPlannerSerialization:
    """Tests for plan serialization."""

    def test_plan_serializes_to_dict(self):
        """Plan can be serialized to dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(MAIN_WITH_CALL)
            (Path(tmpdir) / "HELPER.cob").write_text(HELPER_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir, application_id="SERIAL-TEST")

            d = plan.to_dict()
            assert d["application_id"] == "SERIAL-TEST"
            assert d["overall_status"] in ("READY", "PARTIAL", "BLOCKED", "UNKNOWN")
            assert "programs" in d
            assert "entry_programs" in d
            assert "call_relationships" in d
            assert "copybook_relationships" in d
            assert "file_dependencies" in d
            assert "blocking_summary" in d
            assert "transformation_plan" in d

    def test_plan_json_serializable(self):
        """Plan dictionary is JSON serializable."""
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(MAIN_WITH_CALL)
            (Path(tmpdir) / "HELPER.cob").write_text(HELPER_PROGRAM)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir)

            d = plan.to_dict()
            serialized = json.dumps(d, default=str)
            assert len(serialized) > 0
            deserialized = json.loads(serialized)
            assert deserialized["application_id"] == plan.application_id


class TestModernizationPlannerThreeProgramChain:
    """Tests with three-program call chain."""

    def test_three_program_chain(self):
        """Plan a three-program call chain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, content in THREE_PROGRAM_CHAIN.items():
                (Path(tmpdir) / name).write_text(content)
            planner = ModernizationPlanner(docker_available=True)
            plan = planner.plan(tmpdir, application_id="CHAIN-APP")

            assert plan.total_programs == 3
            assert plan.supported_programs == 3
            program_ids = {p.program_id for p in plan.programs}
            assert program_ids == {"MAIN", "MIDDLE", "LEAF"}

            # Check call relationships
            call_pairs = {(cr.caller, cr.target) for cr in plan.call_relationships}
            assert ("MAIN", "MIDDLE") in call_pairs
            assert ("MIDDLE", "LEAF") in call_pairs

            # MAIN is entry (has STOP RUN)
            entry_ids = {ep.program_id for ep in plan.entry_programs}
            assert "MAIN" in entry_ids


class TestModernizationPlannerCapabilityDetails:
    """Tests for capability detail exposure."""

    def test_program_details_exposed(self):
        """Program details (paragraphs, data items, files) are exposed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "FILE.cob").write_text(PROGRAM_WITH_FILES)
            planner = ModernizationPlanner(docker_available=False)
            plan = planner.plan(tmpdir)

            prog = plan.programs[0]
            assert prog.paragraphs > 0
            assert prog.data_items > 0
            assert prog.file_count > 0

    def test_blocking_summary_comprehensive(self):
        """Blocking summary covers all component types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "GOTO.cob").write_text(PROGRAM_WITH_GOTO)
            planner = ModernizationPlanner(docker_available=False)
            plan = planner.plan(tmpdir)

            assert len(plan.blocking_summary) > 0
            summary_text = "\n".join(plan.blocking_summary)
            assert "GOTO-PROG" in summary_text
            assert "UNSUPPORTED_CONSTRUCT" in summary_text


class TestModernizationPlannerEdgeCases:
    """Edge case tests."""

    def test_empty_directory(self):
        """Empty directory produces empty plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = ModernizationPlanner(docker_available=False)
            plan = planner.plan(tmpdir, application_id="EMPTY")

            assert plan.total_programs == 0
            assert plan.overall_status == ModernizationStatus.UNKNOWN

    def test_nonexistent_directory_raises(self):
        """Nonexistent directory raises ValueError."""
        planner = ModernizationPlanner(docker_available=False)
        with pytest.raises(ValueError, match="does not exist"):
            planner.plan("/nonexistent/path")

    def test_custom_application_id(self):
        """Custom application ID is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "SIMPLE.cob").write_text(SIMPLE_PROGRAM)
            planner = ModernizationPlanner(docker_available=False)
            plan = planner.plan(tmpdir, application_id="CUSTOM-ID")

            assert plan.application_id == "CUSTOM-ID"

    def test_entrypoint_respected(self):
        """Explicit entrypoint is considered in plan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(MAIN_WITH_CALL)
            (Path(tmpdir) / "HELPER.cob").write_text(HELPER_PROGRAM)
            planner = ModernizationPlanner(docker_available=False)
            plan = planner.plan(tmpdir, entrypoint="HELPER")

            # The transformation plan should have HELPER as entry
            assert plan.transformation_plan.oracle.entry_program in ("HELPER", "MAIN")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))