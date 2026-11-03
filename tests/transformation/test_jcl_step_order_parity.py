"""BL-076: step-order edges must agree across the two dependency lanes.

Phase 5 §76 audit probe 9 (`%TEMP%\\opencode\\phase5\\probe_p5_r1.py`) proved
the two lanes of the JCL dependency graph disagree after a COND step:

- the semantic builder (`engine/jcl/builder.py::_build_step_dependencies`)
  emits the edge into the semantic model, carrying the control metadata;
- the application graph (`build_all_dependencies`, published by
  `api/ingestion.py` as `JCL_STEP_ORDER`) silently omits it because
  `build_all_dependencies` skips the pair when the *current* step carries
  a condition.

The result: the production ingestion graph loses ordering information
exactly for conditional workloads, with no diagnostic — a §54 silent-loss
class divergence between two representations of the same source.

Expected behavior: both lanes emit the same step-order pairs; the
application-graph edge carries the condition in its metadata so the
conditional semantics stay visible and honest.
"""

from __future__ import annotations

from engine.jcl.builder import JclSemanticBuilder
from engine.transformation.jcl_parser import JclParser

COND_SOURCE = """\
//CONDJOB JOB CLASS=A
//STEP01 EXEC PGM=PROGRAM-A
//STEP02 EXEC PGM=PROGRAM-B,COND=(0,NE)
//STEP03 EXEC PGM=PROGRAM-C
"""

LINEAR_SOURCE = """\
//LINJOB JOB CLASS=A
//STEP01 EXEC PGM=PROGRAM-A
//STEP02 EXEC PGM=PROGRAM-B
//STEP03 EXEC PGM=PROGRAM-C
"""


def _order_edges(app) -> set[tuple[str, str, str]]:
    return {
        (dep.source, dep.target, dep.metadata)
        for dep in app.dependencies
        if dep.dependency_type == "JCL_STEP_ORDER"
    }


class TestCondStepsKeepTheirStepOrderEdge:
    def test_step_order_edge_after_a_cond_step_is_present(self) -> None:
        app = JclParser().parse_application({"c.jcl": COND_SOURCE})
        pairs = {(s, t) for s, t, _ in _order_edges(app)}
        assert pairs == {
            ("STEP01", "STEP02"),
            ("STEP02", "STEP03"),
        }

    def test_cond_step_edge_metadata_names_the_condition(self) -> None:
        app = JclParser().parse_application({"c.jcl": COND_SOURCE})
        cond_edges = [
            (s, t, m) for s, t, m in _order_edges(app) if s == "STEP02"
        ]
        assert len(cond_edges) == 1
        assert "cond=(0,NE)" in cond_edges[0][2]

    def test_unconditional_edges_carry_no_cond_metadata(self) -> None:
        app = JclParser().parse_application({"c.jcl": COND_SOURCE})
        plain = next(m for s, _t, m in _order_edges(app) if s == "STEP01")
        assert "cond=" not in plain


class TestLaneParity:
    def test_application_and_semantic_lanes_emit_the_same_step_pairs(
        self,
    ) -> None:
        app = JclParser().parse_application({"c.jcl": COND_SOURCE})
        app_pairs = {
            (s.lower(), t.lower()) for s, t, _ in _order_edges(app)
        }

        model = JclSemanticBuilder().build(app, {"c.jcl": COND_SOURCE})
        semantic_pairs = {
            (d.source.lower(), d.target.lower())
            for job in model.jobs
            for d in job.dependencies
            if d.source  # entry edge (job -> first step) is not a pair
        }
        assert app_pairs == semantic_pairs


class TestUnchangedBehavior:
    def test_linear_chain_keeps_its_two_plain_order_edges(self) -> None:
        app = JclParser().parse_application({"l.jcl": LINEAR_SOURCE})
        assert _order_edges(app) == {
            ("STEP01", "STEP02", "job=LINJOB"),
            ("STEP02", "STEP03", "job=LINJOB"),
        }

    def test_single_step_job_has_no_step_order_edges(self) -> None:
        app = JclParser().parse_application(
            {"one.jcl": "//ONEJOB JOB CLASS=A\n//S1 EXEC PGM=A\n"}
        )
        assert _order_edges(app) == set()
