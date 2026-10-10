"""Schema-safe JSON persistence codec for control-plane records.

Replaces the previous ``pickle`` blobs.  Every persisted payload is an
explicit, versioned JSON document:

    {"schema": "<name>", "schema_version": 1, "payload": {...}}

Decoding validates the envelope, the schema version and every field type
before reconstructing a domain object; malformed, truncated, legacy-pickle,
unknown-schema or unsupported-version payloads raise
:class:`api.errors.PersistenceCorruptionError` (fail closed).  No arbitrary
object deserialization ever happens.

Properties of this codec:

* deterministic   — ``json.dumps(..., sort_keys=True)``
* explicit        — field-by-field mapping, no object graph walking
* inspectable     — the database stores readable JSON
* versioned       — ``schema`` + ``schema_version`` on every payload
* tamper evident  — evidence manifests carry their Phase A seal and the seal
                    is re-verified on load
* forward guarded — unknown schema versions are rejected, never guessed
"""

from __future__ import annotations

import json
from typing import Any, NoReturn

from api.errors import PersistenceCorruptionError, UnsupportedSchemaError
from engine.domain.identities import (
    ArtifactIdentity,
    CandidateIdentity,
    ContentHash,
    EnvironmentIdentity,
    ExecutionId,
    InputIdentity,
    OracleIdentity,
    RunId,
    SourceIdentity,
    VerdictState,
    WorkloadId,
)
from engine.evidence.models import (
    ArtifactEvidence,
    ComparisonEvidence,
    EvidenceManifest,
    ExecutionEvidence,
    VerdictEvidence,
)
from engine.verdict.derivation import Verdict

# ---------------------------------------------------------------------------
# Schema registry
# ---------------------------------------------------------------------------

SCHEMA_EVIDENCE = "evidence-manifest"
SCHEMA_VERDICT = "verdict"
SCHEMA_REPORT = "modernization-report"
SCHEMA_STR_LIST = "string-list"

#: Version 1 is the first JSON payload format (Phase B).  There are no
#: earlier supported versions: any other value is unsupported, not "old".
CURRENT_SCHEMA_VERSION = 1

_HEX = frozenset("0123456789abcdef")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _fail(message: str) -> NoReturn:
    raise PersistenceCorruptionError(message)


def _unsupported(message: str) -> NoReturn:
    raise UnsupportedSchemaError(message)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _expect_dict(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"{where} must be an object, got {type(value).__name__}")
    return value


def _expect_list(value: object, where: str) -> list:
    if not isinstance(value, list):
        _fail(f"{where} must be an array, got {type(value).__name__}")
    return value


def _missing(where: str) -> NoReturn:
    _fail(f"missing or null required field {where!r}")


def _expect_str(value: object, where: str, *, allow_empty: bool = False) -> str:
    if value is None:
        _missing(where)
    if not isinstance(value, str):
        _fail(f"{where} must be a string, got {type(value).__name__}")
    if not allow_empty and not value:
        _fail(f"{where} must not be empty")
    return value


def _expect_int(value: object, where: str) -> int:
    if value is None:
        _missing(where)
    if not _is_int(value):
        _fail(f"{where} must be an integer, got {type(value).__name__}")
    return value


def _expect_bool(value: object, where: str) -> bool:
    if value is None:
        _missing(where)
    if not isinstance(value, bool):
        _fail(f"{where} must be a boolean, got {type(value).__name__}")
    return value


