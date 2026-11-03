"""Regression tests for control-plane entry-program resolution.

Defect (found by the WS4 release gate, 2026-10-08):

``ApplicationCreate.java_entrypoint`` defaults to the placeholder ``"Main"``
and the frontend never sends it.  ``Service._generate_application`` forwarded
that string straight into ``ModernizationConfig.entrypoint``.  The Spring Boot
assembler only honours the value when it matches a discovered COBOL PROGRAM-ID
(``_derive_entry_point``); anything else falls back to "invoke every service",
which hoists CALL targets into top-level ``CommandLineRunner`` beans.  For
``fixtures/workload-integrated`` that reordered the CALL chain:

    oracle stdout   : INTEGRATED DEMO STARTED / INPUT ... / CALC-START / ...
    candidate stdout: CALC-START / CALC TAX=000000 / INTEGRATED DEMO STARTED / ...

so every default-created application with a CALL edge silently produced
behaviourally wrong Java, visible only as a downstream STDOUT MISMATCH.

These tests pin the resolution order and its fail-soft behaviour.  They do not
weaken any evidence or verdict gate.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from api.service import Service
from api.store import Store

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures/workload-integrated/cobol"


@pytest.fixture
def service():
    return Service(Store())


@pytest.fixture
def call_chain_source():
    """A MAIN -> CALB CALL chain with a copybook, on disk."""
    root = Path(tempfile.mkdtemp(prefix="entry-program-"))
    for name in ("MAIN.cob", "CALC.cob", "TAXREC.cpy"):
        shutil.copy(FIXTURE / name, root / name)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _app(service: Service, source: Path, entrypoint: str):
    app = service.create_application(
        name="entry-resolution",
        description="",
        workload_id="integrated",
        java_entrypoint=entrypoint,
    )
    app.cobol_source_path = str(source)
    return app


def test_placeholder_entrypoint_resolves_to_call_root(service, call_chain_source):
    """The default placeholder must NOT be forwarded verbatim."""
    app = _app(service, call_chain_source, "Main")
    resolved = service._resolve_entry_program(app)

    assert resolved == "INTGMAIN", (
        "an unmatched placeholder entrypoint must resolve to the single "
        "program no CALL targets, not stay 'Main'"
    )


def test_declared_root_program_is_honoured(service, call_chain_source):
    app = _app(service, call_chain_source, "INTGMAIN")
    assert service._resolve_entry_program(app) == "INTGMAIN"


def test_declared_callee_program_is_honoured(service, call_chain_source):
    """An explicitly declared callee is respected, not silently replaced."""
    app = _app(service, call_chain_source, "INTGCALC")
    assert service._resolve_entry_program(app) == "INTGCALC"


def test_declared_entrypoint_is_compared_case_insensitively(
    service, call_chain_source,
):
    app = _app(service, call_chain_source, "intgmain")
    assert service._resolve_entry_program(app) == "INTGMAIN"


def test_resolved_entrypoint_is_honoured_by_the_assembler(
    service, call_chain_source,
):
    """End-to-end guard on the exact defect: the resolved value must make the
    assembler select a single entry service instead of every service."""
    from engine.transformation.java_to_spring_mapping import _derive_entry_point
    from engine.transformation.java_ir import (
        JavaApplication,
        JavaClass,
        JavaMethod,
        JavaProgram,
    )

    app = _app(service, call_chain_source, "Main")
    entry_program = service._resolve_entry_program(app)

    java_app = JavaApplication(
        application_id="entry-resolution",
        programs=(
            JavaProgram(
                program_id="INTGCALC",
                java_class=JavaClass(
                    name="Intgcalc", package="com.generated.app.service",
                    methods=(JavaMethod(name="CALC_LOGIC"),),
                ),
            ),
            JavaProgram(
                program_id="INTGMAIN",
                java_class=JavaClass(
                    name="Intgmain", package="com.generated.app.service",
                    methods=(JavaMethod(name="MAIN_LOGIC"),),
                ),
                calls=("INTGCALC",),
            ),
        ),
    )

    placeholder_entry = _derive_entry_point(java_app, "com.generated.app", "Main")
    resolved_entry = _derive_entry_point(java_app, "com.generated.app", entry_program)

    assert placeholder_entry.selected_service == "", (
        "documents the defect: an unmatched entrypoint selects no service "
        "(assembler then invokes every service)"
    )
    assert resolved_entry.selected_service == "Intgmain", (
        "the resolved entry program must select exactly the root service so "
        "callees run through service calls instead of top-level runners"
    )


def test_single_program_source_keeps_declared_value(service, call_chain_source):
    """With one program and no CALL edges the resolution is unambiguous."""
    solo = Path(tempfile.mkdtemp(prefix="entry-program-solo-"))
    try:
        shutil.copy(FIXTURE / "MAIN.cob", solo / "MAIN.cob")
        shutil.copy(FIXTURE / "CALC.cob", solo / "CALC.cob")
        shutil.copy(FIXTURE / "TAXREC.cpy", solo / "TAXREC.cpy")
        app = _app(service, solo, "Main")
        # INTGMAIN CALLs INTGCALC, so exactly one root exists.
        assert service._resolve_entry_program(app) == "INTGMAIN"
    finally:
        shutil.rmtree(solo, ignore_errors=True)


def test_discovery_failure_degrades_instead_of_raising(service):
    """A broken source tree must not fail the run from entry resolution."""
    app = _app(service, Path(tempfile.mkdtemp(prefix="entry-program-broken-")), "Main")
    resolved = service._resolve_entry_program(app)
    assert resolved == "Main"


def test_no_source_returns_declared_value(service):
    app = service.create_application(
        name="no-source", description="", workload_id="integrated",
        java_entrypoint="Main",
    )
    assert app.cobol_source_path is None
    assert service._resolve_entry_program(app) == "Main"