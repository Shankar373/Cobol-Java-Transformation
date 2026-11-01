"""The oracle runs the program the candidate enters (Docker-free).

For a multi-program application the differential comparison is only
meaningful when GnuCOBOL executes the same entry program the generated
Spring Boot application enters.  The service resolves that program once
(``_resolve_entry_program``) and the pipeline hands it to the oracle; the
oracle never substitutes a program chosen by file order.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.domain.identities import VerdictState
from engine.pipeline import PipelineConfig, VerticalSlicePipeline
from tests.test_comparison_contract_strength import _Candidate, _Oracle

_DRIVER = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. ZDRIVER.\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    "           CALL 'CALLEE'.\n"
    "           STOP RUN.\n"
)
_CALLEE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. CALLEE.\n"
    "       PROCEDURE DIVISION.\n"
    "       CALLEE-PARA.\n"
    "           DISPLAY 'IN CALLEE'.\n"
    "           GOBACK.\n"
)


class _RecordingOracle(_Oracle):
    def __init__(self) -> None:
        super().__init__(b"HI\n", None, 0)
        self.calls: list[dict] = []

    def execute(self, run_id, source_path, input_data=None, input_files=None,
                **kwargs):
        self.calls.append(kwargs)
        return super().execute(run_id, source_path, input_data, input_files)


def _run(tmp_path: Path, entry: str | None):
    src = tmp_path / "src"
    src.mkdir()
    (src / "ZDRIVER.cob").write_text(_DRIVER, encoding="utf-8")
    (src / "CALLEE.cob").write_text(_CALLEE, encoding="utf-8")
    cand = tmp_path / "cand"
    cand.mkdir()
    (cand / "Main.java").write_text("class Main {}", encoding="utf-8")
    pipe = VerticalSlicePipeline(
        PipelineConfig(
            workload_id="wl-entry",
            cobol_source_path=str(src),
            java_candidate_path=str(cand),
            java_entrypoint="Main",
            oracle_entry_program=entry,
        ),
        candidate_adapter=_Candidate(b"HI\n", None, 0),
    )
    oracle = _RecordingOracle()
    pipe._oracle_adapter = oracle
    return pipe.run(), oracle


class TestPipelinePassesEntry:
    def test_configured_entry_reaches_oracle(self, tmp_path):
        result, oracle = _run(tmp_path, "ZDRIVER")
        assert oracle.calls == [{"entry_program": "ZDRIVER"}]
        assert result.verdict.state == VerdictState.VERIFIED

    def test_unset_entry_is_not_forwarded(self, tmp_path):
        _, oracle = _run(tmp_path, None)
        assert oracle.calls == [{}]


class TestServiceResolvesEntry:
    # api.service needs pydantic; imported lazily so the pytest-only
    # capability gate can still collect this module (it deselects this class).
    @staticmethod
    def _service():
        from api.service import Service
        return Service.__new__(Service)

    @staticmethod
    def _app(src: Path, declared: str = "Main"):
        return SimpleNamespace(
            id="app-entry", name="entry", workload_id="wl-entry",
            cobol_source_path=str(src), java_entrypoint=declared,
        )

    def test_uncalled_root_is_resolved(self, tmp_path):
        (tmp_path / "ZDRIVER.cob").write_text(_DRIVER, encoding="utf-8")
        (tmp_path / "CALLEE.cob").write_text(_CALLEE, encoding="utf-8")
        svc = self._service()
        assert svc._resolve_entry_program(self._app(tmp_path)) == "ZDRIVER"

    def test_validation_config_carries_resolved_entry(self, tmp_path, monkeypatch):
        (tmp_path / "ZDRIVER.cob").write_text(_DRIVER, encoding="utf-8")
        (tmp_path / "CALLEE.cob").write_text(_CALLEE, encoding="utf-8")
        captured: list[PipelineConfig] = []

        class _Stop(Exception):
            pass

        def _fake_pipeline(config, candidate_adapter=None):
            captured.append(config)
            raise _Stop

        monkeypatch.setattr("api.service.VerticalSlicePipeline", _fake_pipeline)
        svc = self._service()
        run = SimpleNamespace(certification_contract=None)
        with pytest.raises(_Stop):
            svc._run_validation(self._app(tmp_path), run, tmp_path, "Main", None)
        assert captured[0].oracle_entry_program == "ZDRIVER"