def _opt_str(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return _expect_str(value, key)


def _opt_int(payload: dict, key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    return _expect_int(value, key)


def _opt_hash(payload: dict, key: str) -> ContentHash | None:
    value = payload.get(key)
    if value is None:
        return None
    return _parse_hash(value, key)


def _hash(payload: dict, key: str, where: str | None = None) -> ContentHash:
    """Read a required sha256 hash field (``where`` only labels errors)."""
    label = f"{where}.{key}" if where else key
    if key not in payload or payload[key] is None:
        _fail(f"{label} is required")
    return _parse_hash(payload[key], label)


def _parse_hash(value: object, where: str) -> ContentHash:
    text = _expect_str(value, where)
    digest = text[len("sha256:"):] if text.startswith("sha256:") else text
    if len(digest) != 64 or not _HEX.issuperset(digest):
        _fail(f"{where} is not a sha256 digest")
    return ContentHash(digest=digest)


def _hash_map(value: object, where: str) -> dict[str, ContentHash]:
    raw = _expect_dict(value, where)
    out: dict[str, ContentHash] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            _fail(f"{where} keys must be strings")
        out[key] = _parse_hash(item, f"{where}.{key}")
    return out


def _str_list(value: object, where: str) -> tuple[str, ...]:
    raw = _expect_list(value, where)
    for item in raw:
        if not isinstance(item, str):
            _fail(f"{where} entries must be strings")
    return tuple(raw)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _encode_envelope(schema: str, payload: dict) -> bytes:
    document = {
        "schema": schema,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "payload": payload,
    }
    try:
        # ``default=str`` mirrors the engine's canonical graph hashing so
        # JSON round-trips keep the same textual form for exotic values.
        return json.dumps(document, sort_keys=True, default=str).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PersistenceCorruptionError(
            f"payload for schema {schema!r} is not JSON-serializable: {exc}"
        ) from None


def _decode_envelope(raw: object, expected_schema: str) -> dict | None:
    """Validate the envelope and return the payload (``None`` for no value)."""
    if raw is None:
        return None
    if isinstance(raw, memoryview):
        raw = bytes(raw)
    if not isinstance(raw, (bytes, bytearray)):
        _fail("persisted payload must be bytes")

    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        # Pickle protocol headers are not valid UTF-8; legacy payloads are
        # rejected here instead of being deserialized.
        _fail("persisted payload is not UTF-8 JSON (legacy or corrupted)")

    try:
        document = json.loads(text)
    except ValueError:
        _fail("persisted payload is not valid JSON")

    doc = _expect_dict(document, "persisted payload")
    schema = doc.get("schema")
    if schema != expected_schema:
        _fail(
            f"unexpected persisted schema {schema!r}, expected {expected_schema!r}"
        )
    version = doc.get("schema_version")
    if not _is_int(version):
        _fail("persisted payload has no integer schema_version")
    if version != CURRENT_SCHEMA_VERSION:
        _unsupported(
            f"unsupported persisted schema version {version} "
            f"(supported: {CURRENT_SCHEMA_VERSION})"
        )
    return _expect_dict(doc.get("payload"), "payload")


# ---------------------------------------------------------------------------
# Evidence manifest
# ---------------------------------------------------------------------------

def _identity_to_dict(source: SourceIdentity) -> dict:
    return {
        "source_id": source.source_id,
        "source_hash": str(source.source_hash),
        "file_count": source.file_count,
        "total_size_bytes": source.total_size_bytes,
    }


def _candidate_to_dict(candidate: CandidateIdentity) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "candidate_hash": str(candidate.candidate_hash),
        "source_hash": str(candidate.source_hash),
        "file_count": candidate.file_count,
        "total_size_bytes": candidate.total_size_bytes,
    }


def _oracle_to_dict(oracle: OracleIdentity) -> dict:
    return {
        "oracle_id": oracle.oracle_id,
        "image_digest": oracle.image_digest,
        "compiler_version": oracle.compiler_version,
        "preprocessor_version": oracle.preprocessor_version,
        "base_image": oracle.base_image,
    }


def encode_evidence_manifest(manifest: EvidenceManifest) -> bytes:
    """Serialize a full evidence manifest (all graph fields) to JSON bytes."""
    if not isinstance(manifest, EvidenceManifest):
        raise PersistenceCorruptionError(
            f"refusing to persist evidence of type {type(manifest).__name__}"
        )
    payload: dict[str, Any] = {
        "manifest_version": manifest.manifest_version,
        "run_id": manifest.run_id.value,
        "workload_id": manifest.workload_id.value,
        "source_identity": _identity_to_dict(manifest.source_identity),
        "candidate_identity": (
            _candidate_to_dict(manifest.candidate_identity)
            if manifest.candidate_identity is not None else None
        ),
        "oracle_identity": _oracle_to_dict(manifest.oracle_identity),
        "environment_identities": [
            {
                "runtime_id": env.runtime_id,
                "java_version": env.java_version,
                "cobol_compiler": env.cobol_compiler,
                "os_base": env.os_base,
                "network_policy": env.network_policy,
                "resource_limits": dict(env.resource_limits),
            }
            for env in manifest.environment_identities
        ],
        "controlled_input": {
            "input_id": manifest.controlled_input.input_id,
            "stdin_hash": (
                str(manifest.controlled_input.stdin_hash)
                if manifest.controlled_input.stdin_hash is not None else None
            ),
            "input_files": {
                key: str(value)
                for key, value in manifest.controlled_input.input_files.items()
            },
        },
        "execution_evidence": [e.to_dict() for e in manifest.execution_evidence],
        "artifact_evidence": [
            {
                # Nested identity keeps the artifact's own content hash,
                # size and record count (the engine's flat to_dict() drops
                # them because the canonical graph uses the evidence-level
                # values instead).
                "artifact": {
                    "artifact_id": a.artifact.artifact_id,
                    "artifact_type": a.artifact.artifact_type,
                    "logical_name": a.artifact.logical_name,
                    "producer_role": a.artifact.producer_role,
                    "content_hash": str(a.artifact.content_hash),
                    "size_bytes": a.artifact.size_bytes,
                    "record_count": a.artifact.record_count,
                },
                "execution_id": a.execution_id.value,
                "capture_time": a.capture_time,
                "content_hash": str(a.content_hash),
                "size_bytes": a.size_bytes,
                "record_count": a.record_count,
            }
            for a in manifest.artifact_evidence
        ],
        "comparison_evidence": [
            {
                # to_dict() omits content_hash, which the canonical evidence
                # graph (and therefore the seal) covers — add it explicitly.
                **c.to_dict(),
                "content_hash": str(c.content_hash),
            }
            for c in manifest.comparison_evidence
        ],
        "verdict_evidence": (
            manifest.verdict_evidence.to_dict()
            if manifest.verdict_evidence is not None else None
        ),
        "created_at": manifest.created_at,
        "sealed_hash": (
            str(manifest.sealed_hash) if manifest.sealed_hash is not None else None
        ),
    }
    return _encode_envelope(SCHEMA_EVIDENCE, payload)


def _decode_execution(raw: object, index: int) -> ExecutionEvidence:
    where = f"execution_evidence[{index}]"
    item = _expect_dict(raw, where)
    generated = item.get("generated_files", {})
    compilation = item.get("compilation_diagnostics")
    if compilation is not None:
        compilation = _expect_dict(compilation, f"{where}.compilation_diagnostics")
        for key, value in compilation.items():
            if not isinstance(key, str) or not isinstance(value, str):
                _fail(f"{where}.compilation_diagnostics must map strings")
    workload_id = item.get("workload_id")
    if workload_id is not None:
        workload_id = _expect_str(workload_id, f"{where}.workload_id")
    timeout_duration = item.get("timeout_duration")
    if timeout_duration is not None:
        timeout_duration = _expect_int(timeout_duration, f"{where}.timeout_duration")
    exit_code = item.get("exit_code")
    if exit_code is not None:
        exit_code = _expect_int(exit_code, f"{where}.exit_code")
    return ExecutionEvidence(
        execution_id=ExecutionId(_expect_str(item.get("execution_id"), f"{where}.execution_id")),
        run_id=RunId(_expect_str(item.get("run_id"), f"{where}.run_id")),
        runtime_id=_expect_str(item.get("runtime_id"), f"{where}.runtime_id"),
        command=_expect_str(item.get("command"), f"{where}.command", allow_empty=True),
        working_directory=_expect_str(
            item.get("working_directory"), f"{where}.working_directory", allow_empty=True
        ),
        environment_variables=_expect_dict(
            item.get("environment_variables"), f"{where}.environment_variables"
        ),
        start_time=_expect_str(item.get("start_time"), f"{where}.start_time", allow_empty=True),
        end_time=_expect_str(item.get("end_time"), f"{where}.end_time", allow_empty=True),
        exit_code=exit_code,
        stdout_hash=_hash(item, "stdout_hash", where),
        stderr_hash=_hash(item, "stderr_hash", where),
        generated_files=_hash_map(generated, f"{where}.generated_files"),
        source_tree_hash_before=_hash(item, "source_tree_hash_before", where),
        source_tree_hash_after=_hash(item, "source_tree_hash_after", where),
        termination_status=_expect_str(
            item.get("termination_status"), f"{where}.termination_status"
        ),
        timeout_applied=_expect_bool(
            item.get("timeout_applied"), f"{where}.timeout_applied"
        ),
        timeout_duration=timeout_duration,
        compilation_diagnostics=compilation,
        workload_id=WorkloadId(workload_id) if workload_id else None,
        image_digest=_opt_str(item, "image_digest"),
        execution_phase=_expect_str(
            item.get("execution_phase", "EXECUTE"), f"{where}.execution_phase"
        ),
    )


def _decode_artifact(raw: object, index: int) -> ArtifactEvidence:
    where = f"artifact_evidence[{index}]"
    item = _expect_dict(raw, where)
    record_count = item.get("record_count")
    if record_count is not None:
        record_count = _expect_int(record_count, f"{where}.record_count")
    identity_raw = _expect_dict(item.get("artifact"), f"{where}.artifact")
    artifact_record_count = identity_raw.get("record_count")
    if artifact_record_count is not None:
        artifact_record_count = _expect_int(
            artifact_record_count, f"{where}.artifact.record_count"
        )
    identity = ArtifactIdentity(
        artifact_id=_expect_str(
            identity_raw.get("artifact_id"), f"{where}.artifact.artifact_id"
        ),
        artifact_type=_expect_str(
            identity_raw.get("artifact_type"), f"{where}.artifact.artifact_type"
        ),
        logical_name=_expect_str(
            identity_raw.get("logical_name"),
            f"{where}.artifact.logical_name",
            allow_empty=True,
        ),
        producer_role=_expect_str(
            identity_raw.get("producer_role"), f"{where}.artifact.producer_role"
        ),
        content_hash=_hash(identity_raw, "content_hash", f"{where}.artifact"),
        size_bytes=_expect_int(
            identity_raw.get("size_bytes"), f"{where}.artifact.size_bytes"
        ),
        record_count=artifact_record_count,
    )
    return ArtifactEvidence(
        artifact=identity,
        execution_id=ExecutionId(_expect_str(item.get("execution_id"), f"{where}.execution_id")),
        capture_time=_expect_str(item.get("capture_time"), f"{where}.capture_time", allow_empty=True),
        content_hash=_hash(item, "content_hash", where),
        size_bytes=_expect_int(item.get("size_bytes"), f"{where}.size_bytes"),
        record_count=record_count,
    )


def _decode_comparison(raw: object, index: int) -> ComparisonEvidence:
    where = f"comparison_evidence[{index}]"
    item = _expect_dict(raw, where)
    field_results = _expect_list(
        item.get("field_level_results"), f"{where}.field_level_results"
    )
    for entry in field_results:
        _expect_dict(entry, f"{where}.field_level_results entry")
    workload_id = item.get("workload_id")
    if workload_id is not None:
        workload_id = _expect_str(workload_id, f"{where}.workload_id")
    return ComparisonEvidence(
        comparison_id=_expect_str(item.get("comparison_id"), f"{where}.comparison_id"),
        run_id=RunId(_expect_str(item.get("run_id"), f"{where}.run_id")),
        comparator_id=_expect_str(item.get("comparator_id"), f"{where}.comparator_id"),
        comparator_version=_expect_str(
            item.get("comparator_version"), f"{where}.comparator_version", allow_empty=True
        ),
        oracle_artifact_id=_expect_str(
            item.get("oracle_artifact_id"), f"{where}.oracle_artifact_id"
        ),
        candidate_artifact_id=_expect_str(
            item.get("candidate_artifact_id"), f"{where}.candidate_artifact_id"
        ),
        artifact_type=_expect_str(item.get("artifact_type"), f"{where}.artifact_type"),
        result=_expect_str(item.get("result"), f"{where}.result"),
        normalization_applied=_str_list(
            item.get("normalization_applied"), f"{where}.normalization_applied"
        ),
        differences=_str_list(item.get("differences"), f"{where}.differences"),
        field_level_results=tuple(field_results),
        content_hash=_hash(item, "content_hash", where),
        ordering_applied=_expect_str(
            item.get("ordering_applied", "SEQUENTIAL"), f"{where}.ordering_applied"
        ),
        failure_policy=_expect_str(
            item.get("failure_policy", ""), f"{where}.failure_policy", allow_empty=True
        ),
        workload_id=WorkloadId(workload_id) if workload_id else None,
    )


def _decode_verdict_evidence(raw: object) -> VerdictEvidence | None:
    if raw is None:
        return None
    where = "verdict_evidence"
    item = _expect_dict(raw, where)
    return VerdictEvidence(
        run_id=RunId(_expect_str(item.get("run_id"), f"{where}.run_id")),
        workload_id=WorkloadId(_expect_str(item.get("workload_id"), f"{where}.workload_id")),
        verdict_state=_expect_str(item.get("verdict_state"), f"{where}.verdict_state"),
        executed_check_count=_expect_int(
            item.get("executed_check_count"), f"{where}.executed_check_count"
        ),
        skipped_count=_expect_int(item.get("skipped_count"), f"{where}.skipped_count"),
        unavailable_count=_expect_int(
            item.get("unavailable_count"), f"{where}.unavailable_count"
        ),
        supported_scope_statement=_expect_str(
            item.get("supported_scope_statement"),
            f"{where}.supported_scope_statement",
            allow_empty=True,
        ),
        evidence_manifest_hash=_parse_hash(
            item.get("evidence_manifest_hash"), f"{where}.evidence_manifest_hash"
        ),
        derivation_timestamp=_expect_str(
            item.get("derivation_timestamp"), f"{where}.derivation_timestamp"
        ),
    )


def decode_evidence_manifest(raw: object) -> EvidenceManifest | None:
    """Decode and seal-verify a persisted evidence manifest.

    Returns ``None`` when nothing was persisted.  Any structural deviation,
    unsupported version or seal mismatch raises
    :class:`PersistenceCorruptionError`.
    """
    payload = _decode_envelope(raw, SCHEMA_EVIDENCE)
    if payload is None:
        return None

    source_raw = _expect_dict(payload.get("source_identity"), "source_identity")
    candidate_raw = payload.get("candidate_identity")
    if candidate_raw is not None:
        candidate_raw = _expect_dict(candidate_raw, "candidate_identity")
    oracle_raw = _expect_dict(payload.get("oracle_identity"), "oracle_identity")
    controlled_raw = _expect_dict(payload.get("controlled_input"), "controlled_input")

    environments: list[EnvironmentIdentity] = []
    for index, raw_env in enumerate(
        _expect_list(payload.get("environment_identities"), "environment_identities")
    ):
        where = f"environment_identities[{index}]"
        env = _expect_dict(raw_env, where)
        limits = _expect_dict(env.get("resource_limits", {}), f"{where}.resource_limits")
        for key, value in limits.items():
            if not isinstance(key, str) or not isinstance(value, str):
                _fail(f"{where}.resource_limits must map strings")
        environments.append(
            EnvironmentIdentity(
                runtime_id=_expect_str(env.get("runtime_id"), f"{where}.runtime_id"),
                java_version=_opt_str(env, "java_version"),
                cobol_compiler=_opt_str(env, "cobol_compiler"),
                os_base=_opt_str(env, "os_base"),
                network_policy=_expect_str(
                    env.get("network_policy", "none"), f"{where}.network_policy"
                ),
                resource_limits=dict(limits),
            )
        )

    executions = tuple(
        _decode_execution(item, index)
        for index, item in enumerate(
            _expect_list(payload.get("execution_evidence"), "execution_evidence")
        )
    )
    artifacts = tuple(
        _decode_artifact(item, index)
        for index, item in enumerate(
            _expect_list(payload.get("artifact_evidence"), "artifact_evidence")
        )
    )
    comparisons = tuple(
        _decode_comparison(item, index)
        for index, item in enumerate(
            _expect_list(payload.get("comparison_evidence"), "comparison_evidence")
        )
    )

    stdin_hash = controlled_raw.get("stdin_hash")
    if stdin_hash is not None:
        stdin_hash = _parse_hash(stdin_hash, "controlled_input.stdin_hash")
    controlled_files = controlled_raw.get("input_files", {})
    controlled = InputIdentity(
        input_id=_expect_str(controlled_raw.get("input_id"), "controlled_input.input_id"),
        stdin_hash=stdin_hash,
        input_files=_hash_map(controlled_files, "controlled_input.input_files"),
    )

    seal = payload.get("sealed_hash")
    if not isinstance(seal, str) or not seal:
        _fail("persisted evidence manifest has no seal")

    try:
        manifest = EvidenceManifest(
            manifest_version=_expect_str(payload.get("manifest_version"), "manifest_version"),
            run_id=RunId(_expect_str(payload.get("run_id"), "run_id")),
            workload_id=WorkloadId(_expect_str(payload.get("workload_id"), "workload_id")),
            source_identity=SourceIdentity(
                source_id=_expect_str(source_raw.get("source_id"), "source_identity.source_id"),
                source_hash=_hash(source_raw, "source_hash", "source_identity"),
                file_count=_expect_int(
                    source_raw.get("file_count"), "source_identity.file_count"
                ),
                total_size_bytes=_expect_int(
                    source_raw.get("total_size_bytes"), "source_identity.total_size_bytes"
                ),
            ),
            candidate_identity=(
                CandidateIdentity(
                    candidate_id=_expect_str(
                        candidate_raw.get("candidate_id"), "candidate_identity.candidate_id"
                    ),
                    candidate_hash=_hash(candidate_raw, "candidate_hash", "candidate_identity"),
                    source_hash=_hash(candidate_raw, "source_hash", "candidate_identity"),
                    file_count=_expect_int(
                        candidate_raw.get("file_count"), "candidate_identity.file_count"
                    ),
                    total_size_bytes=_expect_int(
                        candidate_raw.get("total_size_bytes"),
                        "candidate_identity.total_size_bytes",
                    ),
                )
                if candidate_raw is not None else None
            ),
            oracle_identity=OracleIdentity(
                oracle_id=_expect_str(oracle_raw.get("oracle_id"), "oracle_identity.oracle_id"),
                image_digest=_expect_str(
                    oracle_raw.get("image_digest"), "oracle_identity.image_digest"
                ),
                compiler_version=_expect_str(
                    oracle_raw.get("compiler_version"), "oracle_identity.compiler_version"
                ),
                preprocessor_version=_opt_str(oracle_raw, "preprocessor_version"),
                base_image=_opt_str(oracle_raw, "base_image"),
            ),
            environment_identities=tuple(environments),
            controlled_input=controlled,
            execution_evidence=executions,
            artifact_evidence=artifacts,
            comparison_evidence=comparisons,
            verdict_evidence=_decode_verdict_evidence(payload.get("verdict_evidence")),
            created_at=_expect_str(payload.get("created_at"), "created_at"),
        )
    except PersistenceCorruptionError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        _fail(f"persisted evidence manifest is malformed: {exc}")

    # Phase A seal re-verification: any in-place modification of the
    # persisted evidence graph is detected here (fail closed).
    if manifest.sealed_hash is None or str(manifest.sealed_hash) != seal:
        _fail("persisted evidence seal mismatch (evidence was modified)")
    return manifest


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

_VERDICT_FIELDS = (
    "state",
    "workload_id",
    "run_id",
    "source_hash",
    "candidate_hash",
    "oracle_id",
    "oracle_digest",
    "executed_check_count",
    "skipped_count",
    "unavailable_count",
    "supported_scope_statement",
    "evidence_manifest_hash",
    "derivation_timestamp",
    "differences",
)


def encode_verdict(verdict: Verdict) -> bytes:
    """Serialize a verdict to an explicit JSON document."""
    if not isinstance(verdict, Verdict):
        raise PersistenceCorruptionError(
            f"refusing to persist verdict of type {type(verdict).__name__}"
        )
    payload: dict[str, Any] = {
        "state": verdict.state.value,
        "workload_id": verdict.workload_id.value,
        "run_id": verdict.run_id,
        "source_hash": verdict.source_hash,
        "candidate_hash": verdict.candidate_hash,
        "oracle_id": verdict.oracle_id,
        "oracle_digest": verdict.oracle_digest,
        "executed_check_count": verdict.executed_check_count,
        "skipped_count": verdict.skipped_count,
        "unavailable_count": verdict.unavailable_count,
        "supported_scope_statement": verdict.supported_scope_statement,
        "evidence_manifest_hash": verdict.evidence_manifest_hash,
        "derivation_timestamp": verdict.derivation_timestamp,
        "differences": list(verdict.differences),
    }
    return _encode_envelope(SCHEMA_VERDICT, payload)


def decode_verdict(raw: object) -> Verdict | None:
    """Decode a persisted verdict, rejecting unknown states or missing fields."""
    payload = _decode_envelope(raw, SCHEMA_VERDICT)
    if payload is None:
        return None

    missing = [key for key in _VERDICT_FIELDS if key not in payload]
    if missing:
        _fail(f"persisted verdict is missing fields: {', '.join(missing)}")

    state_raw = _expect_str(payload.get("state"), "state")
    try:
        state = VerdictState(state_raw)
    except ValueError:
        _fail(f"persisted verdict state {state_raw!r} is not a valid verdict state")

    candidate_hash = payload.get("candidate_hash")
    if candidate_hash is not None:
        candidate_hash = _expect_str(candidate_hash, "candidate_hash")

    try:
        return Verdict(
            state=state,
            workload_id=WorkloadId(_expect_str(payload.get("workload_id"), "workload_id")),
            run_id=_expect_str(payload.get("run_id"), "run_id"),
            source_hash=_expect_str(payload.get("source_hash"), "source_hash"),
            candidate_hash=candidate_hash,
            oracle_id=_expect_str(payload.get("oracle_id"), "oracle_id"),
            oracle_digest=_expect_str(payload.get("oracle_digest"), "oracle_digest"),
            executed_check_count=_expect_int(
                payload.get("executed_check_count"), "executed_check_count"
            ),
            skipped_count=_expect_int(payload.get("skipped_count"), "skipped_count"),
            unavailable_count=_expect_int(
                payload.get("unavailable_count"), "unavailable_count"
            ),
            supported_scope_statement=_expect_str(
                payload.get("supported_scope_statement"),
                "supported_scope_statement",
                allow_empty=True,
            ),
            evidence_manifest_hash=_expect_str(
                payload.get("evidence_manifest_hash"), "evidence_manifest_hash"
            ),
            derivation_timestamp=_expect_str(
                payload.get("derivation_timestamp"), "derivation_timestamp"
            ),
            differences=_str_list(payload.get("differences"), "differences"),
        )
    except PersistenceCorruptionError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        _fail(f"persisted verdict is malformed: {exc}")


# ---------------------------------------------------------------------------
# Modernization report (plain JSON document)
# ---------------------------------------------------------------------------

def encode_report(report: dict | None) -> bytes | None:
    if report is None:
        return None
    if not isinstance(report, dict):
        raise PersistenceCorruptionError(
            f"refusing to persist report of type {type(report).__name__}"
        )
    return _encode_envelope(SCHEMA_REPORT, {"report": report})


def decode_report(raw: object) -> dict | None:
    payload = _decode_envelope(raw, SCHEMA_REPORT)
    if payload is None:
        return None
    report = payload.get("report")
    if not isinstance(report, dict):
        _fail("persisted modernization report must be an object")
    return report


# ---------------------------------------------------------------------------
# String tuple columns (applications)
# ---------------------------------------------------------------------------

def encode_str_list(values: tuple[str, ...] | list[str] | None) -> str:
    cleaned: list[str] = []
    for value in values or ():
        if not isinstance(value, str):
            raise PersistenceCorruptionError(
                f"refusing to persist non-string list entry {type(value).__name__}"
            )
        cleaned.append(value)
    return json.dumps(cleaned)


def decode_str_list(raw: object) -> tuple[str, ...]:
    """Decode a JSON string-array column; malformed data fails closed."""
    if raw is None:
        return ()
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            _fail("string list column is not UTF-8")
    if not isinstance(raw, str):
        _fail(f"string list column must be text, got {type(raw).__name__}")
    if not raw.strip():
        _fail("string list column is empty")
    try:
        items = json.loads(raw)
    except ValueError:
        _fail("string list column is not valid JSON")
    if not isinstance(items, list):
        _fail("string list column must contain a JSON array")
    for item in items:
        if not isinstance(item, str):
            _fail("string list column entries must be strings")
    return tuple(items)
