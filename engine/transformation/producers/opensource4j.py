"""OpenSourceCOBOL4J adapter — external/alternative producer.

This adapter wraps OpenSourceCOBOL4J as an external transformation producer.
It is NOT part of the core transformation implementation.

CRITICAL: Generated Java requires libcobj.jar (COBOL-specific runtime).
Therefore: standalone_native_java = PARTIAL

Architecture:

    COBOL source
        ↓
    OpenSourceCOBOL4J (external tool)
        ↓
    Generated Java (requires libcobj.jar)
        ↓
    TransformationResult (with runtime requirements)
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import uuid
from pathlib import Path

from engine.docker_cli import cleanup_container
from engine.execution.container_hardening import (
    container_run_hardening_flags,
    prepare_host_tree,
)
from engine.execution.sandbox_paths import sandbox_staging_dir, to_host_path
from engine.transformation.contracts import (
    GeneratedFile,
    ProducerCapability,
    TransformationProducer,
    TransformationResult,
    TransformationStatus,
)
from engine.transformation.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    to_contract_diagnostic,
)


# Declared capability surface of this adapter.  Hoisted to module scope (rather
# than inlined in transform()) so the claims are inspectable without executing
# the external compiler, and so the cross-producer capability guard
# (tests/transformation/test_producer_capability_consistency.py) can assert
# they never contradict the authoritative registry.
_PRODUCER_SUPPORTED_CONSTRUCTS: tuple[str, ...] = (
    "IDENTIFICATION DIVISION",
    "ENVIRONMENT DIVISION",
    "FILE-CONTROL",
    "DATA DIVISION",
    "FILE SECTION",
    "WORKING-STORAGE",
    "PIC X(n)",
    "PIC 9(n)",
    "OCCURS",
    "OPEN",
    "READ",
    "WRITE",
    "MOVE",
    "ADD",
    "IF/ELSE",
    "PERFORM",
    "DISPLAY",
    "GO TO",
    "STOP RUN",
    "STRING",
    "UNSTRING",
    "SORT",
    "CALL",
    "INDEXED files",
    "RELATIVE files",
)
_PRODUCER_UNSUPPORTED_CONSTRUCTS: tuple[str, ...] = ()

# Hard resource ceilings for the container that runs the external COBOL
# compiler.  We cap it because the source we compile is user-supplied: without
# a ceiling a runaway or malicious compile could consume the whole host.
# These live here as named constants (rather than inline strings) so the limits
# are visible and adjustable in one place, and they deliberately match the
# defaults used by the execution runner so every container we spawn obeys one
# single resource policy.
_PRODUCER_MEMORY_LIMIT = "512m"
_PRODUCER_CPU_LIMIT = "1.0"
_PRODUCER_PIDS_LIMIT = 256

logger = logging.getLogger(__name__)


def _cleanup_timed_out_container(container_name: str | None) -> None:
    """Remove a producer container whose run did not finish normally.

    When our timeout kills the Docker CLI process, the container it started is
    left running behind our back, so we have to go and stop it explicitly.
    This is best-effort: the caller is already reporting a FAILED compile, so a
    cleanup problem is logged rather than raised — it must never replace or
    hide the real error.
    """
    if not container_name:
        return
    try:
        removed, detail = cleanup_container(container_name)
    except Exception as exc:  # cleanup must never mask the producer failure
        logger.warning(
            "Producer container cleanup for %s raised: %s", container_name, exc
        )
        return
    if not removed:
        logger.warning(
            "Producer container %s not confirmed removed (%s)",
            container_name,
            detail,
        )


class OpenSourceCOBOL4JProducerAdapter(TransformationProducer):
    """Adapter for OpenSourceCOBOL4J as an external producer.

    This adapter exposes OpenSourceCOBOL4J through the standard producer
    interface. Generated Java requires libcobj.jar at runtime.

    CRITICAL: This producer does NOT satisfy the standalone native Java
    requirement. It is classified as an alternative/benchmark producer.
    """

    PRODUCER_IDENTITY = "opensourcecobol4j-adapter"
    PRODUCER_VERSION = "2.1.0"
    DOCKER_IMAGE = "opensourcecobol/opensourcecobol4j:2.1.0"

    def __init__(self, use_docker: bool = True) -> None:
        self._use_docker = use_docker

    def transform(
        self,
        cobol_source: str,
        program_id: str = "UNKNOWN",
    ) -> TransformationResult:
        """Transform COBOL source using OpenSourceCOBOL4J.

        NOTE: This requires Docker and the OpenSourceCOBOL4J image.
        Generated Java requires libcobj.jar at runtime.
        """
        if not self._use_docker:
            return TransformationResult(
                status=TransformationStatus.FAILED,
                producer_identity=self.PRODUCER_IDENTITY,
                producer_version=self.PRODUCER_VERSION,
                diagnostics=(
                    to_contract_diagnostic(Diagnostic.error(
                        DiagnosticCode.GENERATION_ERROR,
                        "OpenSourceCOBOL4J adapter requires Docker",
                    )),
                ),
            )

        # Declared before the try block so the cleanup in `finally` always has
        # a defined value to work with, even if the compile never gets far
        # enough to name a container.
        container_name: str | None = None

        try:
            # Write the COBOL source to a temporary directory on the host.  The
            # compiler container mounts this directory, which is why it has to
            # be a host-visible path rather than a location inside the service
            # container.
            with sandbox_staging_dir(prefix="cobj-") as tmpdir:
                cobol_path = Path(tmpdir) / f"{program_id}.cob"
                cobol_path.write_text(cobol_source, encoding="utf-8")

                # Compile the source in Docker.  Each flag is a deliberate
                # safety boundary, because the source being compiled is
                # user-supplied:
                #   --name        gives the container a known name so our
                #                 timeout handler can find and stop it;
                #                 `--rm` alone is not enough, because when the
                #                 CLI client is killed the container it started
                #                 is left running with no one to clean it up
                #   --network none the compiler never needs the network, and
                #                 untrusted source must not be able to reach it
                #   --memory / --cpus / --pids-limit
                #                 bound CPU, memory and process count so a
                #                 pathological program cannot exhaust the host
                #   no-new-privileges / --cap-drop ALL / --user 10001:10001
                #                 hardened execution identity (shared flags —
                #                 engine.execution.container_hardening)
                container_name = f"cobj-{uuid.uuid4().hex[:12]}"
                # The container user must be able to read the staged source
                # and write the generated .java next to it.
                prepare_host_tree(tmpdir, writable=True)
                docker_cmd = [
                    "docker", "run", "--rm",
                    *container_run_hardening_flags("producer-cobj"),
                    "--name", container_name,
                    "--network", "none",
                    "--memory", _PRODUCER_MEMORY_LIMIT,
                    "--cpus", _PRODUCER_CPU_LIMIT,
                    "--pids-limit", str(_PRODUCER_PIDS_LIMIT),
                    "-v", f"{to_host_path(tmpdir)}:/cobol",
                    self.DOCKER_IMAGE,
                    "cobj", f"/cobol/{program_id}.cob",
                ]

                result = subprocess.run(
                    docker_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.returncode != 0:
                    return TransformationResult(
                        status=TransformationStatus.FAILED,
                        producer_identity=self.PRODUCER_IDENTITY,
                        producer_version=self.PRODUCER_VERSION,
                        diagnostics=(
                            to_contract_diagnostic(Diagnostic.error(
                                DiagnosticCode.GENERATION_ERROR,
                                f"OpenSourceCOBOL4J compilation failed: {result.stderr}",
                            )),
                        ),
                    )

                # Read generated Java
                java_path = Path(tmpdir) / f"{program_id}.java"
                if not java_path.exists():
                    return TransformationResult(
                        status=TransformationStatus.FAILED,
                        producer_identity=self.PRODUCER_IDENTITY,
                        producer_version=self.PRODUCER_VERSION,
                        diagnostics=(
                            to_contract_diagnostic(Diagnostic.error(
                                DiagnosticCode.GENERATION_ERROR,
                                "OpenSourceCOBOL4J did not generate Java file",
                            )),
                        ),
                    )

                java_source = java_path.read_text(encoding="utf-8")

                return TransformationResult(
                    status=TransformationStatus.SUCCESS,
                    generated_files=(
                        GeneratedFile(
                            filename=f"{program_id}.java",
                            source_code=java_source,
                            language="java",
                        ),
                    ),
                    entrypoint=program_id,
                    producer_identity=self.PRODUCER_IDENTITY,
                    producer_version=self.PRODUCER_VERSION,
                    supported_constructs=_PRODUCER_SUPPORTED_CONSTRUCTS,
                    unsupported_constructs=_PRODUCER_UNSUPPORTED_CONSTRUCTS,
                    metadata={
                        "source_hash": self._compute_hash(cobol_source),
                        "standalone_java": False,
                        "cobol_runtime_required": True,
                        "runtime_dependency": "libcobj.jar",
                        "runtime_license": "LGPL-3.0",
                        "compiler_license": "GPL-3.0",
                        "docker_image": self.DOCKER_IMAGE,
                    },
                )

        except subprocess.TimeoutExpired:
            # Timeout-clean: the CLI client was killed, so the container
            # it started may still exist — remove it explicitly.
            _cleanup_timed_out_container(container_name)
            return TransformationResult(
                status=TransformationStatus.FAILED,
                producer_identity=self.PRODUCER_IDENTITY,
                producer_version=self.PRODUCER_VERSION,
                diagnostics=(
                    to_contract_diagnostic(Diagnostic.error(
                        DiagnosticCode.GENERATION_ERROR,
                        "OpenSourceCOBOL4J compilation timed out",
                    )),
                ),
            )
        except Exception as e:
            _cleanup_timed_out_container(container_name)
            return TransformationResult(
                status=TransformationStatus.FAILED,
                producer_identity=self.PRODUCER_IDENTITY,
                producer_version=self.PRODUCER_VERSION,
                diagnostics=(
                    to_contract_diagnostic(Diagnostic.error(
                        DiagnosticCode.GENERATION_ERROR,
                        f"OpenSourceCOBOL4J adapter error: {e}",
                    )),
                ),
            )

    def get_capabilities(self) -> tuple[ProducerCapability, ...]:
        return (
            ProducerCapability.SEQUENTIAL_FILES,
            ProducerCapability.INDEXED_FILES,
            ProducerCapability.RELATIVE_FILES,
            ProducerCapability.SORT_STATEMENTS,
            ProducerCapability.CALL_STATEMENTS,
        )

    def get_identity(self) -> tuple[str, str]:
        return (self.PRODUCER_IDENTITY, self.PRODUCER_VERSION)

    def get_runtime_requirements(self) -> tuple[str, ...]:
        return ("libcobj.jar",)  # COBOL-specific runtime required

    def _compute_hash(self, source: str) -> str:
        return hashlib.sha256(source.encode("utf-8")).hexdigest()
