"""The generated Java application consumes a migrated dataset, compared with the original COBOL reading the same file.

A mainframe-form dataset (EBCDIC cp037 text, big-endian binary at IBM widths, packed decimal) is migrated by the real
pipeline to the GnuCOBOL x86 form.  One COBOL program then reads the migrated file twice over: compiled by GnuCOBOL
3.1.2 (the reference) and transformed by the product into Java that is compiled and run.  Both print every record
and a running total; their output must be identical and must equal the values the records were built from.  Neither
side uses the migration code to read the data.

What this proves: for a fixed-length sequential dataset of DISPLAY, COMP and COMP-3 fields, the Java the product
generates reads a migrated file exactly as the COBOL oracle does.  What it does not: indexed or variable files (the
generated Java file I/O is certified only for the shapes in the capability matrix), COMP-5, or any IBM runtime.
Docker lane (RUN_DOCKER_TESTS=1: GnuCOBOL image + a JDK on PATH).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.cobol_parser import CobolParser
from engine.transformation.producer import TransformationProducer
from engine.vsam.layout import derive_file_layout
from engine.vsam.migrate import migrate_dataset
from engine.vsam.model import DatasetDefinition, Encoding, Organization
from engine.vsam.platform import platform

IMAGE = os.environ.get("VSAM_ORACLE_IMAGE", "gnucobol-ocesql:latest")  # override: same differential on another compiler image
IBM_Z, X86 = platform("IBM_ZOS"), platform("GNUCOBOL_X86_DEFAULT")

RECORD = ("       01 REC.\n          05 ID-X PIC X(4).\n          05 QD   PIC 9(5).\n"
          "          05 QP   PIC 9(5) COMP-3.\n          05 QC   PIC 9(4) COMP.\n")
ROWS = [("A001", 120, 34567, 1500), ("B002", 7, 1, 9999), ("C003", 99999, 99999, 0), ("D004", 0, 0, 258)]


def program() -> str:
    return (
        "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. RDR.\n       ENVIRONMENT DIVISION.\n"
        "       INPUT-OUTPUT SECTION.\n       FILE-CONTROL.\n           SELECT F ASSIGN TO \"F.DAT\"\n"
        "               ORGANIZATION IS SEQUENTIAL.\n"
        "       DATA DIVISION.\n       FILE SECTION.\n       FD F.\n" + RECORD +
        "       WORKING-STORAGE SECTION.\n       01 EOF-FLAG PIC X VALUE 'N'.\n       01 TOT PIC 9(9) VALUE 0.\n"
        "       PROCEDURE DIVISION.\n       MAIN-PARA.\n           OPEN INPUT F.\n"
        "           PERFORM UNTIL EOF-FLAG = 'Y'\n               READ F\n                   AT END MOVE 'Y' TO EOF-FLAG\n"
        "                   NOT AT END\n                       ADD QD QP QC TO TOT\n"
        "                       DISPLAY ID-X ' ' QD ' ' QP ' ' QC ' ' TOT\n"
        "               END-READ\n           END-PERFORM.\n           CLOSE F.\n           STOP RUN.\n")


def packed5(value: int) -> bytes:
    digits = f"{value:05d}"
    nibbles = [int(c) for c in digits] + [0xF]            # unsigned PIC 9(5) COMP-3
    return bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, 6, 2))


def mainframe_bytes() -> bytes:
    return b"".join(i.encode("cp037") + str(d).zfill(5).encode("cp037") + packed5(p) + c.to_bytes(2, "big")
                    for i, d, p, c in ROWS)


def migrated_dataset() -> bytes:
    fd = CobolParser().parse(program()).file_definitions[0]
    src = derive_file_layout(fd, binary_width_model=IBM_Z.width_model)
    dst = derive_file_layout(fd, binary_width_model=X86.width_model)
    definition = DatasetDefinition("MF", Organization.SEQUENTIAL, record_length=src.record_length,
                                   encoding=Encoding.EBCDIC_CP037)
    out, report = migrate_dataset(definition, mainframe_bytes(), src, Encoding.ASCII, target_layout=dst,
                                  source_platform=IBM_Z, target_platform=X86)
    assert report.state == "RECONCILED" and report.success, report.failures
    return out


def need_lane() -> None:
    if os.environ.get("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Docker lane test: set RUN_DOCKER_TESTS=1 with the GnuCOBOL image and a JDK")
    if not (shutil.which("javac") and shutil.which("java")):
        pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")


def run_cobol(tmp_path: Path, data: bytes) -> list[str]:
    work = tmp_path / "cobol"
    work.mkdir()
    (work / "RDR.cob").write_text(program(), encoding="utf-8")
    (work / "F.DAT").write_bytes(data)
    os.chmod(work, 0o777)
    run = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-v", f"{work}:/src", IMAGE, "sh", "-c",
         "cd /tmp && cp /src/F.DAT . && cobc -x -std=default /src/RDR.cob -o p && ./p"],
        capture_output=True, timeout=300)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return run.stdout.decode("latin-1").splitlines()


def run_java(tmp_path: Path, data: bytes) -> list[str]:
    work = tmp_path / "java"
    work.mkdir()
    result = TransformationProducer().transform(program(), "RDR")
    assert result.success is True, result.errors
    for generated in result.generated_files:
        (work / generated.filename).write_text(generated.source_code, encoding="utf-8")
    (work / "F.DAT").write_bytes(data)
    compiled = subprocess.run(["javac", "-nowarn", "-d", str(work), *[str(work / g.filename) for g in result.generated_files]],
                              capture_output=True, timeout=120)
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    run = subprocess.run(["java", "-Dline.separator=\n", "-cp", str(work), result.generated_files[0].class_name],
                         capture_output=True, timeout=60, cwd=work)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    return run.stdout.decode().splitlines()


def expected() -> list[str]:
    total, lines = 0, []
    for i, d, p, c in ROWS:
        total += d + p + c
        lines.append(f"{i} {d:05d} {p:05d} {c:04d} {total:09d}")
    return lines


def test_the_cobol_oracle_reads_the_migrated_file_as_the_values_it_was_built_from(tmp_path):
    need_lane()
    assert run_cobol(tmp_path, migrated_dataset()) == expected()


def test_the_generated_java_reads_the_migrated_file_exactly_like_the_cobol_oracle(tmp_path):
    need_lane()
    data = migrated_dataset()
    cobol, java = run_cobol(tmp_path, data), run_java(tmp_path, data)
    assert java == cobol == expected()


def test_the_generated_java_does_not_read_the_unmigrated_mainframe_bytes_as_the_same_values(tmp_path):
    """Control: the migration is what makes the file readable, so the comparison above cannot pass vacuously."""
    need_lane()
    try:
        java = run_java(tmp_path, mainframe_bytes())
    except AssertionError:
        return                                            # the Java refused or failed on foreign data: also "not the same"
    assert java != expected()
