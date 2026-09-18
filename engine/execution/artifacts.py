"""Real artifact capture for the validation engine.

Captures real filesystem/process output as evidence artifacts.
Every captured artifact has:
- artifact identity
- artifact type
- source execution
- content hash
- size
- provenance
- contract binding
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine.domain.identities import (
    ArtifactIdentity,
    ContentHash,
    ExecutionId,
)
from engine.evidence.models import ArtifactEvidence


@dataclass(frozen=True)
class CapturedArtifact:
    """A captured artifact with its content."""
    artifact: ArtifactIdentity
    content: bytes
    content_hash: ContentHash
    size_bytes: int
    execution_id: ExecutionId
    capture_time: str

    def to_evidence(self) -> ArtifactEvidence:
        return ArtifactEvidence(
            artifact=self.artifact,
            execution_id=self.execution_id,
            capture_time=self.capture_time,
            content_hash=self.content_hash,
            size_bytes=self.size_bytes,
        )


class ArtifactCapturer:
    """Captures real artifacts from execution output."""

    def capture_stdout(
        self,
        execution_id: ExecutionId,
        content: bytes,
        logical_name: str = "stdout",
        producer_role: str = "ORACLE",
    ) -> CapturedArtifact:
        content_hash = ContentHash.from_bytes(content)
        artifact = ArtifactIdentity(
            artifact_id=f"stdout-{execution_id.value}",
            artifact_type="STDOUT",
            logical_name=logical_name,
            producer_role=producer_role,
            content_hash=content_hash,
            size_bytes=len(content),
        )
        return CapturedArtifact(
            artifact=artifact,
            content=content,
            content_hash=content_hash,
            size_bytes=len(content),
            execution_id=execution_id,
            capture_time=datetime.now(timezone.utc).isoformat(),
        )

    def capture_stderr(
        self,
        execution_id: ExecutionId,
        content: bytes,
        logical_name: str = "stderr",
        producer_role: str = "ORACLE",
    ) -> CapturedArtifact:
        content_hash = ContentHash.from_bytes(content)
        artifact = ArtifactIdentity(
            artifact_id=f"stderr-{execution_id.value}",
            artifact_type="STDERR",
            logical_name=logical_name,
            producer_role=producer_role,
            content_hash=content_hash,
            size_bytes=len(content),
        )
        return CapturedArtifact(
            artifact=artifact,
            content=content,
            content_hash=content_hash,
            size_bytes=len(content),
            execution_id=execution_id,
            capture_time=datetime.now(timezone.utc).isoformat(),
        )

    def capture_exit_status(
        self,
        execution_id: ExecutionId,
        exit_code: int,
        producer_role: str = "ORACLE",
    ) -> CapturedArtifact:
        content = str(exit_code).encode()
        content_hash = ContentHash.from_bytes(content)
        artifact = ArtifactIdentity(
            artifact_id=f"exit-{execution_id.value}",
            artifact_type="EXIT_STATUS",
            logical_name="exit_status",
            producer_role=producer_role,
            content_hash=content_hash,
            size_bytes=len(content),
        )
        return CapturedArtifact(
            artifact=artifact,
            content=content,
            content_hash=content_hash,
            size_bytes=len(content),
            execution_id=execution_id,
            capture_time=datetime.now(timezone.utc).isoformat(),
        )

    def capture_text_file(
        self,
        execution_id: ExecutionId,
        file_path: str,
        logical_name: str,
        producer_role: str = "ORACLE",
    ) -> CapturedArtifact:
        content = Path(file_path).read_bytes()
        content_hash = ContentHash.from_bytes(content)
        artifact = ArtifactIdentity(
            artifact_id=f"text-{logical_name}-{execution_id.value}",
            artifact_type="TEXT_FILE",
            logical_name=logical_name,
            producer_role=producer_role,
            content_hash=content_hash,
            size_bytes=len(content),
        )
        return CapturedArtifact(
            artifact=artifact,
            content=content,
            content_hash=content_hash,
            size_bytes=len(content),
            execution_id=execution_id,
            capture_time=datetime.now(timezone.utc).isoformat(),
        )

    def capture_text_file_from_bytes(
        self,
        execution_id: ExecutionId,
        content: bytes,
        logical_name: str,
        producer_role: str = "ORACLE",
    ) -> CapturedArtifact:
        content_hash = ContentHash.from_bytes(content)
        artifact = ArtifactIdentity(
            artifact_id=f"text-{logical_name}-{execution_id.value}",
            artifact_type="TEXT_FILE",
            logical_name=logical_name,
            producer_role=producer_role,
            content_hash=content_hash,
            size_bytes=len(content),
        )
        return CapturedArtifact(
            artifact=artifact,
            content=content,
            content_hash=content_hash,
            size_bytes=len(content),
            execution_id=execution_id,
            capture_time=datetime.now(timezone.utc).isoformat(),
        )

    def capture_fixed_record(
        self,
        execution_id: ExecutionId,
        content: bytes,
        logical_name: str,
        producer_role: str = "ORACLE",
        record_length: int | None = None,
    ) -> CapturedArtifact:
        content_hash = ContentHash.from_bytes(content)

        record_count: int | None = None
        if record_length is not None and record_length > 0:
            if len(content) % record_length != 0:
                raise ValueError(
                    f"Content length {len(content)} not divisible by "
                    f"record_length {record_length}"
                )
            record_count = len(content) // record_length

        artifact = ArtifactIdentity(
            artifact_id=f"fixed-{logical_name}-{execution_id.value}",
            artifact_type="FIXED_RECORD",
            logical_name=logical_name,
            producer_role=producer_role,
            content_hash=content_hash,
            size_bytes=len(content),
            record_count=record_count,
        )
        return CapturedArtifact(
            artifact=artifact,
            content=content,
            content_hash=content_hash,
            size_bytes=len(content),
            execution_id=execution_id,
            capture_time=datetime.now(timezone.utc).isoformat(),
        )
