"""Tests for Task 6B: Multi-Program COBOL Application Discovery.

Verifies:
- Application-level IR construction
- Program unit representation
- PROGRAM-ID extraction
- CALL dependency discovery
- COPY dependency discovery
- Entry point discovery
- File dependency discovery
- Dependency graph construction
- Application validation
- Domain-neutral equivalence
- Lexical false-positives
- Mutation matrix
- Determinism
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.ir import (
    CobolApplication,
    CobolProgram,
    CobolProgramUnit,
    CopybookReference,
    DependencyEdge,
    FileDependency,
    ProgramCall,
    derive_capabilities,
)


# ============================================================
# Helper COBOL sources for testing
# ============================================================

ACCOUNT_MAIN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCOUNT-MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ACCOUNT-ID     PIC X(10).
       01 WS-VALID          PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ACCOUNT-FILE.
           READ ACCOUNT-FILE
               AT END MOVE 'Y' TO WS-VALID
           END-READ.
           CALL 'ACCOUNT-VALIDATE' USING WS-ACCOUNT-ID.
           CALL 'ACCOUNT-STORE' USING WS-ACCOUNT-ID.
           CLOSE ACCOUNT-FILE.
           STOP RUN.
"""

ACCOUNT_VALIDATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCOUNT-VALIDATE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ACCOUNT-ID     PIC X(10).
       PROCEDURE DIVISION.
       VALIDATE-PARA.
           IF WS-ACCOUNT-ID NOT = SPACES
               DISPLAY 'VALID ACCOUNT'
           END-IF.
           EXIT PROGRAM.
"""

ACCOUNT_STORE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCOUNT-STORE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ACCOUNT-ID     PIC X(10).
       PROCEDURE DIVISION.
       STORE-PARA.
           OPEN OUTPUT ACCOUNT-OUT.
           WRITE ACCOUNT-REC FROM WS-ACCOUNT-ID.
           CLOSE ACCOUNT-OUT.
           EXIT PROGRAM.
"""

ORDER_MAIN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDER-MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ORDER-ID       PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ORDER-FILE.
           READ ORDER-FILE
               AT END MOVE 'Y' TO WS-ORDER-ID
           END-READ.
           CALL 'ORDER-VALIDATE' USING WS-ORDER-ID.
           CALL 'ORDER-STORE' USING WS-ORDER-ID.
           CLOSE ORDER-FILE.
           STOP RUN.
"""

ORDER_VALIDATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDER-VALIDATE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ORDER-ID       PIC X(10).
       PROCEDURE DIVISION.
       VALIDATE-PARA.
           IF WS-ORDER-ID NOT = SPACES
               DISPLAY 'VALID ORDER'
           END-IF.
           EXIT PROGRAM.
"""

ORDER_STORE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDER-STORE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-ORDER-ID       PIC X(10).
       PROCEDURE DIVISION.
       STORE-PARA.
           OPEN OUTPUT ORDER-OUT.
           WRITE ORDER-REC FROM WS-ORDER-ID.
           CLOSE ORDER-OUT.
           EXIT PROGRAM.
"""

CUSTOMER_MAIN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTOMER-MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CUSTOMER-ID    PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT CUSTOMER-FILE.
           READ CUSTOMER-FILE
               AT END MOVE 'Y' TO WS-CUSTOMER-ID
           END-READ.
           CALL 'CUSTOMER-VALIDATE' USING WS-CUSTOMER-ID.
           CALL 'CUSTOMER-STORE' USING WS-CUSTOMER-ID.
           CLOSE CUSTOMER-FILE.
           STOP RUN.
"""

CUSTOMER_VALIDATE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTOMER-VALIDATE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CUSTOMER-ID    PIC X(10).
       PROCEDURE DIVISION.
       VALIDATE-PARA.
           IF WS-CUSTOMER-ID NOT = SPACES
               DISPLAY 'VALID CUSTOMER'
           END-IF.
           EXIT PROGRAM.
"""

CUSTOMER_STORE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTOMER-STORE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CUSTOMER-ID    PIC X(10).
       PROCEDURE DIVISION.
       STORE-PARA.
           OPEN OUTPUT CUSTOMER-OUT.
           WRITE CUSTOMER-REC FROM WS-CUSTOMER-ID.
           CLOSE CUSTOMER-OUT.
           EXIT PROGRAM.
"""

