"""BL-075: compound DD values (DISP=/SPACE=) must be kept verbatim.

Phase 5 §76 audit probe 6 (`%TEMP%\\opencode\\phase5\\probe_p5_r1.py`) proved
that `_parse_dd` splits DD parameters with a quote-aware but
paren-unaware comma split, so `DISP=(NEW,CATLG,DELETE)` is stored as
`"(NEW"` and `SPACE=(TRK,(10,5))` as `"(TRK"` — dataset lifecycle
detail (CATLG/DELETE/PASS) silently lost in the IR, the semantic model,
and the Spring Batch representation, with no diagnostic. The existing
test tolerated the truncation with the weak `assert "NEW" in
new_dd.disposition` (test_jcl_parser.py L340, strengthened alongside the
fix).

Expected behavior: parameter splitting respects parenthesis depth and
quotes (the JOB/EXEC parser `_parse_parameters` already does), so every
compound value round-trips verbatim; simple values and direction
derivation (first subfield drives NEW/SHR/MOD/OLD) are unchanged.
"""

from __future__ import annotations

from engine.jcl.builder import JclSemanticBuilder
from engine.transformation.jcl_consumer import modernize_jcl_from_sources
from engine.transformation.jcl_parser import JclParser

COMPOUND_SOURCE = """\
//CMPOBJ JOB CLASS=A
//STEP01 EXEC PGM=MAIN
//NEWFILE DD DSN=NEW.DATA,DISP=(NEW,CATLG,DELETE),SPACE=(TRK,(10,5))
//OLDFILE DD DSN=OLD.DATA,DISP=SHR
//OUTDD DD DISP=(SHR,KEEP),SPACE=(CYL,(5,10)),DSN=OUT.DATA
"""

QUOTED_SOURCE = """\
//QUOTJOB JOB CLASS=A
//STEP01 EXEC PGM=MAIN
//QDD DD DSN='PAY.DATA,TEMP',DISP=SHR
"""


class TestCompoundDDValuesAreKeptVerbatim:
    def test_compound_disposition_is_kept_verbatim(self) -> None:
        job = JclParser().parse(COMPOUND_SOURCE)
        dd = next(
            d for d in job.steps[0].dd_statements if d.name == "NEWFILE"
        )
        assert dd.disposition == "(NEW,CATLG,DELETE)"

    def test_nested_paren_space_value_is_kept_verbatim(self) -> None:
        job = JclParser().parse(COMPOUND_SOURCE)
        dd = next(
            d for d in job.steps[0].dd_statements if d.name == "NEWFILE"
        )
        assert dd.space == "(TRK,(10,5))"

    def test_compound_values_before_the_dsn_do_not_break_parameter_parsing(
        self,
    ) -> None:
        job = JclParser().parse(COMPOUND_SOURCE)
        dd = next(
            d for d in job.steps[0].dd_statements if d.name == "OUTDD"
        )
        assert dd.disposition == "(SHR,KEEP)"
        assert dd.space == "(CYL,(5,10))"
        assert dd.dataset == "OUT.DATA"

    def test_simple_values_are_unchanged(self) -> None:
        job = JclParser().parse(COMPOUND_SOURCE)
        dd = next(
            d for d in job.steps[0].dd_statements if d.name == "OLDFILE"
        )
        assert dd.disposition == "SHR"

    def test_quoted_commas_still_stay_in_one_parameter(self) -> None:
        job = JclParser().parse(QUOTED_SOURCE)
        dd = job.steps[0].dd_statements[0]
        assert dd.dataset == "PAY.DATA,TEMP"


class TestCompoundValuesFlowThroughTheLane:
    @staticmethod
    def _semantic_resource(name: str):
        app = JclParser().parse_application({"c.jcl": COMPOUND_SOURCE})
        model = JclSemanticBuilder().build(app, {"c.jcl": COMPOUND_SOURCE})
        return next(
            r
            for job in model.jobs
            for step in job.steps
            for r in step.resources
            if r.name == name
        )

    def test_semantic_resource_keeps_the_full_disposition(self) -> None:
        resource = self._semantic_resource("NEWFILE")
        assert resource.disposition == "(NEW,CATLG,DELETE)"

    def test_direction_is_still_derived_from_the_first_subfield(self) -> None:
        resource = self._semantic_resource("NEWFILE")
        assert resource.dataset_use.value == "OUTPUT"

    def test_spring_batch_resource_carries_the_full_disposition(self) -> None:
        result = modernize_jcl_from_sources(
            {"c.jcl": COMPOUND_SOURCE}, application_id="bl075"
        )
        resources = result.profile.application.resources
        newfile = next(r for r in resources if r.name == "NEWFILE")
        assert newfile.disposition == "(NEW,CATLG,DELETE)"
