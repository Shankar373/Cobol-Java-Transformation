"""Layer 1 audit regressions: blank-padded source in a ZIP, oversized mainframe members, concurrent identical runs."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path

from enterprise.discovery.compilers import ToolchainConfig
from enterprise.discovery.discover import DiscoveryRequest, discover
from enterprise.discovery.limits import Limits
from tests.discovery.helpers import make_zip, write_tree

NONE = ToolchainConfig(backend="none")
PROGRAM = b"       IDENTIFICATION DIVISION.\n       PROGRAM-ID. BIGPGM.\n       PROCEDURE DIVISION.\n           STOP RUN.\n"


def test_blank_padded_source_in_a_zip_is_not_mistaken_for_a_zip_bomb(tmp_path: Path) -> None:
    padded = PROGRAM + (b" " * 79 + b"\n") * 3000  # compresses far beyond 200:1
    archive = make_zip(tmp_path / "estate.zip", [("src/PAD.cbl", padded), ("copy/BLANK.cpy", b" " * 100_000)])
    result = discover(DiscoveryRequest("zip", str(archive)), tmp_path / "store", toolchain=NONE)
    assert result.report["completeness"]["checks"][0]["passed"]


def test_an_oversized_extensionless_member_is_a_blocker_not_a_silent_omission(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "src", {"BIGPGM": PROGRAM + b"*" + b"X" * 5000 + b"\n", "OK.cbl": PROGRAM})
    result = discover(DiscoveryRequest("directory", str(root)), tmp_path / "store", limits=Limits(max_source_bytes=1000), toolchain=NONE)
    gate = result.report["completeness"]
    assert gate["status"] == "INCOMPLETE" and "every-source-file-scanned" in gate["blockers"]
    assert result.report["readiness"]["status"] == "BLOCKED"


def test_concurrent_discoveries_of_the_same_input_do_not_crash(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "src", {"A.cbl": PROGRAM})
    store, errors = tmp_path / "store", []

    def run() -> None:
        try:
            for _ in range(3):
                discover(DiscoveryRequest("directory", str(root)), store, toolchain=NONE)
        except Exception as exc:  # noqa: BLE001 - the test reports any failure
            errors.append(traceback.format_exc())

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors[0]
