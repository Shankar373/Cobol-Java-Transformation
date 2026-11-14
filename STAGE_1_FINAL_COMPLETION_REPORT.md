# Stage 1 Final Completion Report: COBOL + VSAM modernization

Branch `stage1/vsam-completion`, PR #28, base `impl/enterprise-platform`. `main` (`b0c1f6b`) was not touched.

## Verdict

**STAGE 1 PARTIALLY COMPLETE** until the final exact-SHA evidence in section 9 is filled in; see that section for what is verified
and what is not. Nothing in this report is IBM runtime verified, and nothing is production-ready.

What is true of the code on this branch: a deterministic, fail-closed COBOL+VSAM path exists from application source to
discovery, assessment, a migration API, a persisted and downloadable migrated dataset, and a generated-Java application that reads
those downloaded bytes with output equal to the original COBOL program under GnuCOBOL 3.1.2 and to independently constructed values.

## 1. Evidence classes used in this report

| Class | Meaning here |
|---|---|
| Implemented | code exists and is reachable |
| Unit-tested | deterministic pytest, no Docker |
| Integration-tested | HTTP routes with the real service/store, no Docker |
| GnuCOBOL-verified | a GnuCOBOL 3.1.2 program wrote or read the data (Docker lane); 3.2.0 passes the same differentials locally |
| Linux/s390x differential-verified | GnuCOBOL 3.1.2 on `linux/s390x` (QEMU) wrote records; converted to the x86 form they equal what x86 wrote, both directions. **Linux on s390x is not z/OS** |
| Generated-Java-verified | Java emitted by the real transformation producer, compiled and run, equals the COBOL program on the same bytes |
| IBM-runtime-verified | **none**: no IBM runtime, z/OS or IBM VSAM was available. `IBM_ZOS` is documented semantics only |

## 2. Gaps

| Gap | Status | Basis |
|---|---|---|
| G-26 COPY inside FD | **Closed** for FILE SECTION COPY (nested, bounded, shared expansion budget, fail-closed) | unit-tested; IR, layout and generated Java equal the inline FD |
| G-27 binary platform representation | **Closed for the explicitly tested representations**: `GNUCOBOL_X86_DEFAULT`, `GNUCOBOL_X86_IBM_DIALECT`, `GNUCOBOL_S390X_DEFAULT`, `GNUCOBOL_S390X_IBM_DIALECT` | GnuCOBOL and Linux/s390x differentials. `IBM_ZOS` documented only |
| G-28 RDW / ESDS / RRDS / alternate indexes | **Partially closed** | RDW sequential/ESDS migration, both encoding directions, alternate keys validated (kind must match the covered field) but index structures **not built**, ESDS RBA refused, RRDS BLOCKED |
| G-29 layout coverage | **Partially closed** | differential tests for inline SIGN, nested OCCURS, group REDEFINES, signed zoned DISPLAY; SYNCHRONIZED, ODO, COMP-1/2 refused by name |

## 3. Capability table

| Capability | Implemented | Unit-tested | GnuCOBOL | s390x | Generated Java | IBM runtime |
|---|---|---|---|---|---|---|
| FD COPY expansion | yes | yes | n/a | n/a | equivalence to inline FD | no |
| Layout derivation (DISPLAY, COMP, COMP-5, COMP-3, SIGN, OCCURS, selected REDEFINES) | yes | yes | yes, default and `-std=ibm` | COMP/COMP-5 byte order | n/a | no |
| Signed zoned DISPLAY conversion (overpunch) | yes | yes | yes (3.1.2 and 3.2.0 read migrated values) | n/a | no | no |
| Binary platform conversion | yes | yes | yes | yes | COMP only (2-byte, unsigned fixture) | no |
| Fixed-record migration, both encoding directions | yes | yes | yes (independent GnuCOBOL reader plus control) | yes | yes (fixed sequential, DISPLAY/COMP/COMP-3) | no |
| RDW sequential/ESDS migration | yes | yes | payload vs re-framed GnuCOBOL records | no | no | no |
| Alternate key validation | yes | yes | no | no | no | no |
| Per-FD assessment in discovery | yes | yes | n/a | n/a | n/a | no |
| Migration API (migrate, status, download) | yes | yes (HTTP, real store) | n/a | n/a | yes (end to end, section 5) | no |

