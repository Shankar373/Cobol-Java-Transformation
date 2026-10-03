"""Immutable Docker image provenance contract.

This module defines the single identity-resolution contract used for locally
built and registry-pulled Docker images.

Precedence and failure behavior:

- When Docker reports one or more syntactically valid registry RepoDigests,
  the first valid RepoDigest is the image identity.
- When no valid RepoDigest exists, a syntactically valid local Image ID is
  the image identity. This is the auditable fallback for images built locally
  and never pushed to a registry.
- Any other result has no identity and must fail closed.
- Runtime execution images additionally require a RepoDigest identity. A bare
  Image ID is never sufficient for the runtime role.
- Expected and observed identities are compared exactly. Floating tags are
  never accepted as proof of identity.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "1.0"
DEFAULT_PROVENANCE_PATH = Path("test-artifacts/docker-image-provenance.json")

REPO_DIGEST = "repo-digest"
IMAGE_ID = "image-id"
UNKNOWN_IDENTITY = "unknown"

_IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$", re.IGNORECASE)
_REPO_DIGEST_PATTERN = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$", re.IGNORECASE)

DockerRunner = Callable[..., subprocess.CompletedProcess]


def is_image_id(value: str) -> bool:
    """Return whether a value has immutable Image ID syntax."""
    return bool(_IMAGE_ID_PATTERN.match((value or "").strip()))


def is_repo_digest(value: str) -> bool:
    """Return whether a value has immutable registry RepoDigest syntax."""
    return bool(_REPO_DIGEST_PATTERN.match((value or "").strip()))


def _select_identity(
    repo_digests: tuple[str, ...], image_id: str
) -> tuple[str, str]:
    """Select RepoDigest evidence first, then a valid local Image ID."""
    valid_digests = tuple(value for value in repo_digests if is_repo_digest(value))
    if valid_digests:
        return valid_digests[0], REPO_DIGEST
    normalized_image_id = (image_id or "").strip()
    if is_image_id(normalized_image_id):
        return normalized_image_id, IMAGE_ID
    return "", UNKNOWN_IDENTITY


@dataclass(frozen=True)
class DockerImageObservation:
    """Raw Docker identity evidence for one requested image reference."""

    requested_ref: str
    repo_digests: tuple[str, ...] = ()
    image_id: str = ""

    @property
    def valid_repo_digests(self) -> tuple[str, ...]:
        """RepoDigests with valid immutable syntax, preserving Docker order."""
        return tuple(value for value in self.repo_digests if is_repo_digest(value))

    @property
    def valid_image_id(self) -> str:
        """The local Image ID when it has valid immutable syntax."""
        return self.image_id if is_image_id(self.image_id) else ""

    @property
    def identity_kind(self) -> str:
        """Kind of selected identity: repo-digest, image-id, or unknown."""
        return _select_identity(self.repo_digests, self.image_id)[1]

    @property
    def identity(self) -> str:
        """Preferred immutable identity: RepoDigest first, then Image ID."""
        return _select_identity(self.repo_digests, self.image_id)[0]

    @property
    def is_complete(self) -> bool:
        """Whether Docker supplied a usable immutable identity."""
        return self.identity != ""

    def to_dict(self) -> dict[str, Any]:
        """Return an auditable representation of this observation."""
        return {
            "requested_ref": self.requested_ref,
            "repo_digests": list(self.repo_digests),
            "image_id": self.image_id,
            "identity_kind": self.identity_kind,
            "identity": self.identity,
        }


def observation_from_inspect(
    payload: Mapping[str, Any] | None,
    requested_ref: str,
) -> DockerImageObservation:
    """Parse one `docker image inspect` object without accepting tags."""
    if not isinstance(payload, Mapping):
        return DockerImageObservation(requested_ref=requested_ref)

    raw_digests = payload.get("RepoDigests", ())
    if isinstance(raw_digests, str):
        digest_values = (raw_digests,)
    elif isinstance(raw_digests, Sequence) and not isinstance(raw_digests, (bytes, bytearray)):
        digest_values = tuple(
            value.strip() for value in raw_digests if isinstance(value, str)
        )
    else:
        digest_values = ()

    raw_image_id = payload.get("Id", "")
    image_id = raw_image_id.strip() if isinstance(raw_image_id, str) else ""

    return DockerImageObservation(
        requested_ref=requested_ref,
        repo_digests=digest_values,
        image_id=image_id,
    )


def resolve_docker_image_identity(
    image_ref: str,
    runner: DockerRunner = subprocess.run,
) -> DockerImageObservation:
    """Resolve an immutable identity for a local Docker image reference."""
    requested_ref = (image_ref or "").strip()
    if not requested_ref:
        return DockerImageObservation(requested_ref=requested_ref)

    try:
        result = runner(
            ["docker", "image", "inspect", requested_ref],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return DockerImageObservation(requested_ref=requested_ref)

    if getattr(result, "returncode", 1) != 0:
        return DockerImageObservation(requested_ref=requested_ref)

    stdout = getattr(result, "stdout", b"")
    if isinstance(stdout, (bytes, bytearray)):
        text = bytes(stdout).decode(errors="replace")
    elif isinstance(stdout, str):
        text = stdout
    else:
        return DockerImageObservation(requested_ref=requested_ref)

    try:
        payload = json.loads(text)
    except ValueError:
        return DockerImageObservation(requested_ref=requested_ref)

    if isinstance(payload, list):
        if not payload:
            return DockerImageObservation(requested_ref=requested_ref)
        payload = payload[0]

    return observation_from_inspect(payload, requested_ref)


def verify_image_identity(
    *,
    expected_identity: str,
    observed: DockerImageObservation,
    require_repo_digest: bool,
) -> bool:
    """Exactly compare an expected immutable identity with Docker evidence."""
    expected = (expected_identity or "").strip()
    if not expected or not observed.identity:
        return False
    if require_repo_digest and observed.identity_kind != REPO_DIGEST:
        return False
    return observed.identity == expected


@dataclass(frozen=True)
class DockerImageProvenance:
    """Auditable expected identities for one Docker deployment."""

    contract_version: str = CONTRACT_VERSION
    build_image: str = ""
    build_identity: str = ""
    build_identity_kind: str = UNKNOWN_IDENTITY
    build_repo_digests: tuple[str, ...] = ()
    build_image_id: str = ""
    runtime_image: str = ""
    runtime_identity: str = ""
    runtime_identity_kind: str = UNKNOWN_IDENTITY
    runtime_repo_digests: tuple[str, ...] = ()
    runtime_image_id: str = ""
    recorded_at: str = ""
    source_path: str = ""

    def validate(self) -> list[str]:
        """Return contract violations; an empty list means the record is valid."""
        violations: list[str] = []
        if self.contract_version != CONTRACT_VERSION:
            violations.append(f"unsupported contract version: {self.contract_version!r}")
        if not self.build_image.strip():
            violations.append("build_image is required")
        selected_build, selected_build_kind = _select_identity(
            self.build_repo_digests, self.build_image_id
        )
        if not selected_build:
            violations.append("build evidence contains no usable immutable identity")
        elif (
            self.build_identity.strip() != selected_build
            or self.build_identity_kind != selected_build_kind
        ):
            violations.append("build_identity does not match build evidence")
        if not self.runtime_image.strip():
            violations.append("runtime_image is required")
        selected_runtime, selected_runtime_kind = _select_identity(
            self.runtime_repo_digests, self.runtime_image_id
        )
        if selected_runtime_kind != REPO_DIGEST:
            violations.append("runtime evidence contains no RepoDigest identity")
        elif (
            self.runtime_identity.strip() != selected_runtime
            or self.runtime_identity_kind != selected_runtime_kind
        ):
            violations.append("runtime_identity does not match runtime evidence")
        return violations

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable auditable provenance record."""
        return {
            "contract_version": self.contract_version,
            "build_image": self.build_image,
            "build_identity": self.build_identity,
            "build_identity_kind": self.build_identity_kind,
            "build_repo_digests": list(self.build_repo_digests),
            "build_image_id": self.build_image_id,
            "runtime_image": self.runtime_image,
            "runtime_identity": self.runtime_identity,
            "runtime_identity_kind": self.runtime_identity_kind,
            "runtime_repo_digests": list(self.runtime_repo_digests),
            "runtime_image_id": self.runtime_image_id,
            "recorded_at": self.recorded_at,
            "source_path": self.source_path,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DockerImageProvenance:
        """Parse and validate a provenance record; fail closed on bad input."""
        if not isinstance(data, Mapping):
            raise ValueError("Docker image provenance must be a JSON object")

        def _text(name: str) -> str:
            value = data.get(name, "")
            if not isinstance(value, str):
                raise ValueError(f"Docker image provenance field {name!r} must be text")
            return value

        def _texts(name: str) -> tuple[str, ...]:
            value = data.get(name, ())
            if isinstance(value, str):
                return (value,)
            if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
                items = tuple(item for item in value if isinstance(item, str))
                if len(items) != len(tuple(value)):
                    raise ValueError(
                        f"Docker image provenance field {name!r} must contain text"
                    )
                return items
            raise ValueError(f"Docker image provenance field {name!r} must be a list")

        provenance = cls(
            contract_version=_text("contract_version"),
            build_image=_text("build_image"),
            build_identity=_text("build_identity"),
            build_identity_kind=_text("build_identity_kind"),
            build_repo_digests=_texts("build_repo_digests"),
            build_image_id=_text("build_image_id"),
            runtime_image=_text("runtime_image"),
            runtime_identity=_text("runtime_identity"),
            runtime_identity_kind=_text("runtime_identity_kind"),
            runtime_repo_digests=_texts("runtime_repo_digests"),
            runtime_image_id=_text("runtime_image_id"),
            recorded_at=_text("recorded_at"),
            source_path=_text("source_path"),
        )
        violations = provenance.validate()
        if violations:
            raise ValueError("; ".join(violations))
        return provenance


def record_adapter_provenance(
    *,
    build_image: str,
    runtime_image: str,
    expected_runtime_digest: str,
    runner: DockerRunner = subprocess.run,
    recorded_at: str | None = None,
) -> DockerImageProvenance:
    """Record auditable identities using the same resolver as the adapter."""
    build_observation = resolve_docker_image_identity(build_image, runner=runner)
    if not build_observation.is_complete:
        raise ValueError(f"No immutable identity found for build image {build_image!r}")

    runtime_observation = resolve_docker_image_identity(runtime_image, runner=runner)
    if runtime_observation.identity_kind != REPO_DIGEST:
        raise ValueError(f"Runtime image {runtime_image!r} has no RepoDigest identity")
    if runtime_observation.identity != (expected_runtime_digest or "").strip():
        raise ValueError(
            f"Runtime image {runtime_image!r} does not match the expected digest"
        )

    timestamp = recorded_at
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    return DockerImageProvenance(
        build_image=build_observation.requested_ref,
        build_identity=build_observation.identity,
        build_identity_kind=build_observation.identity_kind,
        build_repo_digests=build_observation.repo_digests,
        build_image_id=build_observation.image_id,
        runtime_image=runtime_observation.requested_ref,
        runtime_identity=runtime_observation.identity,
        runtime_identity_kind=runtime_observation.identity_kind,
        runtime_repo_digests=runtime_observation.repo_digests,
        runtime_image_id=runtime_observation.image_id,
        recorded_at=timestamp,
        source_path="docker-image-provenance",
    )


def write_adapter_provenance(provenance: DockerImageProvenance, path: str | Path) -> Path:
    """Write a validated provenance record for CI and local verification."""
    violations = provenance.validate()
    if violations:
        raise ValueError("; ".join(violations))
    output_path = Path(path)
    if output_path.parent != Path(""):
        output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(provenance.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def load_adapter_provenance(path: str | Path = DEFAULT_PROVENANCE_PATH) -> DockerImageProvenance:
    """Load a validated provenance record; fail closed on missing/bad input."""
    provenance_path = Path(path)
    try:
        data = json.loads(provenance_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            f"Docker image provenance not found at {provenance_path}: "
            "record exact image identities before verifying them"
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"Unable to read Docker image provenance at {provenance_path}: {exc}"
        ) from exc
    except ValueError as exc:
        raise ValueError(
            f"Invalid Docker image provenance at {provenance_path}: {exc}"
        ) from exc
    return DockerImageProvenance.from_dict(data)