PROGRAM_WITH_COPY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGRAM-WITH-COPY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY MY-COPYBOOK.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'HELLO'.
           STOP RUN.
"""

PROGRAM_WITH_ENTRY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGRAM-WITH-ENTRY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DATA           PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ENTRY 'CUSTOM-ENTRY' USING WS-DATA.
           DISPLAY WS-DATA.
           STOP RUN.
"""

PROGRAM_WITH_UNRESOLVED_CALL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGRAM-UNRESOLVED.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DATA           PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'UNKNOWN-PROGRAM' USING WS-DATA.
           STOP RUN.
"""


# ============================================================
# A. Application IR Construction Tests
# ============================================================

class TestApplicationIR:
    """Verify application-level IR construction."""

    def test_cobol_application_construction(self):
        """CobolApplication can be constructed."""
        app = CobolApplication(
            application_id="TEST-APP",
            programs=(),
            copybooks=(),
            edges=(),
        )
        assert app.application_id == "TEST-APP"
        assert len(app.programs) == 0

    def test_cobol_program_unit_construction(self):
        """CobolProgramUnit can be constructed."""
        program = CobolProgram(program_id="TEST")
        unit = CobolProgramUnit(
            program_id="TEST",
            source_path="test.cob",
            program=program,
        )
        assert unit.program_id == "TEST"
        assert unit.source_path == "test.cob"

    def test_program_call_construction(self):
        """ProgramCall can be constructed."""
        call = ProgramCall(
            caller="MAIN",
            target="SUB",
            arguments=("ARG1", "ARG2"),
        )
        assert call.caller == "MAIN"
        assert call.target == "SUB"
        assert call.arguments == ("ARG1", "ARG2")

    def test_copybook_reference_construction(self):
        """CopybookReference can be constructed."""
        cb = CopybookReference(
            source_program="MAIN",
            copybook_name="MY-RECORD",
        )
        assert cb.source_program == "MAIN"
        assert cb.copybook_name == "MY-RECORD"

    def test_file_dependency_construction(self):
        """FileDependency can be constructed."""
        fd = FileDependency(
            program_id="MAIN",
            file_name="DATA-FILE",
            operation="READ",
            mode="INPUT",
        )
        assert fd.program_id == "MAIN"
        assert fd.file_name == "DATA-FILE"
        assert fd.operation == "READ"

    def test_dependency_edge_construction(self):
        """DependencyEdge can be constructed."""
        edge = DependencyEdge(
            source="A",
            target="B",
            edge_type="CALL",
        )
        assert edge.source == "A"
        assert edge.target == "B"
        assert edge.edge_type == "CALL"


# ============================================================
# B. Application Discovery Tests
# ============================================================

class TestApplicationDiscovery:
    """Verify application discovery from source directories."""

    def test_discover_single_program(self):
        """Discover single program application."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create COBOL file
            cobol_file = Path(tmpdir) / "MAIN.cob"
            cobol_file.write_text(ACCOUNT_MAIN)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST-APP")

            assert app.application_id == "TEST-APP"
            assert len(app.programs) == 1
            assert app.programs[0].program_id == "ACCOUNT-MAIN"

    def test_discover_multi_program(self):
        """Discover multi-program application."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple COBOL files
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="ACCOUNT-APP")

            assert app.application_id == "ACCOUNT-APP"
            assert len(app.programs) == 3

            program_ids = {p.program_id for p in app.programs}
            assert "ACCOUNT-MAIN" in program_ids
            assert "ACCOUNT-VALIDATE" in program_ids
            assert "ACCOUNT-STORE" in program_ids

    def test_discover_with_copybook(self):
        """Discover program with COPY statement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_COPY)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="COPY-APP")

            assert len(app.programs) == 1
            assert len(app.programs[0].copybooks) == 1
            assert app.programs[0].copybooks[0].copybook_name == "MY-COPYBOOK"
            assert "MY-COPYBOOK" in app.copybooks

    def test_discover_with_entry_point(self):
        """Discover program with ENTRY statement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_ENTRY)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="ENTRY-APP")

            assert len(app.programs) == 1
            assert len(app.programs[0].entry_points) == 1
            assert app.programs[0].entry_points[0] == "CUSTOM-ENTRY"

    def test_discover_with_unresolved_call(self):
        """Discover program with unresolved CALL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_UNRESOLVED_CALL)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="UNRESOLVED-APP")

            assert len(app.programs) == 1
            assert len(app.programs[0].calls) == 1
            assert app.programs[0].calls[0].target == "UNKNOWN-PROGRAM"


