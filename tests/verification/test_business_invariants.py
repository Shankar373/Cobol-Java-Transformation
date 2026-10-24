"""Business invariants: exact evaluation, canonical reports, fail-closed admission."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from engine.verification.business_invariants import (
    BusinessInvariant,
    InvariantKind,
    InvariantObservation,
    InvariantPhase,
    InvariantSource,
    admit_report,
    build_report,
    evaluate_invariants,
    invariant_definition_digest,
)


def _invariant(kind: InvariantKind, **kwargs) -> BusinessInvariant:
    kwargs.setdefault("invariant_id", "inv-1")
    kwargs.setdefault("source", InvariantSource.STDOUT)
    return BusinessInvariant(kind=kind, **kwargs)


def _report(invariants, observation):
    return build_report(invariants, observation)


class TestExactLines:
    def test_exact_sequence_passes_and_crlf_is_a_line_break(self) -> None:
        invariant = _invariant(
            InvariantKind.EXACT_LINES,
            expected=("ALPHA", "BETA"),
            phase=InvariantPhase.POSTCONDITION,
        )
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(exit_code=0, stdout=b"ALPHA\r\nBETA\r\n"),
        )[0]
        assert outcome.passed
        assert outcome.observed == ["ALPHA", "BETA"]

    def test_line_order_and_content_are_exact(self) -> None:
        invariant = _invariant(
            InvariantKind.EXACT_LINES, expected=("ALPHA", "BETA")
        )
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(exit_code=0, stdout=b"BETA\nALPHA\n"),
        )[0]
        assert not outcome.passed

    def test_empty_output_is_zero_lines_not_a_vacuous_match(self) -> None:
        invariant = _invariant(InvariantKind.LINE_COUNT, expected=0)
        assert evaluate_invariants(
            (invariant,), InvariantObservation(exit_code=0, stdout=b"")
        )[0].passed

        exact = _invariant(
            InvariantKind.EXACT_LINES, expected=("ALPHA",)
        )
        assert not evaluate_invariants(
            (exact,), InvariantObservation(exit_code=0, stdout=b"")
        )[0].passed

    def test_invalid_utf8_is_rejected_not_decoded_lossily(self) -> None:
        invariant = _invariant(
            InvariantKind.EXACT_LINES, expected=("ALPHA",)
        )
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(exit_code=0, stdout=b"\xff\xfe"),
        )[0]
        assert not outcome.passed
        assert "UTF-8" in outcome.reason

    def test_stderr_error_behaviour_source(self) -> None:
        invariant = _invariant(
            InvariantKind.EXACT_LINES,
            source=InvariantSource.STDERR,
            expected=("INVALID ACCOUNT",),
            phase=InvariantPhase.ERROR_BEHAVIOR,
        )
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=8, stdout=b"", stderr=b"INVALID ACCOUNT\n"
            ),
        )[0]
        assert outcome.passed
        assert outcome.phase is InvariantPhase.ERROR_BEHAVIOR


class TestExitAndCounts:
    def test_exit_code_exact(self) -> None:
        invariant = _invariant(
            InvariantKind.EXIT_CODE, source=InvariantSource.EXIT_STATUS,
            expected=8,
        )
        assert evaluate_invariants(
            (invariant,), InvariantObservation(exit_code=8)
        )[0].passed
        assert not evaluate_invariants(
            (invariant,), InvariantObservation(exit_code=0)
        )[0].passed

    def test_missing_exit_code_fails(self) -> None:
        invariant = _invariant(
            InvariantKind.EXIT_CODE, source=InvariantSource.EXIT_STATUS,
            expected=0,
        )
        outcome = evaluate_invariants(
            (invariant,), InvariantObservation(exit_code=None)
        )[0]
        assert not outcome.passed

    def test_record_count_exact(self) -> None:
        invariant = _invariant(
            InvariantKind.RECORD_COUNT,
            source=InvariantSource.FILE,
            source_name="out.dat",
            expected=2,
            record_length=4,
        )
        assert evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0, files={"out.dat": b"AAAABBBB"}
            ),
        )[0].passed

    def test_partial_trailing_record_fails_record_count(self) -> None:
        invariant = _invariant(
            InvariantKind.RECORD_COUNT,
            source=InvariantSource.FILE,
            source_name="out.dat",
            expected=2,
            record_length=4,
        )
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0, files={"out.dat": b"AAAABBBBCC"}
            ),
        )[0]
        assert not outcome.passed
        assert "not divisible" in outcome.reason

    def test_missing_declared_file_fails(self) -> None:
        invariant = _invariant(
            InvariantKind.RECORD_COUNT,
            source=InvariantSource.FILE,
            source_name="out.dat",
            expected=0,
            record_length=4,
        )
        outcome = evaluate_invariants(
            (invariant,), InvariantObservation(exit_code=0, files={})
        )[0]
        assert not outcome.passed
        assert outcome.observed == "MISSING"


class TestFixedFields:
    def _equals(self, **kwargs) -> BusinessInvariant:
        values = dict(
            kind=InvariantKind.FIXED_FIELD_EQUALS,
            source=InvariantSource.FILE,
            source_name="out.dat",
            expected=b"AB",
            record_length=4,
            offset=1,
            length=2,
        )
        values.update(kwargs)
        return BusinessInvariant(invariant_id="fixed", **values)

    def test_all_records_must_match(self) -> None:
        invariant = self._equals()
        passing = evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0, files={"out.dat": b"XABYXABY"}
            ),
        )[0]
        assert passing.passed
        failing = evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0, files={"out.dat": b"XABYZZZZ"}
            ),
        )[0]
        assert not failing.passed
        assert failing.observed["mismatched"] == [1]

    def test_record_index_selects_one_record(self) -> None:
        invariant = self._equals(record_index=1)
        assert evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0, files={"out.dat": b"ZZZZXABY"}
            ),
        )[0].passed
        assert not evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0, files={"out.dat": b"XABYZZZZ"}
            ),
        )[0].passed

    def test_out_of_range_record_index_fails(self) -> None:
        invariant = self._equals(record_index=5)
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(exit_code=0, files={"out.dat": b"XABY"}),
        )[0]
        assert not outcome.passed
        assert "out of range" in outcome.reason

    def test_trailing_partial_record_fails_even_if_records_match(self) -> None:
        invariant = self._equals()
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0, files={"out.dat": b"XABYQ"}
            ),
        )[0]
        assert not outcome.passed
        assert "not divisible" in outcome.reason

    def test_total_is_exact_decimal(self) -> None:
        invariant = BusinessInvariant(
            invariant_id="total",
            kind=InvariantKind.FIXED_FIELD_TOTAL,
            source=InvariantSource.FILE,
            source_name="out.dat",
            expected="604.56",
            record_length=6,
            offset=0,
            length=6,
            decimal_places=2,
        )
        content = b"010000020000030456"  # 100.00 + 200.00 + 304.56
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(exit_code=0, files={"out.dat": content}),
        )[0]
        assert outcome.passed
        assert outcome.observed == {"$decimal": "604.56"}

    def test_total_mismatch_is_exact_not_rounded(self) -> None:
        invariant = BusinessInvariant(
            invariant_id="total",
            kind=InvariantKind.FIXED_FIELD_TOTAL,
            source=InvariantSource.FILE,
            source_name="out.dat",
            expected="0.31",
            record_length=2,
            offset=0,
            length=2,
            decimal_places=2,
        )
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(exit_code=0, files={"out.dat": b"1020"}),
        )[0]
        assert not outcome.passed
        assert outcome.observed == {"$decimal": "0.3"}

    def test_non_numeric_field_fails_closed(self) -> None:
        invariant = BusinessInvariant(
            invariant_id="total",
            kind=InvariantKind.FIXED_FIELD_TOTAL,
            source=InvariantSource.FILE,
            source_name="out.dat",
            expected="10",
            record_length=2,
            offset=0,
            length=2,
        )
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(exit_code=0, files={"out.dat": b"1X"}),
        )[0]
        assert not outcome.passed
        assert "signed integer" in outcome.reason

    def test_float_expectation_is_rejected_at_declaration(self) -> None:
        with pytest.raises(ValueError, match="exact decimal"):
            BusinessInvariant(
                invariant_id="float",
                kind=InvariantKind.FIXED_FIELD_TOTAL,
                source=InvariantSource.FILE,
                source_name="out.dat",
                expected=1.1,
                record_length=2,
                offset=0,
                length=2,
            )

    def test_window_outside_record_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="exceeds record_length"):
            BusinessInvariant(
                invariant_id="window",
                kind=InvariantKind.FIXED_FIELD_EQUALS,
                source=InvariantSource.FILE,
                source_name="out.dat",
                expected=b"AB",
                record_length=4,
                offset=3,
                length=2,
            )


class TestJsonState:
    def _json(self, expected, path="account.balance") -> BusinessInvariant:
        return BusinessInvariant(
            invariant_id="json",
            kind=InvariantKind.JSON_FIELD_EQUALS,
            source=InvariantSource.FILE,
            source_name="state.json",
            expected=expected,
            json_path=path,
        )

    def test_decimal_json_value_matches_exactly(self) -> None:
        invariant = self._json("1.10")
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0,
                files={"state.json": b'{"account":{"balance":1.10}}'},
            ),
        )[0]
        assert outcome.passed
        assert outcome.observed == Decimal("1.10")

    def test_numeric_mismatch_is_exact(self) -> None:
        invariant = self._json("1.10")
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0,
                files={"state.json": b'{"account":{"balance":1.11}}'},
            ),
        )[0]
        assert not outcome.passed

    def test_list_index_path(self) -> None:
        invariant = self._json("BETA", path="lines[1].code")
        assert evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0,
                files={
                    "state.json": b'{"lines":[{"code":"ALPHA"},{"code":"BETA"}]}'
                },
            ),
        )[0].passed

    def test_missing_path_fails(self) -> None:
        invariant = self._json("x")
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0, files={"state.json": b'{"account":{}}'}
            ),
        )[0]
        assert not outcome.passed
        assert outcome.observed == "MISSING_PATH"

    def test_malformed_json_fails(self) -> None:
        invariant = self._json("x")
        outcome = evaluate_invariants(
            (invariant,),
            InvariantObservation(
                exit_code=0, files={"state.json": b"{not json"}
            ),
        )[0]
        assert not outcome.passed
        assert outcome.observed == "MALFORMED_JSON"

    def test_float_expectation_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="float"):
            self._json(1.1)


class TestDeclarations:
    def test_declaration_parameters_that_would_be_ignored_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="does not accept record_length"):
            BusinessInvariant(
                invariant_id="bad",
                kind=InvariantKind.EXIT_CODE,
                source=InvariantSource.EXIT_STATUS,
                expected=0,
                record_length=4,
            )

    def test_duplicate_ids_rejected_during_evaluation(self) -> None:
        invariant = _invariant(
            InvariantKind.EXIT_CODE, source=InvariantSource.EXIT_STATUS,
            expected=0,
        )
        with pytest.raises(ValueError, match="Duplicate invariant_id"):
            evaluate_invariants(
                (invariant, invariant),
                InvariantObservation(exit_code=0),
            )

    def test_empty_invariant_set_cannot_produce_a_report(self) -> None:
        with pytest.raises(ValueError, match="no invariants"):
            build_report((), InvariantObservation(exit_code=0))


class TestCanonicalReport:
    def _invariants(self):
        return (
            BusinessInvariant(
                invariant_id="exit", kind=InvariantKind.EXIT_CODE,
                source=InvariantSource.EXIT_STATUS, expected=0,
            ),
            BusinessInvariant(
                invariant_id="lines", kind=InvariantKind.EXACT_LINES,
                expected=("OK",),
            ),
        )

    def test_report_is_deterministic_and_pass_only_when_all_pass(self) -> None:
        first = _report(
            self._invariants(),
            InvariantObservation(exit_code=0, stdout=b"OK\n"),
        )
        second = _report(
            self._invariants(),
            InvariantObservation(exit_code=0, stdout=b"OK\n"),
        )
        assert first.to_bytes() == second.to_bytes()
        assert first.overall == "PASS"

    def test_one_failure_makes_the_whole_report_fail(self) -> None:
        report = _report(
            self._invariants(),
            InvariantObservation(exit_code=1, stdout=b"OK\n"),
        )
        assert report.overall == "FAIL"
        assert report.failed_count == 1

    def test_declaration_order_does_not_change_canonical_report(self) -> None:
        forward = _report(
            self._invariants(),
            InvariantObservation(exit_code=0, stdout=b"OK\n"),
        )
        backward = _report(
            tuple(reversed(self._invariants())),
            InvariantObservation(exit_code=0, stdout=b"OK\n"),
        )
        assert forward.to_bytes() == backward.to_bytes()
        assert invariant_definition_digest(self._invariants()) == (
            invariant_definition_digest(tuple(reversed(self._invariants())))
        )


class TestReportAdmission:
    def _valid_report(self):
        return _report(
            (
                BusinessInvariant(
                    invariant_id="exit", kind=InvariantKind.EXIT_CODE,
                    source=InvariantSource.EXIT_STATUS, expected=0,
                ),
            ),
            InvariantObservation(exit_code=0),
        )

    def test_valid_report_is_admitted(self) -> None:
        admitted = admit_report(self._valid_report().to_bytes())
        assert admitted.overall == "PASS"

    def test_tampered_digest_is_rejected(self) -> None:
        payload = json.loads(self._valid_report().to_bytes())
        payload["definition_digest"] = "0" * 64
        with pytest.raises(ValueError, match="definition_digest"):
            admit_report(json.dumps(payload).encode())

    def test_outcome_not_declared_is_rejected(self) -> None:
        payload = json.loads(self._valid_report().to_bytes())
        payload["outcomes"].append({
            "invariant_id": "smuggled",
            "phase": "POSTCONDITION",
            "kind": "EXIT_CODE",
            "passed": True,
            "expected": 0,
            "observed": 0,
            "reason": "fabricated",
        })
        with pytest.raises(ValueError, match="do not match"):
            admit_report(json.dumps(payload).encode())

    def test_overall_contradicting_outcomes_is_rejected(self) -> None:
        payload = json.loads(self._valid_report().to_bytes())
        payload["outcomes"][0]["passed"] = False
        with pytest.raises(ValueError, match="contradicts"):
            admit_report(json.dumps(payload).encode())

    def test_non_json_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            admit_report(b"not json")
