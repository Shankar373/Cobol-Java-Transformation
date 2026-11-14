# VSAM Capability Matrix (Stage 1)

Status vocabulary: IMPLEMENTED, UNIT_TESTED, INTEGRATION_TESTED,
GNUCOBOL_VERIFIED, CROSS_PLATFORM_VERIFIED, IBM_RUNTIME_VERIFIED, UNSUPPORTED,
REFUSED. **No row is IBM_RUNTIME_VERIFIED**: there was no IBM environment.
GNUCOBOL_VERIFIED means output parity with GnuCOBOL 3.1.2 on Linux, not z/OS.
No row is CROSS_PLATFORM_VERIFIED yet: tests ran on Windows (host) and Docker
Linux (oracle), and CI evidence for the final commit is recorded separately.

Evidence tests: `tests/enterprise/` (unit, API, FD check),
`tests/integration/test_vsam_oracle_parity.py` (GnuCOBOL vs the runtime class),
`tests/integration/test_vsam_api_to_java_e2e.py` (HTTP API, generated Java,
GnuCOBOL), `scripts/perf/vsam_benchmark.py` (scale).

| Capability | Status | Evidence / limit |
|---|---|---|
| KSDS fixed-length | IMPLEMENTED, UNIT_TESTED, INTEGRATION_TESTED, GNUCOBOL_VERIFIED | API to generated Java equals GnuCOBOL for sequential scan from START and random READ KEY, including a missing key |
| KSDS variable-length (RDW) | IMPLEMENTED, UNIT_TESTED, GNUCOBOL_VERIFIED | runtime-class parity only (`test_vsam_oracle_parity`), not a generated program |
| ESDS fixed-length | IMPLEMENTED, UNIT_TESTED, INTEGRATION_TESTED, GNUCOBOL_VERIFIED | migrated file is byte-identical to the file GnuCOBOL writes; generated Java output equals GnuCOBOL |
| ESDS variable-length (RDW) | IMPLEMENTED, UNIT_TESTED | line-sequential image; no oracle comparison |
| RRDS fixed-length | IMPLEMENTED, UNIT_TESTED, INTEGRATION_TESTED, GNUCOBOL_VERIFIED | random READ by RRN including an empty slot. Sequential READ NEXT on RELATIVE files is UNSUPPORTED by the runtime |
| RRDS variable-length | REFUSED | `INVALID_LAYOUT` |
| RDW framing | IMPLEMENTED, UNIT_TESTED | bad length, non-zero reserved bytes and truncation are refused |
| Primary key at offset 0 | IMPLEMENTED, GNUCOBOL_VERIFIED | |
| Primary key at offset > 0 | REFUSED | `KEY_OFFSET_UNSUPPORTED`; the runtime keys on the first bytes of the record |
| Alternate keys | REFUSED | manifest or COBOL SELECT; the runtime builds no alternate index |
| Duplicate primary keys | REFUSED | `DUPLICATE_KEY`; duplicate-allowed manifests refused |
| Sequential access | GNUCOBOL_VERIFIED | START then READ NEXT (KSDS), sequential read (ESDS) |
| Random access | GNUCOBOL_VERIFIED | READ KEY (KSDS), READ by RRN (RRDS) |
| DISPLAY text fields | IMPLEMENTED, GNUCOBOL_VERIFIED | ASCII and EBCDIC (cp037, cp500, cp1047, cp1140) decoded; EBCDIC decoding is UNIT_TESTED only |
| COMP / COMP-3 / binary fields in records | REFUSED | control or undecodable bytes give `UNREPRESENTABLE_RECORD`; non-DISPLAY USAGE in the FD gives `LAYOUT_UNVERIFIABLE` |
| Manifest vs SELECT/FD validation | IMPLEMENTED, UNIT_TESTED | organization, record length, key offset and length, alternate keys |
| Streaming migration (bounded memory) | IMPLEMENTED, UNIT_TESTED, scale-tested | see `docs/operations/CERTIFICATION_EVIDENCE.md` |
| Checkpoint and resume | IMPLEMENTED, UNIT_TESTED, scale-tested | source tamper is refused (`RESUME_REJECTED`) |
| Java consumption: ESDS fixed | IMPLEMENTED, GNUCOBOL_VERIFIED | per-record buffered reads: bounded memory |
| Java consumption: KSDS and RRDS | IMPLEMENTED, GNUCOBOL_VERIFIED | **not streaming**: `CobolFileIo` loads the whole `.idx` or `.rel` into a TreeMap, so Java memory grows with dataset size. UNSUPPORTED as a bounded-memory consumer |
| Native IBM VSAM, IDCAMS, CI/CS splits, SHAREOPTIONS | UNSUPPORTED | out of scope |
