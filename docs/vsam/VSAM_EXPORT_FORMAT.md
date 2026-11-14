# VSAM Logical Export Format

A native IBM VSAM dataset is not a normal Linux file. SystemaOps migrates a
**logical export**: records unloaded from the cluster (for example with
IDCAMS REPRO to a sequential dataset) in the framing below, plus a manifest.
Nothing here is verified against a real IBM environment.

## Framing
| Format | Layout |
|---|---|
| FIXED | records back to back, each exactly `max_record_length` bytes |
| VARIABLE_RDW | 4-byte RDW per record: 2-byte big-endian length that includes the RDW, then 2 zero bytes; then the record |
| RRDS | every record is preceded by a 4-byte big-endian relative record number (RRN, 1 or more, strictly ascending). The prefix is not part of the record length. RRDS exports must be FIXED |

The RRN prefix is a SystemaOps convention: a plain REPRO of an RRDS does not
carry slot numbers, so the exporter must add them.

## Manifest (`VsamExportManifest`, schema 1.0)
`dataset_name`, `organization` (KSDS, ESDS, RRDS), `layout` (`record_format`,
`min_record_length`, `max_record_length`, `key_offset`, `key_length`,
`code_page`), `duplicate_keys`, `alternate_keys`, `record_count`,
`dataset_bytes`, `sha256`, and provenance fields (`export_platform`,
`export_tool`, `export_tool_version`, `provenance`).

The manifest is never trusted on its own. The migrator checks the actual file
size, record count, byte count and SHA-256, and (when the COBOL source is
supplied) the SELECT/FD: organization, record length, primary key offset and
length. Any disagreement refuses the job.

## Output (what the generated Java runtime reads)
| Organization | Image |
|---|---|
| KSDS | `<runtime_path>.idx`: line `K<keylen>`, then `key U+0001 data-after-key` per record |
| ESDS FIXED | `<runtime_path>`: decoded records back to back, no terminator (COBOL ORGANIZATION SEQUENTIAL) |
| ESDS VARIABLE_RDW | `<runtime_path>`: one decoded record per line (line-sequential image) |
| RRDS | `<runtime_path>.rel`: line `R`, then `rrn U+0001 record` per record |

Records are decoded from `code_page` (single-byte only: ascii, latin-1,
cp037, cp500, cp1047, cp1140) and written as UTF-8. Java 17 on a platform whose
default charset is not UTF-8 may mis-read non-ASCII data.

## Refusals (stable codes)
`ALTERNATE_KEY_UNSUPPORTED`, `KEY_OFFSET_UNSUPPORTED`, `DUPLICATE_KEYS_UNSUPPORTED`,
`CODE_PAGE_UNSUPPORTED`, `DATASET_TOO_LARGE`, `RECORD_TOO_LARGE`, `INVALID_LAYOUT`,
`SIZE_MISMATCH`, `TRUNCATED_RECORD`, `INVALID_RDW`, `INVALID_RRN`,
`RECORD_LENGTH_OUT_OF_RANGE`, `UNDECODABLE_RECORD`, `UNREPRESENTABLE_RECORD`,
`DUPLICATE_KEY`, `KEYS_OUT_OF_ORDER`, `COLLATION_MISMATCH`, `RRN_OUT_OF_ORDER`,
`RECORD_COUNT_MISMATCH`, `CHECKSUM_MISMATCH`, `RESUME_REJECTED`, and from the
FD check `FD_NOT_FOUND`, `ORGANIZATION_MISMATCH`, `RECORD_LENGTH_MISMATCH`,
`KEY_MISMATCH`, `KEY_FIELD_NOT_FOUND`, `LAYOUT_UNVERIFIABLE`.

A refusal never leaves a published artifact.

## Limits that affect correctness
- KSDS exports must be sorted by primary key (the normal REPRO order). Key order is checked on the raw bytes and again after decoding, because EBCDIC and text collating sequences differ (`COLLATION_MISMATCH`).
- Records containing control characters or undecodable bytes (packed decimal, binary integers) are refused. A binary field whose bytes happen to be printable cannot be told apart from text by the migrator; the FD check refuses any non-DISPLAY USAGE it can see in the COBOL source.
