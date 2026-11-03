"""BL-074: ``link_with_cobol`` must produce precise, ambiguity-flagged edges.

Phase 5 §76 audit probe 10 (`%TEMP%\\opencode\\phase5\\probe_p5_r1.py`)
proved that the dataset↔file linker matched datasets to COBOL files by
loose bidirectional substring and kept only the **last** program for a
shared file name:

- DSN ``ORDER.INPUT`` linked to COBOL file ``DER.INPUT`` (phantom edge),
- in a file read by two programs the executed program's edge was
  overwritten by an unrelated program (wrong-target edge),
- nothing ever reported the ambiguity.

These edges feed the production dependency graph in ``api/ingestion.py``
L265-272, so the graph silently showed wrong customer-facing relations
(Phase 3's phantom-dependency class, BL-034, in the JCL↔COBOL linker).

Expected behavior: exact or qualified-tail matching (``DSN == file`` or
``DSN ends with ".file"``, case-insensitive), one edge per matching
program, ``resolution=AMBIGUOUS`` metadata when a file maps to more than
one program, and no substring phantoms.
"""

from __future__ import annotations

from engine.transformation.ir import (
    CobolApplication,
    CobolProgram,
    CobolProgramUnit,
    FileDependency,
    JclApplication,
)
from engine.transformation.jcl_discovery import JclDiscovery
from engine.transformation.jcl_parser import JclParser

DATASET_MATCH_JCL = """\
//LINKJOB JOB CLASS=A
//STEP01 EXEC PGM=PROG1
//INPUT DD DSN=ORDER.INPUT,DISP=SHR
//EXACT DD DSN=INPUT.DATA,DISP=SHR
//QUAL DD DSN=PAY.INPUT,DISP=SHR
"""


def _unit(program_id: str, *file_names: str) -> CobolProgramUnit:
    return CobolProgramUnit(
        program_id=program_id,
        source_path=f"{program_id}.cob",
        program=CobolProgram(program_id=program_id),
        file_dependencies=tuple(
            FileDependency(
                program_id=program_id,
                file_name=file_name,
                operation="READ",
                mode="INPUT",
            )
            for file_name in file_names
        ),
    )


def _link(jcl_source: str, *units: CobolProgramUnit) -> list:
    jcl_app = JclParser().parse_application({"l.jcl": jcl_source})
    cobol_app = CobolApplication(application_id="bl074", programs=units)
    linked = JclDiscovery().link_with_cobol(jcl_app, cobol_app)
    return [
        dep
        for dep in linked.dependencies
        if dep.dependency_type == "COBOL_FILE"
    ]


class TestSubstringPhantomsAreGone:
    def test_partial_substring_file_name_does_not_link(self) -> None:
        edges = _link(DATASET_MATCH_JCL, _unit("PROG1", "DER.INPUT"))
        phantom = [e for e in edges if e.source.endswith(".INPUT")]
        assert phantom == [], f"substring phantom edges: {phantom}"

    def test_non_boundary_qualifier_fragment_does_not_link(self) -> None:
        edges = _link(DATASET_MATCH_JCL, _unit("PROG1", "PUT.DAT"))
        assert edges == []

    def test_empty_file_name_never_matches_every_dataset(self) -> None:
        edges = _link(DATASET_MATCH_JCL, _unit("PROG1", ""))
        assert edges == []


class TestPreciseMatchesStillLink:
    def test_exact_dataset_equals_file_name_links(self) -> None:
        edges = _link(DATASET_MATCH_JCL, _unit("PROG1", "INPUT.DATA"))
        exact = [e for e in edges if e.target == "PROG1.INPUT.DATA"]
        assert len(exact) == 1
        assert exact[0].source == "LINKJOB.STEP01.EXACT"

    def test_dataset_qualifier_tail_equals_file_name_links(self) -> None:
        edges = _link(DATASET_MATCH_JCL, _unit("PROG1", "INPUT"))
        targets = {e.target for e in edges}
        assert "PROG1.INPUT" in targets

    def test_single_program_match_is_flagged_resolved(self) -> None:
        edges = _link(DATASET_MATCH_JCL, _unit("PROG1", "INPUT.DATA"))
        exact = [e for e in edges if e.target == "PROG1.INPUT.DATA"]
        assert "resolution=RESOLVED" in exact[0].metadata


class TestSharedFilesKeepEveryProgramAndFlagAmbiguity:
    SHARED_JCL = """\
//SHARED JOB CLASS=A
//STEP01 EXEC PGM=PROG1
//MASTER DD DSN=MASTER.DATA,DISP=SHR
"""

    def test_every_program_declaring_the_file_gets_an_edge(self) -> None:
        edges = _link(
            self.SHARED_JCL,
            _unit("PROG1", "MASTER.DATA"),
            _unit("PROG2", "MASTER.DATA"),
            _unit("PROG3", "OTHER.DATA"),
        )
        targets = sorted(e.target for e in edges)
        assert targets == ["PROG1.MASTER.DATA", "PROG2.MASTER.DATA"]

    def test_ambiguity_is_reported_in_edge_metadata(self) -> None:
        edges = _link(
            self.SHARED_JCL,
            _unit("PROG1", "MASTER.DATA"),
            _unit("PROG2", "MASTER.DATA"),
        )
        assert len(edges) == 2
        for edge in edges:
            assert "resolution=AMBIGUOUS" in edge.metadata
            assert "dsn=MASTER.DATA" in edge.metadata

    def test_unrelated_programs_do_not_receive_edges(self) -> None:
        edges = _link(
            self.SHARED_JCL,
            _unit("PROG1", "MASTER.DATA"),
            _unit("PROG2", "DER.INPUT"),
        )
        assert [e.target for e in edges] == ["PROG1.MASTER.DATA"]
