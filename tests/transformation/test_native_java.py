"""Native Java runtime proof tests.

Proves that generated Java is truly standalone:
- No COBOL runtime dependency
- No subprocess calls to COBOL
- No COBOL executable references
- Only standard Java libraries used
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from engine.transformation.producers.internal_native import InternalNativeJavaProducer


FIXTURES_DIR = Path("fixtures/workload-claims")
COBOL_PATH = FIXTURES_DIR / "cobol" / "CLAIMS.cob"


def load_cobol() -> str:
    return COBOL_PATH.read_text(encoding="utf-8")


class TestNativeJavaRuntime:
    """Prove generated Java is standalone native Java."""

    def test_no_cobol_runtime_imports(self):
        """Generated Java does not import COBOL runtime libraries."""
        producer = InternalNativeJavaProducer()
        cobol = load_cobol()
        result = producer.transform(cobol, program_id="CLAIMS")

        java_code = result.java_source_tree[list(result.java_source_tree.keys())[0]]

        # Should NOT import libcobj or any COBOL-specific library
        assert "libcobj" not in java_code.lower()
        assert "jp.osscons" not in java_code
        assert "CobolRunnable" not in java_code
        assert "CobolModule" not in java_code
        assert "CobolTerminal" not in java_code

    def test_no_subprocess_calls(self):
        """Generated Java does not use ProcessBuilder or Runtime.exec."""
        producer = InternalNativeJavaProducer()
        cobol = load_cobol()
        result = producer.transform(cobol, program_id="CLAIMS")

        java_code = result.java_source_tree[list(result.java_source_tree.keys())[0]]

        assert "ProcessBuilder" not in java_code
        assert "Runtime.exec" not in java_code
        assert "Runtime.getRuntime" not in java_code

    def test_no_cobol_executable_references(self):
        """Generated Java does not reference COBOL executables."""
        producer = InternalNativeJavaProducer()
        cobol = load_cobol()
        result = producer.transform(cobol, program_id="CLAIMS")

        java_code = result.java_source_tree[list(result.java_source_tree.keys())[0]]

        assert "cobc" not in java_code.lower()
        assert "gnucobol" not in java_code.lower()
        assert "cobj" not in java_code.lower()

    def test_only_standard_java_imports(self):
        """Generated Java uses only standard Java libraries."""
        producer = InternalNativeJavaProducer()
        cobol = load_cobol()
        result = producer.transform(cobol, program_id="CLAIMS")

        java_code = result.java_source_tree[list(result.java_source_tree.keys())[0]]

        # Extract all import statements
        imports = re.findall(r"import\s+([\w.]+);", java_code)

        for imp in imports:
            # Allow java.* and javax.* imports
            assert imp.startswith("java.") or imp.startswith("javax."), \
                f"Non-standard import: {imp}"

    def test_no_cobol_source_dependency(self):
        """Generated Java does not reference .cob files."""
        producer = InternalNativeJavaProducer()
        cobol = load_cobol()
        result = producer.transform(cobol, program_id="CLAIMS")

        java_code = result.java_source_tree[list(result.java_source_tree.keys())[0]]

        assert ".cob" not in java_code
        assert "CLAIMS.cob" not in java_code

    def test_compiles_without_cobol_runtime(self):
        """Generated Java compiles with only standard JDK."""
        producer = InternalNativeJavaProducer()
        cobol = load_cobol()
        result = producer.transform(cobol, program_id="CLAIMS")

        java_code = result.java_source_tree[list(result.java_source_tree.keys())[0]]

        with tempfile.TemporaryDirectory() as tmpdir:
            java_file = Path(tmpdir) / "Claims.java"
            java_file.write_text(java_code)

            proc = subprocess.run(
                ["javac", str(java_file)],
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert proc.returncode == 0, f"javac failed: {proc.stderr}"

    def test_runtime_requirements_empty(self):
        """Internal producer declares no runtime requirements."""
        producer = InternalNativeJavaProducer()
        reqs = producer.get_runtime_requirements()
        assert reqs == ()

    def test_metadata_confirms_standalone(self):
        """Result metadata confirms standalone Java."""
        producer = InternalNativeJavaProducer()
        cobol = load_cobol()
        result = producer.transform(cobol, program_id="CLAIMS")

        assert result.metadata.get("standalone_java") is True
        assert result.metadata.get("cobol_runtime_required") is False
