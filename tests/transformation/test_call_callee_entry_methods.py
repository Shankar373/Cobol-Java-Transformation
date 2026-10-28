"""CALL callee entry-method emission — duplicate-method regression.

Pinned defect (fixed in ``engine/transformation/cobol_to_java_mapping.py``):
every LINKAGE callee class received BOTH a method per COBOL paragraph AND a
static entry ``MAIN_LOGIC`` whose body re-inlined the driver paragraph.
When the callee's driver paragraph was itself named ``MAIN-LOGIC`` (the
commonest style for small called programs), the class declared
``MAIN_LOGIC`` twice and the Spring project **did not compile**. The defect
was latent-but-compilable for callees whose paragraph names differed from
the entry (e.g. ``MID-PARA``), where it produced a redundant duplicate body
instead of a compile error.

Pinned contract:

* a LINKAGE callee declares each method name exactly once;
* the caller-facing static entry ``MAIN_LOGIC`` always exists (the CALL
  lowering resolves every static LINKAGE target to it);
* a paragraph of a LINKAGE program whose Java name would collide with the
  entry is emitted as ``PARA_MAIN_LOGIC`` — at the definition *and* at every
  PERFORM / THRU call site, so targets still resolve;
* programs without a LINKAGE SECTION keep their paragraph names unchanged
  (``MAIN-LOGIC`` → ``MAIN_LOGIC``), so the rule never over-applies.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
from engine.transformation.cobol_parser import CobolParser
from engine.transformation.java_to_spring_mapping import (
    map_java_application_to_spring_boot,
)
from engine.transformation.cobol_to_java_mapping import (
    _paragraph_method_name,
    map_cobol_program_to_java,
)
from engine.transformation.spring_boot_generator import SpringBootGenerator

FIXTURES = Path("fixtures")

MODE_DIRS = ("workload-by-reference", "workload-by-content", "workload-by-value")

_METHOD_RE = re.compile(r"public (?:static )?void (\w+)\(")


def _modify_source(fixture: str) -> str:
    cobol_dir = FIXTURES / fixture / "cobol"
    app = ApplicationDiscovery().discover(
        str(cobol_dir), application_id=f"regression-{fixture}"
    )
    gen = ApplicationGenerator().generate(
        app, entrypoint="Main", source_root=cobol_dir
    )
    assert gen.success, gen.errors
    spring = map_java_application_to_spring_boot(
        gen.java_application, entry_program="Main", copybook_models=gen.copybook_models
    )
    files = SpringBootGenerator().generate_project(spring)
    return next(f.source_code for f in files if f.path.endswith("Modify.java"))


def _main_source(fixture: str) -> str:
    cobol_dir = FIXTURES / fixture / "cobol"
    app = ApplicationDiscovery().discover(
        str(cobol_dir), application_id=f"regression-{fixture}"
    )
    gen = ApplicationGenerator().generate(
        app, entrypoint="Main", source_root=cobol_dir
    )
    assert gen.success, gen.errors
    spring = map_java_application_to_spring_boot(
        gen.java_application, entry_program="Main", copybook_models=gen.copybook_models
    )
    files = SpringBootGenerator().generate_project(spring)
    return next(f.source_code for f in files if f.path.endswith("service/Main.java"))


@pytest.mark.parametrize("fixture", MODE_DIRS)
def test_callee_declares_every_method_exactly_once(fixture):
    """The pre-fix code emitted MAIN_LOGIC twice for MODIFY → javac error."""
    source = _modify_source(fixture)
    methods = _METHOD_RE.findall(source)
    assert len(methods) == len(set(methods)), (
        f"duplicated method(s) in Modify.java for {fixture}: {methods}"
    )


@pytest.mark.parametrize("fixture", MODE_DIRS)
def test_callee_keeps_static_entry_and_renames_colliding_paragraph(fixture):
    source = _modify_source(fixture)
    methods = _METHOD_RE.findall(source)
    assert methods.count("MAIN_LOGIC") == 1, methods
    assert "PARA_MAIN_LOGIC" in methods, methods


@pytest.mark.parametrize("fixture", MODE_DIRS)
def test_caller_resolves_to_the_static_entry(fixture):
    source = _main_source(fixture)
    assert "modify.MAIN_LOGIC();" in source


def test_perform_target_resolves_to_renamed_paragraph(tmp_path):
    """PERFORM of a MAIN-LOGIC paragraph inside a LINKAGE program must call
    the renamed paragraph method, not the entry."""
    (tmp_path / "CALLEE.cob").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. CALLEE.\n"
        "       DATA DIVISION.\n"
        "       LINKAGE SECTION.\n"
        "       01  LS-X              PIC 9(4).\n"
        "       PROCEDURE DIVISION USING LS-X.\n"
        "       DRIVER.\n"
        "           PERFORM MAIN-LOGIC.\n"
        "           GOBACK.\n"
        "       MAIN-LOGIC.\n"
        "           ADD 1 TO LS-X.\n"
    )
    program = CobolParser().parse((tmp_path / "CALLEE.cob").read_text())
    java_program = map_cobol_program_to_java(program)
    names = [m.name for m in java_program.java_class.methods]
    assert len(names) == len(set(names)), names
    assert "PARA_MAIN_LOGIC" in names
    assert "MAIN_LOGIC" in names  # static entry still emitted for linkage
    body = next(m for m in java_program.java_class.methods if m.name == "DRIVER")
    called = [
        s.call.method_name
        for s in body.body_statements
        if hasattr(s, "call")
    ]
    assert called == ["PARA_MAIN_LOGIC"], called


def test_non_linkage_programs_keep_paragraph_names():
    """No LINKAGE SECTION → the rule must not rename MAIN-LOGIC."""
    program = CobolParser().parse(
        (FIXTURES / "workload-minimal" / "cobol" / "SIMPLE-CALC.cob").read_text()
    )
    assert not program.linkage_section
    assert _paragraph_method_name(program, "MAIN-LOGIC") == "MAIN_LOGIC"


def test_rule_is_scoped_to_linkage_programs():
    class _NoLinkage:
        linkage_section = ()

    class _WithLinkage:
        linkage_section = (object(),)

    assert _paragraph_method_name(_NoLinkage(), "MAIN-LOGIC") == "MAIN_LOGIC"
    assert _paragraph_method_name(_WithLinkage(), "MAIN-LOGIC") == "PARA_MAIN_LOGIC"
    # Other paragraph names are never touched.
    assert _paragraph_method_name(_WithLinkage(), "MID-PARA") == "MID_PARA"
    assert _paragraph_method_name(None, "MAIN-LOGIC") == "MAIN_LOGIC"