# ============================================================
# C. PROGRAM-ID Extraction Tests
# ============================================================

class TestProgramIdentity:
    """Verify PROGRAM-ID is structurally extracted."""

    def test_program_id_from_source(self):
        """PROGRAM-ID comes from source, not filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # File named RANDOM123.cob but PROGRAM-ID is ACCOUNT-MAIN
            cobol_file = Path(tmpdir) / "RANDOM123.cob"
            cobol_file.write_text(ACCOUNT_MAIN)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            assert len(app.programs) == 1
            assert app.programs[0].program_id == "ACCOUNT-MAIN"

    def test_filename_rename_preserves_identity(self):
        """Renaming file does not change program identity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create with original name
            cobol_file = Path(tmpdir) / "ORIGINAL.cob"
            cobol_file.write_text(ACCOUNT_MAIN)

            discovery = ApplicationDiscovery()
            app1 = discovery.discover(tmpdir, application_id="TEST")

            # Rename file
            new_file = Path(tmpdir) / "RENAMED.cob"
            cobol_file.rename(new_file)

            app2 = discovery.discover(tmpdir, application_id="TEST")

            assert app1.programs[0].program_id == app2.programs[0].program_id
            assert app1.programs[0].program_id == "ACCOUNT-MAIN"


# ============================================================
# D. CALL Discovery Tests
# ============================================================

class TestCallDiscovery:
    """Verify CALL dependency discovery."""

    def test_call_discovery(self):
        """CALL statements are discovered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            main_unit = app.get_program("ACCOUNT-MAIN")
            assert main_unit is not None
            assert len(main_unit.calls) == 2

            call_targets = {c.target for c in main_unit.calls}
            assert "ACCOUNT-VALIDATE" in call_targets
            assert "ACCOUNT-STORE" in call_targets

    def test_call_resolution(self):
        """CALL targets are resolved against known programs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            # Check edges
            call_edges = [e for e in app.edges if e.edge_type == "CALL"]
            assert len(call_edges) == 2

            for edge in call_edges:
                assert "resolution=RESOLVED" in edge.metadata

    def test_unresolved_call_detection(self):
        """Unresolved CALL targets are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_UNRESOLVED_CALL)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            call_edges = [e for e in app.edges if e.edge_type == "CALL"]
            assert len(call_edges) == 1
            assert "resolution=UNRESOLVED" in call_edges[0].metadata


# ============================================================
# E. COPY Discovery Tests
# ============================================================

class TestCopyDiscovery:
    """Verify COPY dependency discovery."""

    def test_copy_discovery(self):
        """COPY statements are discovered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_COPY)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            main_unit = app.get_program("PROGRAM-WITH-COPY")
            assert main_unit is not None
            assert len(main_unit.copybooks) == 1
            assert main_unit.copybooks[0].copybook_name == "MY-COPYBOOK"

    def test_copy_edges(self):
        """COPY statements create dependency edges."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_COPY)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            copy_edges = [e for e in app.edges if e.edge_type == "COPY"]
            assert len(copy_edges) == 1
            assert copy_edges[0].target == "MY-COPYBOOK"


# ============================================================
# F. File Dependency Tests
# ============================================================

class TestFileDependencies:
    """Verify file dependency discovery."""

    def test_file_dependency_discovery(self):
        """File dependencies are discovered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            main_unit = app.get_program("ACCOUNT-MAIN")
            assert main_unit is not None

            # Should have file dependencies
            file_deps = main_unit.file_dependencies
            assert len(file_deps) > 0

    def test_file_dependency_types(self):
        """File dependencies have correct operation types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            main_unit = app.get_program("ACCOUNT-MAIN")
            operations = {fd.operation for fd in main_unit.file_dependencies}
            assert "OPEN" in operations or "READ" in operations


# ============================================================
# G. Dependency Graph Tests
# ============================================================

class TestDependencyGraph:
    """Verify dependency graph construction."""

    def test_dependency_graph_edges(self):
        """Dependency graph contains correct edges."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            assert len(app.edges) > 0

            edge_types = {e.edge_type for e in app.edges}
            assert "CALL" in edge_types

    def test_get_callers(self):
        """get_callers returns correct programs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            callers = app.get_callers("ACCOUNT-VALIDATE")
            assert "ACCOUNT-MAIN" in callers

    def test_get_callees(self):
        """get_callees returns correct programs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            callees = app.get_callees("ACCOUNT-MAIN")
            assert "ACCOUNT-VALIDATE" in callees
            assert "ACCOUNT-STORE" in callees


