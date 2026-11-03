"""Files written relative to the working directory are observable (Docker-free).

The execution lanes collect files left in the working directory as
``workspace/<path>`` (``engine.execution.workspace_files``).  The pipeline
compares those byte-exactly like any other generated file, except the
on-disk image of an INDEXED/RELATIVE file: the Java organisation is an
emulation, so that image is recorded as an INCONCLUSIVE comparison and the
run is PARTIAL — never VERIFIED on a file nobody compared.
"""

from __future__ import annotations

from pathlib import Path

from api.workload_contract import default_contract
from engine.domain.identities import VerdictState
from engine.evidence.integrity import EvidenceIntegrityValidator, ValidatedEvidenceManifest
from engine.execution.workspace_files import collect_generated_files
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from tests.test_comparison_contract_strength import _Candidate, _Oracle

_INDEXED = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. MAIN.\n"
    "       ENVIRONMENT DIVISION.\n"
    "       INPUT-OUTPUT SECTION.\n"
    "       FILE-CONTROL.\n"
    '           SELECT IDX-FILE ASSIGN TO "IDX.DAT"\n'
    "               ORGANIZATION IS INDEXED\n"
    "               RECORD KEY IS IDX-KEY.\n"
    "       PROCEDURE DIVISION.\n"
    "           DISPLAY 'HI'.\n"
    "           STOP RUN.\n"
)
_SEQUENTIAL = _INDEXED.replace(
    "               ORGANIZATION IS INDEXED\n               RECORD KEY IS IDX-KEY.\n",
    "               ORGANIZATION IS LINE SEQUENTIAL.\n",
)


def _run(tmp_path: Path, source: str, oracle_files, candidate_files):
    src = tmp_path / "MAIN.cob"
    src.write_text(source, encoding="latin-1")
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
    pipe = VerticalSlicePipeline(
        PipelineConfig(
            workload_id="wl-ws",
            cobol_source_path=str(src),
            java_candidate_path=str(cand),
            java_entrypoint="Main",
            workload=default_contract("wl-ws").workload,
        ),
        candidate_adapter=_Candidate(b"HI\n", candidate_files, 0),
    )
    pipe._oracle_adapter = _Oracle(b"HI\n", oracle_files, 0)
    return pipe.run()


def _file_results(result) -> dict[str, str]:
    return {
        c.comparison_id.split(":", 1)[1].rsplit("-run-", 1)[0]: c.result
        for c in result.comparison_evidence
        if c.comparison_id.startswith("comp-generated-file:")
    }


class TestCollection:
    def test_working_directory_files_are_collected_with_prefix(self, tmp_path):
        out = tmp_path / "output"
        ws = tmp_path / "ws"
        (ws / "jars").mkdir(parents=True)
        out.mkdir()
        (out / "report.txt").write_bytes(b"R")
        (ws / "IDX.DAT").write_bytes(b"I")
        (ws / "sub").mkdir()
        (ws / "sub" / "x.txt").write_bytes(b"X")
        (ws / "jars" / "app.jar").write_bytes(b"J")
        files = collect_generated_files(out, ws, ("jars", "output"))
        assert files == {
            "report.txt": b"R",
            "workspace/IDX.DAT": b"I",
            "workspace/sub/x.txt": b"X",
        }

    def test_nested_output_files_with_one_name_do_not_collide(self, tmp_path):
        # Audit V8: output files were keyed by base name, so a/x.txt and
        # b/x.txt collided and one of them was never compared.
        out = tmp_path / "output"
        (out / "a").mkdir(parents=True)
        (out / "b").mkdir()
        (out / "a" / "x.txt").write_bytes(b"A")
        (out / "b" / "x.txt").write_bytes(b"B")
        (out / "top.txt").write_bytes(b"T")
        files = collect_generated_files(out, None)
        assert files == {"a/x.txt": b"A", "b/x.txt": b"B", "top.txt": b"T"}


class TestComparison:
    def test_differing_sequential_workspace_file_fails(self, tmp_path):
        result = _run(tmp_path, _SEQUENTIAL,
                      {"workspace/IDX.DAT": b"A\n"}, {"workspace/IDX.DAT": b"B\n"})
        assert _file_results(result) == {"workspace/IDX.DAT": "MISMATCH"}
        assert result.verdict.state == VerdictState.FAILED

    def test_identical_sequential_workspace_file_verifies(self, tmp_path):
        result = _run(tmp_path, _SEQUENTIAL,
                      {"workspace/IDX.DAT": b"A\n"}, {"workspace/IDX.DAT": b"A\n"})
        assert _file_results(result) == {"workspace/IDX.DAT": "MATCH"}
        assert result.verdict.state == VerdictState.VERIFIED

    def test_indexed_file_image_is_inconclusive_not_verified(self, tmp_path):
        result = _run(tmp_path, _INDEXED,
                      {"workspace/IDX.DAT": b"bdb-image"},
                      {"workspace/IDX.DAT.idx": b"emulated-image"})
        assert _file_results(result) == {
            "workspace/IDX.DAT": "INCONCLUSIVE",
            "workspace/IDX.DAT.idx": "INCONCLUSIVE",
        }
        assert result.verdict.state == VerdictState.PARTIAL
        validated = EvidenceIntegrityValidator().validate(result.evidence_manifest)
        assert isinstance(validated, ValidatedEvidenceManifest)
