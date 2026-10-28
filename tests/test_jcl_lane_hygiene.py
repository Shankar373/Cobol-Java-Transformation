"""BL-077: JCL lane hygiene — dead constructs are removed, not left to drift.

Phase 5 §76 audit (change-log (w)) recorded four dead code paths in the
JCL lane plus two stale documentation claims. Each removal is pinned here
so the dead construct cannot silently return:

(a) ``JclDD.sysin`` was never set by the parser (``DD *`` is handled via
    ``is_inline``), so the builder clause
    ``dd.name.upper() == "SYSIN" and dd.sysin`` was always False;
(b) ``JclParseError`` was never raised — the parser's contract is
    "unsupported constructs produce minimal IR without error";
(c) ``JclSemanticModel.unsupported_jobs`` was a documented no-op stub
    with zero callers (the profile diagnostics are the authoritative
    signal, as its own docstring said);
(d) ``JclDatasetFlow.disposition`` was never populated at construction
    and never read by any consumer.

The live behavior those dead paths shadowed (inline ``SYSIN DD *``
classification) is pinned by a control test.
"""

from __future__ import annotations

from engine.jcl.builder import JclSemanticBuilder
from engine.jcl.model import JclDatasetFlow, JclResourceKind, JclSemanticModel
from engine.transformation import jcl_parser
from engine.transformation.ir import JclDD
from engine.transformation.jcl_parser import JclParser


def test_jcl_dd_ir_no_longer_carries_the_never_set_sysin_flag() -> None:
    assert not hasattr(JclDD(name="X"), "sysin"), (
        "JclDD.sysin was dead (never set by the parser) and removed in BL-077"
    )


def test_jcl_parser_module_no_longer_exports_the_never_raised_parse_error() -> None:
    assert not hasattr(jcl_parser, "JclParseError"), (
        "JclParseError was never raised (parser fails soft by design) "
        "and removed in BL-077"
    )


def test_semantic_model_no_longer_carries_the_no_op_unsupported_jobs_stub() -> None:
    assert not hasattr(JclSemanticModel(), "unsupported_jobs"), (
        "JclSemanticModel.unsupported_jobs was a no-op stub with zero "
        "callers and removed in BL-077"
    )


def test_dataset_flow_no_longer_carries_the_never_populated_disposition_field() -> None:
    flow = JclDatasetFlow(job="J", dataset="D", producer="S", consumers=())
    assert not hasattr(flow, "disposition"), (
        "JclDatasetFlow.disposition was never populated or read and "
        "removed in BL-077"
    )


def test_inline_sysin_dd_is_still_classified_as_sysin_inline() -> None:
    """Control: the live ``is_inline`` branch survives the dead-code removal."""
    source = (
        "//SYSJOB JOB CLASS=A\n"
        "//STEP01 EXEC PGM=MAIN\n"
        "//SYSIN DD *\n"
        "some data\n"
    )
    app = JclParser().parse_application({"s.jcl": source})
    model = JclSemanticBuilder().build(app, {"s.jcl": source})
    kinds = {
        r.kind
        for job in model.jobs
        for step in job.steps
        for r in step.resources
    }
    assert JclResourceKind.SYSIN_INLINE in kinds
