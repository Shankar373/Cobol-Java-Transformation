"""Real Docker-backed Oracle adapter for GnuCOBOL execution.

Implements the oracle adapter with real Docker execution:
- container-per-execution
- read-only staged source
- no network
- resource limits
- hard timeout
- source hash before/after
- real stdout/stderr capture
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from engine.domain.identities import (
    AdapterStatus,
    ContentHash,
    ExecutionId,
    RunId,
)
from engine.oracle.adapter import (
    OracleAdapter,
    OracleAdapterConfig,
    OracleExecutionResult,
)


class DockerOracleAdapter(OracleAdapter):
    """Real Docker-backed GnuCOBOL oracle adapter.

    Multi-program applications are compiled and linked by GnuCOBOL from
    their separate source modules (``cobc -x ENTRY.cob OTHER.cob ...``):
    sources are never concatenated. The entry module is resolved by
    explicit entry_program, main.cob/main.cbl convention, then legacy
    first-module fallback. Single-module workloads behave exactly as
    before.
    """

    V1_IMAGE = "gnucobol-ocesql:latest"
    V1_DIGEST = "sha256:f6f567fb15c30442ea844426dd9d5dea0b626f70bbe3d2208e26cf9d35b8d780"

    def __init__(self, config: OracleAdapterConfig) -> None:
        super().__init__(config)
        self._docker_available = self._check_docker()

    def _check_docker(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def probe(self) -> AdapterStatus:
        if not self._docker_available:
            self._status = AdapterStatus.UNAVAILABLE
            return self._status

        try:
            result = subprocess.run(
                ["docker", "image", "inspect", self.V1_IMAGE],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0:
                self._status = AdapterStatus.AVAILABLE
            else:
                self._status = AdapterStatus.UNAVAILABLE
        except Exception:
            self._status = AdapterStatus.UNAVAILABLE

        return self._status

    # Filenames that designate the application entry module by convention.
    # Mirrors the ingestion layer's source-root markers without importing it.
    ENTRY_MODULE_MARKERS = frozenset({"main.cob", "main.cbl"})

    COBOL_SUFFIXES = (".cob", ".cbl")

    @staticmethod
    def _read_program_id(source_file: Path) -> str:
        """Extract PROGRAM-ID for entry matching only (not parsing)."""
        try:
            text = source_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
        match = re.search(
            r"PROGRAM-ID\.\s*([A-Za-z0-9][A-Za-z0-9_-]*)",
            text,
            re.IGNORECASE,
        )
        return match.group(1).upper() if match else ""

    @classmethod
    def select_modules(
        cls,
        source_dir: Path,
        entry_program: str | None = None,
    ) -> tuple[str | None, list[str]]:
        """Select the entry module and link set for a COBOL source directory.

        Returns (entry_filename, [other_module_filenames]). Only top-level
        *.cob/*.cbl files are modules; copybooks and other files are never
        compiled. Sources are NEVER concatenated — GnuCOBOL compiles and
        links the separate modules with a single multi-file command.

        Entry resolution order:
          1. explicit entry_program (PROGRAM-ID, then filename match);
          2. main.cob/main.cbl filename convention (case-insensitive);
          3. legacy first-glob fallback.
        """
        # .cob takes precedence over .cbl (legacy glob order), each sorted.
        modules: list[str] = []
        for suffix in cls.COBOL_SUFFIXES:
            modules.extend(sorted(
                (
                    f.name
                    for f in source_dir.iterdir()
                    if f.is_file() and f.suffix.lower() == suffix
                ),
                key=str.lower,
            ))
        if not modules:
            return None, []

        wanted = (entry_program or "").strip().strip("'\"").upper()
        if wanted:
            for name in modules:
                if cls._read_program_id(source_dir / name) == wanted:
                    others = [m for m in modules if m != name]
                    return name, others
            for name in modules:
                if name.lower() == wanted.lower() or Path(name).stem.upper() == wanted:
                    others = [m for m in modules if m != name]
                    return name, others

        for name in modules:
            if name.lower() in cls.ENTRY_MODULE_MARKERS:
                others = [m for m in modules if m != name]
                return name, others

        # Legacy fallback: first module wins (historical glob behaviour
        # restricted to a deterministic sorted order).
        return modules[0], modules[1:]

    # --- Source format detection -----------------------------------------
    #
    # GnuCOBOL defaults to fixed source format. The fixture estate mixes
    # free-format (code beginning at column 1) and fixed-format (sequence
    # area columns 1-6, indicator column 7) sources, so the oracle must
    # select the format flag per compilation unit instead of assuming one.
    # Sources are NEVER rewritten or normalised.

    @staticmethod
    def _line_is_comment(line: str) -> bool:
        """True for fixed- or free-format comment lines."""
        if line.startswith("*") or line.startswith("/"):
            return True
        if len(line) > 6 and line[6] in "*/":
            return True
        return line.lstrip().startswith("*>")

    @classmethod
    def detect_source_format(cls, text: str) -> str:
        """Classify COBOL source text as ``"free"`` or ``"fixed"``.

        An explicit ``>>SOURCE FORMAT`` directive takes precedence. In its
        absence fixed format is assumed unless a code line places a
        non-digit, non-space character in the sequence area (columns 1-6):
        that is impossible in fixed format and is characteristic of free
        format, where code may begin at column 1.
        """
        for raw in text.splitlines():
            upper = raw.strip().upper()
            if upper.startswith(">>SOURCE") and "FORMAT" in upper:
                if "FREE" in upper:
                    return "free"
                if "FIXED" in upper:
                    return "fixed"
        for raw in text.splitlines():
            line = raw.rstrip("\r\n")
            if not line.strip() or cls._line_is_comment(line):
                continue
            if any(ch not in "0123456789 " for ch in line[:6]):
                return "free"
        return "fixed"

    @classmethod
    def _module_source_format(cls, source_dir: Path, module: str) -> str:
        try:
            text = (source_dir / module).read_text(
                encoding="utf-8", errors="ignore"
            )
        except OSError:
            return "fixed"
        return cls.detect_source_format(text)

    @classmethod
    def _compile_format_flag(cls, source_dir: Path, modules: list[str]) -> str:
        """Return the ``cobc`` source-format flag for a module set.

        V1 contract: the modules of one application share a single source
        format. ``-free`` is applied only when every module is detected as
        free format; otherwise GnuCOBOL's fixed-format default is kept, so
        fixed-format workloads are never reinterpreted as free format.
        """
        formats = {cls._module_source_format(source_dir, m) for m in modules}
        return "-free " if formats == {"free"} else ""

    def _compute_source_hash(self, source_path: str) -> ContentHash:
        hasher = hashlib.sha256()
        path = Path(source_path)
        if path.is_file():
            hasher.update(path.read_bytes())
        elif path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    hasher.update(str(f.relative_to(path)).encode())
                    hasher.update(f.read_bytes())
        return ContentHash(digest=hasher.hexdigest())

    def execute(
        self,
        run_id: RunId,
        source_path: str,
        input_data: bytes | None = None,
        input_files: dict[str, bytes] | None = None,
        entry_program: str | None = None,
    ) -> OracleExecutionResult:
        execution_id = ExecutionId(
            value=f"oracle-{run_id.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        start_time = datetime.now(timezone.utc)

        source_hash_before = self._compute_source_hash(source_path)

        if not self._docker_available:
            end_time = datetime.now(timezone.utc)
            return OracleExecutionResult(
                execution_id=execution_id,
                run_id=run_id,
                oracle_id=self._config.oracle_id,
                status=AdapterStatus.UNAVAILABLE,
                exit_code=None,
                stdout=b"",
                stderr=b"Docker is not available",
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status="error",
                timeout_applied=False,
                source_tree_hash_before=source_hash_before,
                source_tree_hash_after=source_hash_before,
            )

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                cobol_source = Path(source_path)
                if cobol_source.is_file():
                    dest = Path(tmpdir) / "src" / cobol_source.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(cobol_source.read_bytes())
                    # A single COBOL entry file may depend on sibling COPYBOOKs.
                    # Stage those read-only dependencies without broadening the
                    # compile/link set to unrelated COBOL program modules.
                    for copybook in cobol_source.parent.iterdir():
                        if copybook.is_file() and copybook.suffix.lower() == ".cpy":
                            (dest.parent / copybook.name).write_bytes(copybook.read_bytes())
                    container_src = "/workspace/src"
                else:
                    import shutil
                    dest = Path(tmpdir) / "src"
                    shutil.copytree(str(cobol_source), str(dest))
                    container_src = "/workspace/src"

                main_file = cobol_source.name if cobol_source.is_file() else None
                link_modules: list[str] = []
                if main_file is None:
                    main_file, link_modules = self.select_modules(
                        Path(tmpdir, "src"), entry_program=entry_program
                    )

                if main_file is None:
                    end_time = datetime.now(timezone.utc)
                    return OracleExecutionResult(
                        execution_id=execution_id,
                        run_id=run_id,
                        oracle_id=self._config.oracle_id,
                        status=AdapterStatus.FAILED,
                        exit_code=1,
                        stdout=b"",
                        stderr=b"No COBOL source file found",
                        start_time=start_time.isoformat(),
                        end_time=end_time.isoformat(),
                        termination_status="nonzero_exit",
                        timeout_applied=False,
                        source_tree_hash_before=source_hash_before,
                        source_tree_hash_after=source_hash_before,
                    )

                output_dir = Path(tmpdir) / "output"
                output_dir.mkdir()

                input_dir = Path(tmpdir) / "input"
                input_mount_args: list[str] = []
                if input_files:
                    input_dir.mkdir()
                    for name, content in input_files.items():
                        (input_dir / name).write_bytes(content)
                    input_mount_args = [
                        "-v", f"{os.path.abspath(input_dir)}:/workspace/input:ro",
                    ]

                # Multi-module link: the entry module plus every other
                # COBOL module, compiled/linked by GnuCOBOL from separate
                # source files (never concatenated) so static CALLs resolve.
                # Source format is detected per unit so free-format sources
                # compile without reinterpreting fixed-format ones.
                compile_units = " ".join(
                    shlex.quote(name) for name in [main_file, *link_modules]
                )
                format_flag = self._compile_format_flag(
                    Path(tmpdir, "src"), [main_file, *link_modules]
                )
                compile_cmd = (
                    f"cd {container_src} && "
                    f"cobc -x {format_flag}{compile_units} -o /tmp/oracle_prog && "
                    f"cd /workspace && "
                    f"/tmp/oracle_prog"
                )

                docker_cmd = [
                    "docker", "run", "--rm",
                    "--network", "none",
                    "--memory", "512m",
                    "--cpus", "1.0",
                    "--pids-limit", "256",
                    "--workdir", "/workspace",
                    "-v", f"{os.path.abspath(tmpdir)}/src:{container_src}:ro",
                    "-v", f"{os.path.abspath(output_dir)}:/workspace/output",
                    *input_mount_args,
                    self.V1_IMAGE,
                    "sh", "-c", compile_cmd,
                ]

                try:
                    proc = subprocess.run(
                        docker_cmd,
                        capture_output=True,
                        timeout=self._config.timeout_seconds + 5,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    stdout = proc.stdout
                    stderr = proc.stderr
                    exit_code = proc.returncode
                    termination = "normal" if exit_code == 0 else "nonzero_exit"

                except subprocess.TimeoutExpired:
                    stdout = b""
                    stderr = b"Oracle execution timeout"
                    exit_code = None
                    termination = "timeout"

                generated_files: dict[str, bytes] = {}
                if output_dir.is_dir():
                    for f in sorted(output_dir.rglob("*")):
                        if f.is_file():
                            rel = f.name
                            generated_files[rel] = f.read_bytes()

            end_time = datetime.now(timezone.utc)
            source_hash_after = self._compute_source_hash(source_path)

            return OracleExecutionResult(
                execution_id=execution_id,
                run_id=run_id,
                oracle_id=self._config.oracle_id,
                status=AdapterStatus.SUCCEEDED if exit_code == 0 else AdapterStatus.FAILED,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status=termination,
                timeout_applied=termination == "timeout",
                timeout_duration=self._config.timeout_seconds,
                generated_files=generated_files if generated_files else None,
                source_tree_hash_before=source_hash_before,
                source_tree_hash_after=source_hash_after,
            )

        except Exception as e:
            end_time = datetime.now(timezone.utc)
            return OracleExecutionResult(
                execution_id=execution_id,
                run_id=run_id,
                oracle_id=self._config.oracle_id,
                status=AdapterStatus.FAILED,
                exit_code=None,
                stdout=b"",
                stderr=str(e).encode(),
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                termination_status="error",
                timeout_applied=False,
                source_tree_hash_before=source_hash_before,
                source_tree_hash_after=source_hash_before,
            )
