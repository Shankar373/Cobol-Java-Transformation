"""Layer 4 (P1): the ``DialectProfile`` — frozen, deterministic, order-independent, surfaced in report and API.

Acceptance contract: ``docs/discovery/DIALECT_PARSER_FRONTEND_AUDIT.md`` (criteria 1 and the P1 record
requirements); layer ownership: ``docs/architecture/LAYER_MODEL.md`` contract 3.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from enterprise.discovery.classify import classify
from enterprise.discovery.compilers import ToolchainConfig, std_for_dialect
from enterprise.discovery.discover import DiscoveryRequest, discover, scan_file
from enterprise.discovery.dialect_profile import (
    BASIS,
    ORACLE_TOOL,
    PROFILE_SCHEMA,
    build_profiles,
    canonical_json,
)
from enterprise.discovery.resolve import build_graph
from enterprise.discovery.runtime_deps import dialect_report
from tests.discovery.helpers import COBOL_ESTATE, _fixed
from tests.discovery.test_api import client, estate_zip, service, submit, wait  # noqa: F401 - fixtures
from tests.discovery.test_compilers_applications import FakeCobc, records
from tests.discovery.test_resolve_graph import program


def _ids(profiles) -> dict[str, str]:
    return {profile.file: profile.profile_id for profile in profiles}


# --- determinism and identity ----------------------------------------------------------------------------------------

def test_profile_is_frozen_and_profile_id_hashes_every_other_field() -> None:
    (profile,) = build_records({"src/P.cbl": program("P")})
    with pytest.raises(Exception):
        profile.dialect = "ibm-enterprise"  # type: ignore[misc]
    assert profile.profile_id == hashlib.sha256(canonical_json(profile).encode("utf-8")).hexdigest()
    assert len(profile.profile_id) == 64
    payload = profile.as_dict()
    assert payload["schema"] == PROFILE_SCHEMA and payload["oracle"]["tool"] == ORACLE_TOOL
    # The id covers every field: a payload without the id must be exactly what was hashed.
    assert "profile_id" not in json.loads(canonical_json(profile))


def build_records(files: dict[str, str]):
    return build_profiles(records(files))


def test_profiles_are_order_independent_and_byte_deterministic() -> None:
    files = {
        "src/A.cbl": program("A", "EXEC CICS LINK PROGRAM('B') END-EXEC."),
        "src/B.cbl": program("B"),
        "cpy/C.cpy": _fixed("05  C-FLAG PIC X."),
    }
    forward = build_records(files)
    backward = build_records(dict(reversed(list(files.items()))))
    assert _ids(forward) == _ids(backward)
    assert [canonical_json(p) for p in forward] == [canonical_json(p) for p in backward]
    # A second scan of the same bytes yields the same ids.
    assert _ids(build_records(files)) == _ids(forward)
    assert [p.file for p in forward] == ["cpy/C.cpy", "src/A.cbl", "src/B.cbl"]  # sorted by path


def test_a_byte_change_changes_only_that_file_profile() -> None:
    files = {"src/A.cbl": program("A"), "src/B.cbl": program("B")}
    before = _ids(build_records(files))
    changed = dict(files)
    changed["src/A.cbl"] = program("A", "DISPLAY 'X'.")
    after = _ids(build_records(changed))
    assert after["src/A.cbl"] != before["src/A.cbl"]
    assert after["src/B.cbl"] == before["src/B.cbl"]


# --- feeds: dialect evidence, single reader, std mapping ---------------------------------------------------------------

def test_profile_basis_is_the_report_basis_verbatim() -> None:
    recs = records({"src/P.cbl": program("P")})
    (profile,) = build_profiles(recs, dialect_report_result=dialect_report(recs))
    assert profile.basis == BASIS == dialect_report(recs)["basis"]


def test_std_mapping_and_oracle_fields_come_from_the_authority() -> None:
    assert std_for_dialect("ibm-enterprise") == "ibm"
    assert std_for_dialect("microfocus") == "mf"
    assert std_for_dialect("legacy-cobol74") == "cobol85"
    assert std_for_dialect("") == std_for_dialect("anything-unknown") == "default"

    ibm = build_records({"src/I.cbl": "CBL ARITH(EXTEND)\n" + program("I", "EXEC SQL SELECT 1 END-EXEC.")})[0]
    assert ibm.dialect == "ibm-enterprise" and ibm.confidence == "indicative"
    assert ibm.oracle_std == "ibm" and ibm.oracle_format == "-fixed"
    assert "ARITH(EXTEND)" in ibm.compiler_options

    plain = build_records({"src/P.cbl": program("P")})[0]
    assert plain.dialect == "undetermined" and plain.confidence == "undetermined"
    assert plain.oracle_std == "default"

    free = build_records({"src/F.cbl": "       PROGRAM-ID. F.\n       PROCEDURE DIVISION.\n       GOBACK.\n"})[0]
    assert free.reference_format == "fixed" and free.oracle_format == "-fixed"  # -free only for a wholly free file


def test_reference_format_switches_are_recorded_from_the_single_reader() -> None:
    text = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. MIXED.\n>>SOURCE FORMAT FREE\nPROCEDURE DIVISION.\nGOBACK.\n"
    (profile,) = build_records({"src/M.cbl": text})
    assert profile.reference_format == "mixed"
    assert (3, "free") in profile.format_switches
    assert profile.oracle_format == ""  # not attributable to one flag: never a silent fixed/free read
    assert profile.directives and profile.directives[0][0] == 3


def test_variable_sourceformat_is_refused_by_name_never_a_silent_fixed_read() -> None:
    text = '$SET SOURCEFORMAT"VARIABLE"\n' + program("V")
    scan = scan_file("src/V.cbl", "cobol", text)
    assert scan is not None and scan.source_format == "variable"
    assert any(p.code == "REFERENCE_FORMAT_VARIABLE_UNSUPPORTED" for p in scan.problems)
    (profile,) = build_records({"src/V.cbl": text})
    assert profile.reference_format == "variable"
    assert "REFERENCE_FORMAT_VARIABLE_UNSUPPORTED" in profile.unsupported
    assert profile.oracle_format == ""


def test_directive_state_and_unsupported_construct_names() -> None:
    # A documented >>DEFINE set the reader can evaluate: gated, not refused (criterion 5).
    conditional = build_records({"src/C.cbl": ">>DEFINE X AS 1\n" + program("C")})[0]
    assert conditional.directive_state == "evaluated"
    assert "CONDITIONAL_COMPILATION_UNEVALUATED" not in conditional.unsupported

    # A condition on a name nobody defines cannot be decided: refused by name, both branches kept.
    undecided = build_records({"src/U.cbl": ">>IF X = 1\n" + program("U")})[0]
    assert undecided.directive_state == "unevaluated"
    assert "CONDITIONAL_COMPILATION_UNEVALUATED" in undecided.unsupported

    plain = build_records({"src/P.cbl": program("P")})[0]
    assert plain.directive_state == "none" and plain.unsupported == ()

    oo = build_records({"src/O.cbl": _fixed("IDENTIFICATION DIVISION.", "CLASS-ID. HELLO.", "END CLASS HELLO.")})[0]
    assert oo.dialect == "object-oriented-cobol"
    assert "OO_COBOL_UNSUPPORTED" in oo.unsupported

    screen = build_records({"src/S.cbl": _fixed(
        "IDENTIFICATION DIVISION.", "PROGRAM-ID. S.", "DATA DIVISION.", "WORKING-STORAGE SECTION.",
        "SCREEN SECTION.", "01 SCR.", "05 F1 PIC X.", "PROCEDURE DIVISION.", "GOBACK.")})[0]
    assert "SCREEN_SECTION_UNSUPPORTED" in screen.unsupported


# --- criterion 7: the estate's JCL names its compiler ------------------------------------------------------------------

def test_a_jcl_compile_step_names_the_dialect_of_the_program_it_compiles() -> None:
    """Criterion 7: ``EXEC PGM=ELAXF`` + its SYSIN member decide ``primary`` for that program.

    The compiler name is observed in the JCL and joined to the program through the member the
    compile step actually reads; a step without a observed compiler name contributes nothing.
    """
    files = {
        "src/PAYROLL.cbl": program("PAYROLL"),
        "jcl/BUILD.jcl": "//B JOB\n//C EXEC PGM=ELAXF\n//SYSIN DD DSN=PROD.SRC(PAYROLL),DISP=SHR\n",
    }
    report = dialect_report(records(files))
    entry = next(e for e in report["files"] if e["file"] == "src/PAYROLL.cbl")
    assert entry["primary"] == "microfocus"
    micro = next(c for c in entry["candidates"] if c["dialect"] == "microfocus")
    signal = micro["examples"][0]["signal"]
    assert "ELAXF" in signal and "jcl/BUILD.jcl" in signal  # the evidence names its source


def test_a_data_item_named_like_a_signal_is_not_vendor_evidence() -> None:
    """Criterion 7 second half: ``05 JSON PIC X`` declares a data-name; it proves no dialect."""
    text = _fixed("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                  "WORKING-STORAGE SECTION.", "05 JSON PIC X.", "PROCEDURE DIVISION.", "GOBACK.")
    scan = scan_file("src/P.cbl", "cobol", text)
    assert scan is not None
    assert not [f for f in scan.facts if f.category == "dialect-signal" and f.name == "JSON"]
    (entry,) = dialect_report(records({"src/P.cbl": text}))["files"]
    assert entry["primary"] == "undetermined"


# --- surfacing: report["dialects"] and the API ------------------------------------------------------------------------

def test_report_dialects_gains_profiles_additively(tmp_path) -> None:
    source = tmp_path / "estate"
    for name, text in COBOL_ESTATE.items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def run(store_name: str) -> dict:
        return discover(
            DiscoveryRequest("directory", str(source)), tmp_path / store_name,
            toolchain=ToolchainConfig(backend="local", runner=FakeCobc(),
                                      which=lambda name: "/fake/cobc" if name == "cobc" else None),
        ).report

    report = run("store")
    dialects = report["dialects"]
    # Additive: every pre-existing key is still there, verbatim.
    assert {"basis", "files", "summary", "undetermined_files"} <= set(dialects)
    profiles = dialects["profiles"]
    assert profiles, "profiles must be surfaced in report['dialects']"
    for payload in profiles:
        assert payload["schema"] == PROFILE_SCHEMA
        assert len(payload["profile_id"]) == 64
        assert payload["oracle"]["tool"] == ORACLE_TOOL
    # The report is a pure function of the checkpoint: a second run gives byte-identical profile JSON.
    again = run("store2")
    assert json.dumps(again["dialects"]["profiles"], sort_keys=True) == json.dumps(profiles, sort_keys=True)


def test_profiles_surface_through_the_api(client: TestClient, service) -> None:  # noqa: F811 - fixtures
    run = wait(client, submit(client, estate_zip()).json()["run_id"])
    report = client.get(f"/discovery/runs/{run['run_id']}/report").json()
    profiles = report["dialects"]["profiles"]
    assert profiles, "the API report must carry the per-file profiles"
    inventory = {f["path"] for f in client.get(f"/discovery/runs/{run['run_id']}/inventory").json()["files"]}
    assert {p["file"] for p in profiles} <= inventory
    assert all(p["schema"] == PROFILE_SCHEMA and len(p["profile_id"]) == 64 for p in profiles)


# --- library order (contract 3 feed) ----------------------------------------------------------------------------------

def test_library_order_comes_from_compile_include_order_or_jcllib() -> None:
    with_include = records({
        "build/Makefile": "all:\n\tcobc -I cpy src/P.cbl\n",
        "src/P.cbl": program("P"),
        "cpy/C.cpy": _fixed("05 C PIC X."),
    })
    build = build_graph(with_include)
    profile = {p.file: p for p in build_profiles(with_include, build=build)}["src/P.cbl"]
    assert profile.library_order and profile.library_order[0] == "cpy"

    jcl_records = records({
        "src/P.cbl": program("P", "COPY COMMON."),
        "jcl/J.jcl": "//J JOB\n//  JCLLIB ORDER=(PROD.PROCLIB,TEST.PROCLIB)\n//S1 EXEC PGM=IGYCRCTL\n",
    })
    build = build_graph(jcl_records)
    profile = {p.file: p for p in build_profiles(jcl_records, build=build)}["src/P.cbl"]
    assert list(profile.library_order) == ["PROD.PROCLIB", "TEST.PROCLIB"]
