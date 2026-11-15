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
GnuCOBOL), `tests/integration/test_vsam_disk_index.py` (disk-backed Java
consumer), `scripts/perf/vsam_benchmark.py` (scale).

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
| Alternate keys, fixed-length KSDS | IMPLEMENTED, UNIT_TESTED, GNUCOBOL_VERIFIED | up to three DISPLAY leaf keys, WITH DUPLICATES or unique, declared in the manifest as `(offset, length, duplicates)` and required to equal the COBOL SELECT; the migrator writes each record's write sequence in front of its data (the image the runtime keeps), refuses a repeated value of a unique key with `ALTERNATE_KEY_DUPLICATE` and refuses `ALTERNATE_CHECK_TOO_LARGE` beyond `alternate_unique_check_records` (default 5,000,000) because that check is held in memory. `tests/enterprise/test_vsam_alternate_keys.py` (13 tests, including resume), `tests/integration/test_vsam_alternate_key_e2e.py` (API to generated Java against GnuCOBOL: reads by both alternate keys, START and READ NEXT along both in the certified browsing shape, and a 46-byte record whose data is longer than the sequence prefix; negative control: without the prefix the wide case differs from GnuCOBOL) |
| Alternate keys with variable-length records, ESDS or RRDS, group-item keys, binary records, more than three keys | REFUSED | `ALTERNATE_KEY_UNSUPPORTED` |
| Duplicate primary keys | REFUSED | `DUPLICATE_KEY`; duplicate-allowed manifests refused |
| Sequential access | GNUCOBOL_VERIFIED | START then READ NEXT (KSDS), sequential read (ESDS) |
| Random access | GNUCOBOL_VERIFIED | READ KEY (KSDS), READ by RRN (RRDS) |
| DISPLAY text fields | IMPLEMENTED, GNUCOBOL_VERIFIED | ASCII and EBCDIC (cp037, cp500, cp1047, cp1140) decoded; EBCDIC decoding is UNIT_TESTED only |
| COMP / COMP-3 / binary fields in records | REFUSED | control or undecodable bytes give `UNREPRESENTABLE_RECORD`; non-DISPLAY USAGE in the FD gives `LAYOUT_UNVERIFIABLE` |
| Manifest vs SELECT/FD validation | IMPLEMENTED, UNIT_TESTED | organization, record length, key offset and length, alternate keys (offset, length, duplicates flag and order) |
| Streaming migration (bounded memory) | IMPLEMENTED, UNIT_TESTED, scale-tested | see `docs/operations/CERTIFICATION_EVIDENCE.md` |
| Checkpoint and resume | IMPLEMENTED, UNIT_TESTED, scale-tested | source tamper is refused (`RESUME_REJECTED`) |
| Java consumption: ESDS fixed | IMPLEMENTED, GNUCOBOL_VERIFIED | per-record buffered reads: bounded memory |
| Java consumption: KSDS and RRDS, large read-only (`OPEN INPUT`, image of 32 MiB or more) | IMPLEMENTED, UNIT_TESTED, INTEGRATION_TESTED, GNUCOBOL_VERIFIED | disk-backed sparse index: memory is proportional to records / 256. Differential tests against a TreeMap and a 165 MB KSDS scanned and probed under a 48 MB Java heap (the in-memory path fails under the same heap). GnuCOBOL parity (runtime-class level, KSDS fixed and RDW, RRDS) is verified with the threshold forced to 1 byte on small images; the large-image behavior is verified by the differential and heap tests, not by GnuCOBOL |
| Java consumption: KSDS and RRDS, small images, or any file opened `OUTPUT`, `I-O` or `EXTEND` | IMPLEMENTED, GNUCOBOL_VERIFIED | **not bounded**: the whole image is loaded into a TreeMap, and `CLOSE` rewrites it. Threshold: system property `cobolio.diskIndexBytes` (default 33554432) |
| Native IBM VSAM, IDCAMS, CI/CS splits, SHAREOPTIONS | UNSUPPORTED | out of scope |
