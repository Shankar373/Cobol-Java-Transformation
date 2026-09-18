"""Real Java candidate adapter with javac compilation and execution.

Implements the candidate adapter with real execution:
- platform-controlled javac
- real Java execution
- stdout/stderr capture
- artifact capture
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from engine.candidate.adapter import (
    CandidateAdapter,
    CandidateExecutionResult,
    CandidateManifest,
    CompilationResult,
)
from engine.domain.identities import (
    AdapterStatus,
    ExecutionId,
    RunId,
)


class RealJavaCandidateAdapter(CandidateAdapter):
    """Real Java candidate adapter using host javac/java."""

    def __init__(self, javac_path: str = "javac", java_path: str = "java") -> None:
        super().__init__()
        self._javac_path = javac_path
        self._java_path = java_path
        self._available = self._check_java()

    def _check_java(self) -> bool:
        try:
            result = subprocess.run(
                [self._javac_path, "-version"],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @property
    def available(self) -> bool:
        return self._available

    def probe(self) -> AdapterStatus:
        if self._available:
            self._status = AdapterStatus.AVAILABLE
        else:
            self._status = AdapterStatus.UNAVAILABLE
        return self._status

    def validate_candidate(self, candidate_path: str, manifest: CandidateManifest) -> list[str]:
        violations = []
        missing = manifest.validate()
        if missing:
            violations.append(f"Missing manifest fields: {', '.join(missing)}")
        if manifest.dependencies:
            violations.append("V1 does not allow external dependencies")
        if not manifest.generated_files:
            violations.append("No generated files declared")
        if not manifest.entrypoint:
            violations.append("No entrypoint declared")

        candidate_dir = Path(candidate_path)
        for rel_path in manifest.generated_files:
            full_path = candidate_dir / rel_path
            if not full_path.exists():
                violations.append(f"Declared file not found: {rel_path}")

        return violations

    def compile(self, candidate_path: str, manifest: CandidateManifest) -> CompilationResult:
        if not self._available:
            return CompilationResult(
                success=False,
                class_files={},
                compilation_errors=("Java compiler not available",),
            )

        start_time = time.time()

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                candidate_dir = Path(candidate_path)
                java_files = []
                for rel_path in manifest.generated_files:
                    src = candidate_dir / rel_path
                    if src.suffix == ".java":
                        dest = Path(tmpdir) / rel_path
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(src.read_bytes())
                        java_files.append(str(dest))

                if not java_files:
                    return CompilationResult(
                        success=False,
                        class_files={},
                        compilation_errors=("No .java files found",),
                    )

                class_dir = Path(tmpdir) / "classes"
                class_dir.mkdir()

                compile_cmd = [
                    self._javac_path,
                    "-d", str(class_dir),
                ] + java_files

                proc = subprocess.run(
                    compile_cmd,
                    capture_output=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )

                if proc.returncode != 0:
                    return CompilationResult(
                        success=False,
                        class_files={},
                        compilation_errors=(proc.stderr.decode(errors="replace"),),
                        compilation_time_ms=int((time.time() - start_time) * 1000),
                    )

                class_files = {}
                for f in class_dir.rglob("*.class"):
                    rel = f.relative_to(class_dir)
                    class_files[str(rel)] = f.read_bytes()

                return CompilationResult(
                    success=True,
                    class_files=class_files,
                    compilation_time_ms=int((time.time() - start_time) * 1000),
                )

        except Exception as e:
            return CompilationResult(
                success=False,
                class_files={},
                compilation_errors=(str(e),),
                compilation_time_ms=int((time.time() - start_time) * 1000),
            )

    def execute(
        self,
        run_id: RunId,
        compiled_path: str,
        manifest: CandidateManifest,
        input_data: bytes | None = None,
        input_files: dict[str, bytes] | None = None,
    ) -> CandidateExecutionResult:
        execution_id = ExecutionId(
            value=f"candidate-{run_id.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        start_time = datetime.now(timezone.utc)

        if not self._available:
            end_time = datetime.now(timezone.utc)
            return CandidateExecutionResult(
                execution_id=execution_id,
                run_id=run_id,
                status=AdapterStatus.UNAVAILABLE,
                exit_code=None,
                stdout=b"",
                stderr=b"Java runtime not available",
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status="error",
                timeout_applied=False,
            )

        try:
            entrypoint_class = manifest.entrypoint
            entrypoint_class = entrypoint_class.removesuffix(".java")

            java_cmd = [
                self._java_path,
                "-cp", compiled_path,
                entrypoint_class,
            ]

            proc = subprocess.run(
                java_cmd,
                capture_output=True,
                input=input_data,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            end_time = datetime.now(timezone.utc)
            stdout = proc.stdout
            stderr = proc.stderr
            exit_code = proc.returncode
            termination = "normal" if exit_code == 0 else "nonzero_exit"

        except subprocess.TimeoutExpired:
            end_time = datetime.now(timezone.utc)
            stdout = b""
            stderr = b"Java execution timeout"
            exit_code = None
            termination = "timeout"

        except Exception as e:
            end_time = datetime.now(timezone.utc)
            stdout = b""
            stderr = str(e).encode()
            exit_code = None
            termination = "error"

        return CandidateExecutionResult(
            execution_id=execution_id,
            run_id=run_id,
            status=AdapterStatus.SUCCEEDED if exit_code == 0 else AdapterStatus.FAILED,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            termination_status=termination,
            timeout_applied=termination == "timeout",
            timeout_duration=30,
        )
