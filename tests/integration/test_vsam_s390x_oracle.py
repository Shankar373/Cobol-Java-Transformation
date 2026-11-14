"""Lane D: a real big-endian machine writes the data, the platform conversion must reproduce what x86 writes.

The same COBOL program is compiled and run twice by GnuCOBOL 3.1.2: once natively on x86-64 and once on
``linux/s390x`` (QEMU-emulated, big-endian).  The records the s390x run wrote are converted with
``convert_record_between`` from the s390x representation to the x86 one, and must equal, byte for byte, the
records the x86 run wrote - an independent differential: neither side of the comparison is produced by the
migration code.  The s390x run also pins the facts the presets claim (COMP-5 is big-endian there).

Evidence class: GNUCOBOL_DIFFERENTIAL on Linux/s390x.  Linux on s390x is not z/OS and GnuCOBOL is not IBM
Enterprise COBOL: this establishes byte order and width behaviour of a compiled program on a big-endian
CPU, nothing about IBM VSAM.  Docker lane: RUN_DOCKER_TESTS=1 with images ``gnucobol-ocesql:latest`` and
``gnucobol-s390x:local`` (built from ``docker/gnucobol-s390x``).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.vsam.layout import BinaryWidthModel, derive_file_layout
from engine.vsam.model import Encoding
from engine.vsam.platform import convert_record_between, platform

X86_IMAGE = os.environ.get("VSAM_ORACLE_IMAGE", "gnucobol-ocesql:latest")  # override: same differential on another compiler image
S390X_IMAGE = "gnucobol-s390x:local"

RECORD = """\
       01 REC.
          05 ID-X  PIC X(4).
          05 N     PIC S9(4) COMP.
          05 C5    PIC S9(4) COMP-5.
          05 B     PIC S9(9) COMP-5.
          05 U     PIC 9(4) COMP-5.
          05 A     PIC S9(5) COMP-3.
          05 NOTE  PIC X(3).
"""

VALUES = [  # id, N, C5, B, U, A, note
    ("A001", 258, 258, 123456789, 65535, 12345, "abc"),
    ("B002", -2, -2, -1, 0, -999, "def"),
    ("C003", 9999, -9999, 999999999, 258, 0, "xyz"),
    ("D004", 0, 0, -999999999, 1, 7, "   "),
]

MODELS = [("default", BinaryWidthModel.GNUCOBOL_1_2_4_8, "GNUCOBOL_X86_DEFAULT", "GNUCOBOL_S390X_DEFAULT"),
          ("ibm", BinaryWidthModel.IBM_2_4_8, "GNUCOBOL_X86_IBM_DIALECT", "GNUCOBOL_S390X_IBM_DIALECT")]


def program() -> str:
    body: list[str] = []
    for ident, n, c5, b, u, a, note in VALUES:
        for statement in ("MOVE SPACES TO REC.", f'MOVE "{ident}" TO ID-X.', f"MOVE {n} TO N.", f"MOVE {c5} TO C5.",
                          f"MOVE {b} TO B.", f"MOVE {u} TO U.", f"MOVE {a} TO A.", f'MOVE "{note}" TO NOTE.',
                          "WRITE REC."):
            body.append(f"           {statement}\n")
    return ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. ENDI.\n       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n"
            '           SELECT F ASSIGN TO "OUT.DAT" ORGANIZATION IS SEQUENTIAL.\n'
            "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n" + RECORD +
            "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           OPEN OUTPUT F.\n" + "".join(body) +
            "           CLOSE F.\n           STOP RUN.\n")


def run(tmp_path: Path, image: str, std: str, platform_flag: list[str]) -> bytes:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 with the GnuCOBOL images present")
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode != 0:
        pytest.skip(f"image {image} is not built (docker build docker/gnucobol-s390x -t gnucobol-s390x:local)")
    (tmp_path / "ENDI.cob").write_text(program(), encoding="utf-8")
    os.chmod(tmp_path, 0o777)
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", *platform_flag, "-v", f"{tmp_path}:/src", image, "sh", "-c",
         f"cd /tmp && cobc -x -std={std} /src/ENDI.cob -o p && ./p && cp OUT.DAT /src/ && chmod a+r /src/OUT.DAT"],
        capture_output=True, timeout=900)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return (tmp_path / "OUT.DAT").read_bytes()


def layout_for(model: BinaryWidthModel):
    fdef = CobolParser().parse(program()).file_definitions[0]
    layout = derive_file_layout(fdef, binary_width_model=model)
    assert layout.supported, layout.diagnostics
    return layout


@pytest.mark.parametrize("std,model,x86_name,s390x_name", MODELS)
def test_the_real_big_endian_cpu_writes_comp5_big_endian(tmp_path, std, model, x86_name, s390x_name):
    layout = layout_for(model)
    written = run(tmp_path, S390X_IMAGE, std, ["--platform", "linux/s390x"])
    assert len(written) == len(VALUES) * layout.record_length
    by_path = {f.path: f for f in layout.fields}
    first = written[:layout.record_length]
    c5, comp = by_path["REC.C5"], by_path["REC.N"]
    assert first[c5.offset:c5.offset + c5.length] == (258).to_bytes(c5.length, "big", signed=True)   # big-endian COMP-5
    assert first[comp.offset:comp.offset + comp.length] == (258).to_bytes(comp.length, "big", signed=True)


@pytest.mark.parametrize("std,model,x86_name,s390x_name", MODELS)
def test_s390x_records_converted_to_x86_equal_the_records_x86_wrote(tmp_path, std, model, x86_name, s390x_name):
    layout = layout_for(model)
    x86_dir, s390x_dir = tmp_path / "x86", tmp_path / "s390x"
    x86_dir.mkdir()
    s390x_dir.mkdir()
    x86 = run(x86_dir, X86_IMAGE, std, [])
    s390x = run(s390x_dir, S390X_IMAGE, std, ["--platform", "linux/s390x"])
    assert len(x86) == len(s390x) == len(VALUES) * layout.record_length
    assert x86 != s390x                                    # the machines really differ (COMP-5 byte order)
    size = layout.record_length
    converted = b"".join(
        convert_record_between(s390x[i:i + size], layout, layout, platform(s390x_name), platform(x86_name),
                               Encoding.ASCII, Encoding.ASCII)
        for i in range(0, len(s390x), size))
    assert converted == x86
    back = b"".join(
        convert_record_between(x86[i:i + size], layout, layout, platform(x86_name), platform(s390x_name),
                               Encoding.ASCII, Encoding.ASCII)
        for i in range(0, len(x86), size))
    assert back == s390x                                   # and the other direction
