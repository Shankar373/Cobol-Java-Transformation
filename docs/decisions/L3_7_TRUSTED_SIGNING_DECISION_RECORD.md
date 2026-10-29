# Decision Record: L.3.7 Trusted Evidence Signing

**Date:** 2026-10-29
**Status:** BLOCKED pending owner approval (no implementation)
**Owner decision required:** Choose key custody strategy and production policy.

## 1. Current state (confirmed)
- `api/artifact_seal.py` implements SHA-256 self-seal over generated bundle files.
- Seal detects filesystem substitution only.
- A database attacker can rewrite both bytes and seal; no authenticity/non-repudiation.
- Product claim narrowed to "filesystem-substitution detection" (commit a3509ca).

## 2. Threat model
Actors:
- A1: filesystem writer (staging volume) — protected by self-seal.
- A2: database writer (SQLite store) — NOT protected.
- A3: control-plane process compromise — holds signing key if mounted; key exposure possible.
- A4: backup/restore operator — can replay old seals; must not resurrect stale approvals.

Assets:
- Generated bundle bytes and their seal.
- Approval/download gate integrity.

Threats:
- T1: DB rewrite of `runs.generated_seal` to match tampered bundle (A2).
- T2: Seal flag downgrade `signed:true` -> `signed:false` to bypass signature (A2).
- T3: Key theft from mounted secret (A3).
- T4: Replay of historical seal under rotated key (A4).
- T5: Malformed payload / algorithm confusion (A2).

## 3. Recommended design (Ed25519)
- Algorithm: Ed25519 signature over canonical JSON payload.
- Canonical payload fields (sorted): algorithm, key_id, run_id, workload_id, sorted file paths + content hashes, sealed_at? (sealed_at excluded from signed body to avoid re-signing on read; include a nonce).
- Key custody: private key loaded from `EVIDENCE_SIGNING_KEY_PATH` at startup; if unset in production -> fail closed (startup error), no unsigned downgrade.
- Public key ring retained for historical verification.
- Key rotation: new key_id; old public keys retained for verification only.
- Production policy: `signed:true` required; `signed:false` seals rejected in production (dev mode may allow unsigned with explicit label).

## 4. Fail-closed requirements
- Missing signature on a seal that claims signed:true -> 409 ConflictError.
- Invalid signature -> 409.
- Unknown/revoked key_id -> 409.
- Malformed payload / algorithm mismatch -> 409.
- DB-only seal rewrite -> signature mismatch -> 409.
- signed:false in production -> startup failure or 409 (no downgrade).
- Historical key validation: verify with keyring; if key missing -> 409 (not silent).

## 5. Migration / legacy policy
- Existing unsigned seals remain verifiable in dev/non-production as unsigned.
- In production, legacy unsigned seals fail closed at approval/download until re-sealed or explicit migration window approved.
- No destructive migration; adding signature fields is additive JSON.
- DB schema version unchanged unless index column added.

## 6. Test plan
- Unit: canonical payload serialization deterministic; signature verify round-trip.
- Negative: tamper one byte -> 409; rewrite DB seal -> 409; downgrade signed flag -> 409; unknown key -> 409; malformed payload -> 409.
- Mutation: corrupt signature bytes, file hash, key_id, algorithm -> all fail.
- Key rotation: old seal verifies with old key; new signing uses new key.
- Integration: forge seal without private key -> 409 (differential).

## 7. Decision request (owner action)
Choose one:
- (A) Implement Ed25519 with mounted secret key (Option C) — requires key provisioning + rotation runbook.
- (B) Implement HMAC-SHA256 with server secret (Option B) — simpler, shared secret.
- (C) Keep narrowed claim (Option D) — no code change.

Acceptance gate for (A)/(B): differential test (forge without key -> 409) passes in CI; key custody documented; production startup fails closed without key.

## 8. Outstanding blockers
- No HSM/KMS assumed available; mounted secret is the realistic custody.
- Network availability for Sigstore not assumed (air-gapped likely).
- Owner must approve before any code change.

## 9. Non-goals
- No implementation in this change set.
- No signed:false production downgrade.
PY