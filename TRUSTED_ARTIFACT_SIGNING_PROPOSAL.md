# Trusted Artifact Signing — Technical Proposal and Owner Decision Record

Date: 2026-10-30
Status: BLOCKED on owner decision for key custody and production policy. Safe preparatory work only.

## 1. Threat model

Actors: filesystem writer (staging volume), database writer (SQLite store), control-plane compromise, backup/restore operator.
Assets: generated bundle bytes and seal, approval/download gate integrity.
Threats: DB rewrite of seal, seal-flag downgrade, key theft, replay of historical seals, malformed payload / algorithm confusion.

## 2. Signing scope

- Generated Java bundle bytes (all files in the artifact bundle).
- Seal payload containing run_id, workload_id, sorted file paths and content hashes, key_id, algorithm, nonce.
- Evidence manifests and verification reports where required by release policy.

## 3. Recommended algorithm

Ed25519 signature over canonical JSON (sorted keys, no volatile fields such as timestamps in the signed body; include a nonce). Verification uses the public-key ring.

## 4. Public-key verification workflow

1. Load public keys by key_id from a configured keyring (file or secret store).
2. Recompute canonical payload from bundle files and run metadata.
3. Verify signature; reject on any mismatch.
4. Fail closed (409) on unknown/revoked key_id.

## 5. Private-key custody

- Private key loaded from `EVIDENCE_SIGNING_KEY_PATH` at startup.
- If unset in production, startup fails closed.
- Never commit private keys; never log key material.

## 6. Development vs production key separation

- Dev keys may be ephemeral/generated locally and labeled unsigned/dev.
- Production key is separate, stored in a secret manager or HSM/KMS.
- Dev signatures are not accepted by production verification.

## 7. Rotation and revocation

- New key gets a new key_id; old public keys remain in the keyring for verification only.
- Revoked keys are marked; seals using revoked keys fail verification.
- Rotation does not invalidate historical evidence; verification resolves by key_id.

## 8. CI integration

- CI may verify signatures using the public keyring.
- CI must not possess the production private key.
- Release pipelines fail if any required artifact is unsigned in production mode.

## 9. Failure-closed behavior

- Missing signature where signed:true is claimed -> 409.
- Invalid signature -> 409.
- Unknown/revoked key_id -> 409.
- Malformed payload or algorithm mismatch -> 409.
- signed:false in production -> startup failure or 409; no unsigned downgrade.

## 10. Required tests and acceptance criteria

- Unit: deterministic canonical payload; round-trip verify.
- Negative: tamper one byte, DB rewrite, flag downgrade, unknown key, malformed payload.
- Mutation: corrupt signature bytes, file hash, key_id, algorithm.
- Rotation: old seal verifies with old key; new signing uses new key.
- Integration: forge seal without private key -> 409.

## Safe preparatory work completed

- Architecture audit and threat model documented.
- Fail-closed requirements specified.
- No production keys generated or committed.
- No implementation changes to signing code (owner decision pending).

## Owner decisions required

1. Key custody strategy (file path vs secret manager vs HSM/KMS).
2. Production policy for legacy unsigned seals.
3. Key rotation cadence and revocation process.
4. Whether generated artifacts must be signed for the controlled pilot scope.
