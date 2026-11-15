# Stage 1 remaining gaps: disposition against the code (2026-11-15)

Basis: branch `codex/enterprise-on-stage1` at `ce8ce00` (Stage 1 PR #28 head `c962efe` plus the streaming migration path).
Evidence for `ce8ce00`: corpus certification 43603385699 succeeded and its summary artifact names `ce8ce00` (self-attested, no IBM
runtime evidence); supply chain 43603382150 succeeded; CI 43603382116 succeeded. Every status below is read from code or tests
in that tree, not from older documents. "Verified against GnuCOBOL" never means IBM-verified.

| Item | Status | Evidence | Remaining restriction |
|---|---|---|---|
| Alternate key `START` / `READ NEXT` | Certified for a stated shape | `engine/transformation/alternate_key.py` docstring and `tests/integration/test_alternate_key_browse_oracle.py` (recorded: 18 seeds, 450 programs, 0 mismatches). I ran 190 further browsing programs (seeds 501 and 502) against GnuCOBOL on this tree: 0 mismatches. Three more seeds were killed by the low-memory guard and are not counted. | Shape only: ACCESS MODE DYNAMIC, two alternate keys (one with duplicates, one unique), `PIC X(2)` fields, FILE STATUS only, OUTPUT or I-O. Everything else is refused by name. |
| Numeric alternate keys, SPLIT KEYS, group-item keys, binary records with alternate keys, SEQUENTIAL access with alternate keys | Refused by name | `alternate_key.py` gate | Not implemented; no oracle sweep exists for them. |
| KSDS fixed records, key at offset zero | Supported, GnuCOBOL-verified | 6 parity tests in `tests/integration/test_vsam_oracle_parity.py` | Key offset above zero is refused by the migration path. |
| KSDS variable-length (RDW export) | Supported for the migration path, GnuCOBOL-verified | RDW cases in the same parity tests | IBM RDW semantics are not IBM-verified. Stage 1 `engine/vsam/migrate_variable.py` still refuses variable KSDS. |
| RRDS | Image produced and GnuCOBOL-verified (migration path) | RRDS parity and API-to-Java tests | Equivalence with an IBM VSAM RRDS is **BLOCKED**: it needs an IBM VSAM reference. Variable-length RRDS and sequential `READ NEXT` on RELATIVE files are refused or unsupported. Slot reuse after DELETE is not separately verified. |
| ESDS fixed and variable | Supported, GnuCOBOL-verified (the fixed ESDS file is byte-identical to the one GnuCOBOL writes) | `tests/integration/test_vsam_api_to_java_e2e.py` | RBA addressing and preservation: **BLOCKED**, no IBM reference. Not modelled. |
| Alternate indexes in the migrated KSDS image | Implemented on the streaming path (branch `codex/stage1-alt-key-browsing`), GnuCOBOL-verified | The migrator emits the write-sequence prefix the runtime keeps and checks unique alternate keys; `tests/enterprise/test_vsam_alternate_keys.py` (13) and `tests/integration/test_vsam_alternate_key_e2e.py` (2, API to generated Java against GnuCOBOL, with a negative control for the wide-record case) | Fixed-length KSDS, up to three DISPLAY leaf keys, key at offset zero. The unique-key check is bounded to 5,000,000 records and refuses beyond that. This is the runtime's own alternate index, not an IDCAMS `BLDINDEX` and not an IBM alternate index (BLOCKED for IBM). Not yet certified: no CI or certification run exists for this commit. |
| IDCAMS | Subset only | `engine/jcl/orchestrator.py` `parse_idcams`: `DELETE` (flags PURGE, SCRATCH, NOSCRATCH, NONVSAM, CLUSTER, GDG, FORCE), `DEFINE GDG` (LIMIT 1 to 255), `REPRO INFILE/OUTFILE`, `SET MAXCC`; anything else is refused with the command text | `DEFINE CLUSTER`, `LISTCAT`, `BLDINDEX`, `ALTER` are **BLOCKED**: their results depend on the IBM catalog and no GnuCOBOL reference exists, so a result could only be invented. |
| `OCCURS DEPENDING ON`, `SYNCHRONIZED`, `COMP-1`/`COMP-2`, unselected `REDEFINES` as record layouts | Refused by name | ADR-0009, `engine/vsam/layout.py`, G-29 | `COMP-1`/`COMP-2` is **BLOCKED** for migration between platforms: IBM hexadecimal floating point and IEEE differ and there is no IBM reference. The others are open. |
| Binary (COMP/COMP-5) platform representation | Closed for four explicit GnuCOBOL presets | `engine/vsam/platform.py`, G-27 | `IBM_ZOS` is documented only. |
| Independent migration verification | Done for the streaming path | Artifact re-hashed on download, input/output SHA-256, record count, interrupt/resume with identical hashes (`docs/operations/CERTIFICATION_EVIDENCE.md`); Stage 1 `engine/vsam/reconcile.py` | Checksums are not signatures. |
| Large-volume streaming | Measured | 16 MiB to 10 GiB, peak memory about 33 MiB | One Windows host, one run per size. |
| Four Java runtimes | Certified | Run 43603385699: plain_java, spring_boot, quarkus, micronaut succeeded; 55 applications | quarkus and micronaut are certified in command mode only; jakarta_ee is not certified (from the artifact's own `not_proven` list). |
| IBM runtime verification | None | | **BLOCKED**: no IBM environment. No `IBM_RUNTIME_VERIFIED` claim. |

## Verdict for Stage 1

PARTIALLY COMPLETE. The certified subset above is real and exact-SHA certified on `ce8ce00`. It is not a complete Stage 1: alternate
index construction, ESDS RBA, IBM RRDS equivalence, several layout forms and most IDCAMS commands are open or BLOCKED as stated.
The 14 November 2026 deadline passed before this was written.