**Unsupported or refused by name** (regression-tested as refusals, never approximated): variable KSDS, binary fields in variable
layouts, RRDS (BLOCKED), spanned records, alternate index construction and maintenance, ESDS RBA preservation, OCCURS DEPENDING ON,
SYNCHRONIZED, COMP-1/COMP-2, an unselected REDEFINES, several FD record descriptions without an explicit compatible choice.

## 4. Product workflow

`POST /applications` -> `POST /applications/{id}/ingest` (zip) -> `GET /applications/{id}/discovery` (programs, COPY-in-FD
expanded, a `vsam_assessment` per FD) -> `POST /applications/{id}/vsam/migrate` -> `GET .../vsam/migrations/{id}` ->
`GET .../vsam/migrations/{id}/download`.

* Layout, keys and organization come from the application's own FD; the request only chooses encodings, platforms, record format and,
  for a multi-record FD, the record. The organization option can only pick one compatible with the FD.
* Migration ids are deterministic and derived from the application, options, engine version, source and target layout identities,
  key definitions and platforms; a changed source or engine gets a new id.
* Roles: `POST` needs operator; **reading a report and the download both need operator** (reports can quote field values); viewer
  can read nothing here. Unauthenticated requests are 401.
* Limits: per-file upload 10 MB by default (`CONTROL_PLANE_MAX_FILE_BYTES`, enforced while reading), hard backstop
  `MAX_DATASET_BYTES` 50 MB, two concurrent migrations per process (busy refusal), 200 stored migrations per application,
  1000 rejected-record entries kept per report (exact count always reported), layout diagnostics capped at 200.
* Persistence: **files under the workspace root**, one directory per migration id; atomic temp+rename writes, report written last,
  output hash checked before download, a corrupt report reads as absent and is rewritten by an identical request, a failed write
  leaves no temp file. **This is not a durable enterprise job store** (ADR-0011): no listing, delete, retention, audit events, resume or
  cancel; no coordination with re-ingestion (do not re-ingest during a migration); the concurrency bound is per process; the
  upload is read into memory (bounded); files are not fsynced; the integrity hash is unsigned; execution is synchronous; an engine
  report with `success` true can still carry rejected records, so consumers must read `complete`. The sqlite Store migration was
  considered and **not** done: it is the follow-up before use beyond this bounded subset.

## 5. Acceptance proofs

All Docker-lane proofs need `RUN_DOCKER_TESTS=1` and are kept distinct:

1. **API to generated Java** (`tests/integration/test_vsam_api_to_java.py`): application created and its source ingested over HTTP;
   `GET /discovery` shows the FD and its assessment; a mainframe-form dataset (EBCDIC cp037, IBM binary widths, packed) is uploaded
   to `POST /vsam/migrate`; status is read; the download equals the stored artifact (SHA-256 and size checked); **those exact
   bytes** are the input of (a) Java generated by the real producer, compiled and run, and (b) the original COBOL under GnuCOBOL
   3.1.2; both outputs equal each other and equal values built from the fixture rows (never from the migration engine); a control shows
   the unconverted bytes do not give the expected result; a second identical submission returns the same id and the same bytes.
   Evidence JSON (fixture and COBOL source hashes, migration id/state/engine version, artifact hash and size, generated Java file
   names, COBOL/Java/expected output, comparison, proof class) is written to `VSAM_EVIDENCE_DIR`, which CI uploads.
   **Proof bound:** fixed sequential records of DISPLAY, COMP and COMP-3; the fixture is unsigned and its only binary field is 2-byte
   COMP, so 4/8-byte widths and signs are proved by the GnuCOBOL differentials, not by the Java run. No indexed, variable or COMP-5
   Java proof. The generated Java `readRecord` treats an I/O error as end of file.
2. **Independent GnuCOBOL reader** (`test_vsam_consumer_oracle.py`): a separate GnuCOBOL program reads the migrated data (COMP, COMP-5,
   COMP-3, signed zoned DISPLAY) and shows the original values; a control shows the raw mainframe bytes do not.
3. **Generated-Java consumer** (`test_vsam_java_consumer.py`): the engine-level (not API) variant of proof 1.
4. **Linux/s390x** (`test_vsam_s390x_oracle.py`, 4 cases: two dialects x {COMP-5 big-endian witness, x86 equality both directions}).

