"""Stored characters of signed DISPLAY numerics (Phase 3, increment 10).

STRING (and a group move such as ``WRITE r FROM x``) copies a sending
item's storage.  GnuCOBOL 3.1.2 stores a negative signed DISPLAY item with
its last digit d overpunched as ``'p' + d`` (-1 is ``00q``, -120 is ``12p``,
``S9(3)V9`` -12.5 is ``012u``); positive values and zero are plain digits.
Signed STRING senders and signed WRITE FROM senders were refused; they are
reproduced now (``_display_storage_text``).  COMP senders store binary
bytes and stay refused.
"""

from __future__ import annotations

from pathlib import Path

from engine.transformation.producer import TransformationProducer
from tests.oracle_java_helpers import run_generated_java, run_gnucobol

DATA = Path(__file__).parent / "data" / "phase3"
SOURCE = (DATA / "OVP.cob").read_text()
EXPECTED = (DATA / "OVP.expected").read_text()


def test_comp_string_sender_stays_refused() -> None:
    source = SOURCE.replace("01  S   PIC S9(3).", "01  S   PIC S9(3) COMP.")
    assert TransformationProducer().transform(source, "OVP").success is False


def test_generated_java_matches_oracle(tmp_path: Path) -> None:
    assert run_generated_java(SOURCE, "OVP", tmp_path) == EXPECTED


def test_oracle_pin(tmp_path: Path) -> None:
    assert run_gnucobol(SOURCE, "OVP", tmp_path) == EXPECTED