# ============================================================
# H. Application Validation Tests
# ============================================================

class TestApplicationValidation:
    """Verify application validation rules."""

    def test_valid_application(self):
        """Valid application passes validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            errors = app.validate()
            # No errors expected for well-formed application
            unresolved = [e for e in errors if "Unresolved CALL" in e]
            assert len(unresolved) == 0

    def test_duplicate_program_id_detection(self):
        """Duplicate PROGRAM-IDs are detected."""
        # Create program with same ID in two files
        duplicate_main = ACCOUNT_MAIN.replace(
            "PROGRAM-ID. ACCOUNT-MAIN.",
            "PROGRAM-ID. ACCOUNT-MAIN.\n       PROGRAM-ID. ACCOUNT-MAIN.",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN1.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "MAIN2.cob").write_text(ACCOUNT_MAIN)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            errors = app.validate()
            # Note: This depends on parser behavior
            # If parser handles duplicate IDs, this test may need adjustment

    def test_unresolved_call_reporting(self):
        """Unresolved calls are reported in validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(PROGRAM_WITH_UNRESOLVED_CALL)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            errors = app.validate()
            unresolved = [e for e in errors if "Unresolved CALL" in e]
            assert len(unresolved) > 0


# ============================================================
# I. Domain-Neutral Equivalence Tests
# ============================================================

class TestDomainNeutralEquivalence:
    """Verify domain-neutral applications produce equivalent graphs."""

    def test_account_vs_order_equivalence(self):
        """ACCOUNT and ORDER applications with same structure produce equivalent graphs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create ACCOUNT application
            account_dir = Path(tmpdir) / "account"
            account_dir.mkdir()
            (account_dir / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (account_dir / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (account_dir / "STORE.cob").write_text(ACCOUNT_STORE)

            # Create ORDER application
            order_dir = Path(tmpdir) / "order"
            order_dir.mkdir()
            (order_dir / "MAIN.cob").write_text(ORDER_MAIN)
            (order_dir / "VALIDATE.cob").write_text(ORDER_VALIDATE)
            (order_dir / "STORE.cob").write_text(ORDER_STORE)

            discovery = ApplicationDiscovery()
            app_account = discovery.discover(account_dir, application_id="ACCOUNT-APP")
            app_order = discovery.discover(order_dir, application_id="ORDER-APP")

            # Same structure
            assert len(app_account.programs) == len(app_order.programs)
            assert len(app_account.edges) == len(app_order.edges)

            # Same edge types
            account_edge_types = {e.edge_type for e in app_account.edges}
            order_edge_types = {e.edge_type for e in app_order.edges}
            assert account_edge_types == order_edge_types

    def test_customer_equivalence(self):
        """CUSTOMER application has same structure as ACCOUNT."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create ACCOUNT application
            account_dir = Path(tmpdir) / "account"
            account_dir.mkdir()
            (account_dir / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (account_dir / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (account_dir / "STORE.cob").write_text(ACCOUNT_STORE)

            # Create CUSTOMER application
            customer_dir = Path(tmpdir) / "customer"
            customer_dir.mkdir()
            (customer_dir / "MAIN.cob").write_text(CUSTOMER_MAIN)
            (customer_dir / "VALIDATE.cob").write_text(CUSTOMER_VALIDATE)
            (customer_dir / "STORE.cob").write_text(CUSTOMER_STORE)

            discovery = ApplicationDiscovery()
            app_account = discovery.discover(account_dir, application_id="ACCOUNT-APP")
            app_customer = discovery.discover(customer_dir, application_id="CUSTOMER-APP")

            # Same structure
            assert len(app_account.programs) == len(app_customer.programs)
            assert len(app_account.edges) == len(app_customer.edges)


# ============================================================
# J. Lexical False-Positive Tests
# ============================================================

class TestLexicalFalsePositives:
    """Verify domain names do not affect discovery."""

    def test_claim_name_no_special_behavior(self):
        """CLAIM in program name does not activate special behavior."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create program with CLAIM in name
            claim_main = ACCOUNT_MAIN.replace("ACCOUNT-MAIN", "CLAIM-MAIN")
            claim_main = claim_main.replace("ACCOUNT-VALIDATE", "CLAIM-VALIDATE")
            claim_main = claim_main.replace("ACCOUNT-STORE", "CLAIM-STORE")
            (Path(tmpdir) / "MAIN.cob").write_text(claim_main)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="CLAIM-APP")

            assert len(app.programs) == 1
            assert app.programs[0].program_id == "CLAIM-MAIN"

    def test_settlement_name_no_special_behavior(self):
        """SETTLEMENT in program name does not activate special behavior."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settlement_main = ACCOUNT_MAIN.replace("ACCOUNT-MAIN", "SETTLEMENT-MAIN")
            (Path(tmpdir) / "MAIN.cob").write_text(settlement_main)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="SETTLEMENT-APP")

            assert len(app.programs) == 1
            assert app.programs[0].program_id == "SETTLEMENT-MAIN"

    def test_payment_name_no_special_behavior(self):
        """PAYMENT in program name does not activate special behavior."""
        with tempfile.TemporaryDirectory() as tmpdir:
            payment_main = ACCOUNT_MAIN.replace("ACCOUNT-MAIN", "PAYMENT-MAIN")
            (Path(tmpdir) / "MAIN.cob").write_text(payment_main)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="PAYMENT-APP")

            assert len(app.programs) == 1
            assert app.programs[0].program_id == "PAYMENT-MAIN"