## 6. Independent reviews (each actually ran and returned findings)

| Review | Result and disposition |
|---|---|
| python-reviewer (earlier head) | 1 HIGH (key over a width-changing binary field) fixed; 7 MEDIUM, 7 LOW |
| security-reviewer (earlier head) | 2 HIGH (copybook dropped from WORKING-STORAGE; unbounded COPY fan-out) fixed |
| code-reviewer (earlier head) | 1 HIGH (signed zoned DISPLAY translated as text) fixed, GnuCOBOL-verified |
| architect (earlier head) | 1 BLOCKER (migration id not tied to layout/engine) fixed; SHOULDs fixed or in ADR-0011 |
| security-reviewer (head `b754599`) | 0 CRITICAL/HIGH. MEDIUM: unbounded artifact growth (fixed by per-app cap, rest documented), full discovery per request with no timeout (documented, not fixed); LOW items documented |
| architect + persistence review (head `b754599`) | 0 blockers. Fixed: corrupt report wedged an id, report readable by viewer, temp file left on failed write, no per-app cap. Documented: re-ingest coordination, retention, per-process concurrency, fsync, ADR claim wording (corrected) |
| java-reviewer + test-quality review (head `b754599`) | no vacuous agreement; expected values independent. Fixed: CI gate that fails when the VSAM Docker proofs skip, evidence booleans computed. Documented: narrow fixture, control passes through a Java crash on foreign bytes |
| database-reviewer, tdd-guide agents | **not invoked as such**; the architect agent covered persistence, the Java reviewer covered test quality. RED was recorded before each fix |

Open, not fixed (low risk for the bounded subset, recorded): server paths can appear in copybook diagnostics (pre-existing);
`validate_layout` is not re-run on caller-built layouts in the binary path; private helpers shared by `migrate.py` and
`migrate_variable.py` and a double `convert` call per record; assessment and API planning are separate code (discovery can
disagree with the API for group RECORD KEYs, multi-record FDs and record format); COMP truncation is hard-coded and platform
evidence is a free-text string, so z/OS `TRUNC(BIN)`, `NUMPROC` and float formats need explicit facets before any `IBM_ZOS` data is
relied on; `reconcile` re-applies the same conversion, so it proves accounting and ordering, and conversion correctness rests on the
differentials.

## 7. Open-source tools

See `docs/reports/STAGE_1_OPEN_SOURCE_TOOL_EVALUATION.md`: GnuCOBOL 3.1.2 retained as the reference; Linux/s390x lane adopted
(built in CI under QEMU, base pinned by digest); GnuCOBOL 3.2.0 adopted as an optional local lane (25 differentials pass, not in
required CI; its tarball checksum is self-computed, the `.sig` was not verified); VBISAM deferred; GCBLUnit and COBOL Check
rejected; Zowe CLI unusable without an authorized z/OS.

## 8. Local verification

| Command | Result |
|---|---|
| VSAM unit and API tests (`tests/test_vsam*.py`, `tests/transformation/test_fd_copybooks.py`) | 357 passed |
| `RUN_DOCKER_TESTS=1` VSAM Docker lanes incl. API-to-Java, s390x (default and ibm), consumer oracle, layout, g29, variable | passed locally (x86 3.1.2; s390x via QEMU; 3.2.0 differentials) |
| `ruff check .`, `python tools/dependency_map.py --check` | clean |
| full hermetic suite, frontend tests/build | **pending**: recorded in section 9 |

Skipped Docker-lane tests are never counted as passes.

## 9. Exact-SHA evidence

**Pending.** Filled in only from workflow runs inspected for the exact final commit; a commit cannot contain its own run ids, so the
final SHA, run links and the certification artifact check are recorded in the PR #28 comment and the final handoff, and a later
commit would invalidate them.

Earlier exact-SHA results, for the record only (they do not certify later code): `52e0608` CI 43441968285 success,
certification 43441968326 success (certified=True), supply chain 43441968361 success; `766627b` CI 43531323685 **failed** (s390x
image not built in CI; stale dependency map), both fixed; `f06e78e` CI 43546366927 and supply chain 43546367035 (see PR comment).
The certification `not_proven` list is unchanged: self-attested evidence, no IBM runtime, Quarkus and Micronaut certified in command
mode only.