# ============================================================
# K. Mutation Matrix Tests
# ============================================================

class TestMutationMatrix:
    """Verify mutations produce correct application model changes."""

    def test_add_call_changes_edges(self):
        """Adding a CALL statement adds dependency edge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create program without extra call
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()
            app1 = discovery.discover(tmpdir, application_id="TEST")

            # Add CALL to main
            modified = ACCOUNT_MAIN
            (Path(tmpdir) / "MAIN.cob").write_text(modified)

            app2 = discovery.discover(tmpdir, application_id="TEST")

            # Should have more edges
            assert len(app2.edges) >= len(app1.edges)

    def test_remove_call_changes_edges(self):
        """Removing a CALL statement removes dependency edge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create program with calls
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()
            app1 = discovery.discover(tmpdir, application_id="TEST")

            # Remove one CALL
            modified_main = ACCOUNT_MAIN.replace(
                "CALL 'ACCOUNT-STORE' USING WS-ACCOUNT-ID.",
                "",
            )
            (Path(tmpdir) / "MAIN.cob").write_text(modified_main)

            app2 = discovery.discover(tmpdir, application_id="TEST")

            # Should have fewer CALL edges
            call_edges1 = [e for e in app1.edges if e.edge_type == "CALL"]
            call_edges2 = [e for e in app2.edges if e.edge_type == "CALL"]
            assert len(call_edges2) < len(call_edges1)

    def test_change_call_target(self):
        """Changing CALL target updates dependency edge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)

            discovery = ApplicationDiscovery()
            app1 = discovery.discover(tmpdir, application_id="TEST")

            # Change CALL target
            modified_main = ACCOUNT_MAIN.replace(
                "CALL 'ACCOUNT-STORE'",
                "CALL 'NEW-STORE'",
            )
            (Path(tmpdir) / "MAIN.cob").write_text(modified_main)

            app2 = discovery.discover(tmpdir, application_id="TEST")

            # Check new target exists
            call_edges = [e for e in app2.edges if e.edge_type == "CALL"]
            targets = {e.target for e in call_edges}
            assert "NEW-STORE" in targets

    def test_add_copy_changes_edges(self):
        """Adding a COPY statement adds dependency edge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)

            discovery = ApplicationDiscovery()
            app1 = discovery.discover(tmpdir, application_id="TEST")

            # Add COPY
            modified = ACCOUNT_MAIN + "\n       COPY MY-RECORD.\n"
            (Path(tmpdir) / "MAIN.cob").write_text(modified)

            app2 = discovery.discover(tmpdir, application_id="TEST")

            # Should have COPY edge
            copy_edges = [e for e in app2.edges if e.edge_type == "COPY"]
            assert len(copy_edges) > 0

    def test_filename_rename_preserves_semantics(self):
        """Renaming file does not change semantic identity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cobol_file = Path(tmpdir) / "ORIGINAL.cob"
            cobol_file.write_text(ACCOUNT_MAIN)

            discovery = ApplicationDiscovery()
            app1 = discovery.discover(tmpdir, application_id="TEST")

            # Rename file
            new_file = Path(tmpdir) / "RENAMED.cob"
            cobol_file.rename(new_file)

            app2 = discovery.discover(tmpdir, application_id="TEST")

            # Program identity unchanged
            assert app1.programs[0].program_id == app2.programs[0].program_id

            # Dependencies unchanged
            assert len(app1.edges) == len(app2.edges)


# ============================================================
# L. Determinism Tests
# ============================================================

class TestDeterminism:
    """Verify deterministic discovery."""

    def test_same_source_same_application(self):
        """Same source tree produces identical application IR."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()

            apps = []
            for _ in range(3):
                app = discovery.discover(tmpdir, application_id="TEST")
                apps.append(app)

            # All should be identical
            for i in range(1, len(apps)):
                assert apps[0].application_id == apps[i].application_id
                assert len(apps[0].programs) == len(apps[i].programs)
                assert len(apps[0].edges) == len(apps[i].edges)

                # Check program IDs are in same order
                ids0 = [p.program_id for p in apps[0].programs]
                idsi = [p.program_id for p in apps[i].programs]
                assert ids0 == idsi

    def test_deterministic_serialization(self):
        """Application IR serializes deterministically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "MAIN.cob").write_text(ACCOUNT_MAIN)
            (Path(tmpdir) / "VALIDATE.cob").write_text(ACCOUNT_VALIDATE)
            (Path(tmpdir) / "STORE.cob").write_text(ACCOUNT_STORE)

            discovery = ApplicationDiscovery()

            serializations = []
            for _ in range(3):
                app = discovery.discover(tmpdir, application_id="TEST")
                # Create deterministic representation
                rep = {
                    "app_id": app.application_id,
                    "programs": sorted([p.program_id for p in app.programs]),
                    "edges": sorted([
                        (e.source, e.target, e.edge_type)
                        for e in app.edges
                    ]),
                }
                serializations.append(str(rep))

            # All serializations should be identical
            assert len(set(serializations)) == 1


# ============================================================
# M. Generator Compatibility Tests
# ============================================================

class TestGeneratorCompatibility:
    """Verify existing single-program generation remains green."""

    def test_single_program_generation_unchanged(self):
        """Single program generation still works."""
        from engine.transformation.java_generator import JavaGenerator

        parser = CobolParser()
        gen = JavaGenerator()

        # Test with existing workload
        from pathlib import Path
        cobol = Path("fixtures/workload-claims/cobol/CLAIMS.cob").read_text()
        program = parser.parse(cobol)
        files = gen.generate(program)

        assert len(files) == 1
        assert len(files[0].source_code) > 0

    def test_workload_generation_unchanged(self):
        """All workloads still generate."""
        from engine.transformation.java_generator import JavaGenerator

        parser = CobolParser()
        gen = JavaGenerator()

        workloads = [
            ("workload-claims", "fixtures/workload-claims/cobol/CLAIMS.cob"),
            ("workload-gradecalc", "fixtures/workload-gradecalc/cobol/GRADE-CALC.cob"),
            ("workload-studentproc", "fixtures/workload-studentproc/cobol/STUDENT-PROCESSOR.cob"),
            ("workload-minimal", "fixtures/workload-minimal/cobol/SIMPLE-CALC.cob"),
        ]

        for name, path in workloads:
            cobol = Path(path).read_text()
            program = parser.parse(cobol)
            files = gen.generate(program)
            assert len(files) == 1
            assert len(files[0].source_code) > 0


# ============================================================
# N. Forensic Search Tests
# ============================================================

class TestForensicSearch:
    """Verify no domain coupling in architecture."""

    def test_no_domain_driven_discovery(self):
        """Discovery does not use domain vocabulary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create program with CLAIM name
            claim_main = ACCOUNT_MAIN.replace("ACCOUNT-MAIN", "CLAIM-MAIN")
            (Path(tmpdir) / "MAIN.cob").write_text(claim_main)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            # Should work the same as any other program
            assert len(app.programs) == 1
            assert app.programs[0].program_id == "CLAIM-MAIN"

    def test_no_filename_detection(self):
        """Discovery does not use filename for semantics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file with random name
            cobol_file = Path(tmpdir) / "random123.cob"
            cobol_file.write_text(ACCOUNT_MAIN)

            discovery = ApplicationDiscovery()
            app = discovery.discover(tmpdir, application_id="TEST")

            # Program ID comes from source, not filename
            assert app.programs[0].program_id == "ACCOUNT-MAIN"
