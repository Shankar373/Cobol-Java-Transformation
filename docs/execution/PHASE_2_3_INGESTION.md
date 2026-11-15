# Enterprise Phases 2 and 3: GitHub and ZIP ingestion (status 2026-11-16)

Branch `codex/enterprise-phases-continuation`. Both phases are **PARTIALLY COMPLETE**: the safe core exists and is tested; the API
endpoints, durable ingestion jobs, upload sessions and frontend flow do not exist yet. Nothing here is certified.

## What exists (`enterprise/ingest/`)

| Module | Purpose | Tests |
|---|---|---|
| `safe_extract.py` | Extract a ZIP into a new empty directory. Refuses (stable `ARCHIVE_*` code, nothing left behind): path traversal, absolute and drive paths, non-normalised names (`a//b`, `a/./b`), control characters, Windows reserved names, over-long or too-deep paths, symlinks (refuse, or skip and record), devices and FIFOs, encrypted entries, case-insensitive duplicate paths, too many files, files over the size limit, compression ratio above the limit, and total expanded bytes above the limit counted on the bytes actually written, corrupt CRC, truncated or non-ZIP input. Reads with random access, streams in 1 MiB chunks, hashes while writing, opens targets exclusively so nothing is overwritten. Never executes content. | `tests/enterprise/test_safe_extract.py` (22 pass, 1 skipped on Windows only) |
| `manifest.py` | Classify files (COBOL, copybook, JCL, BMS, SQL and others), list ignored files with a reason (excluded directories such as `.git`, binary and archive types), content-addressed `manifest_id` over the sorted listing, prune ignored files from the workspace | covered by the GitHub tests |
| `github.py` | Public GitHub repository ingestion pinned to an exact commit: strict `https://github.com/<owner>/<repo>[/tree/<ref>]` URL parsing; repository metadata; branch, tag or SHA resolved to a 40-hex commit; ZIP snapshot streamed under a byte limit (declared length and running total); extraction with symlinks skipped; manifest; the single top-level archive directory is stripped | `tests/enterprise/test_github_ingest.py` (38 pass) |

Network behaviour covered, over real sockets against a local stand-in server: 404 and private repositories, rate limits (a long
reset is reported, a short one is waited out and retried), transient 5xx with bounded retries, an unreachable server, oversize
repository metadata, an oversize archive with and without a declared length, redirects (refused off the allowed hosts, followed on
them), a malicious archive, and a token that reaches only allowed hosts and never appears in an error. The user supplies only the
repository URL; API and archive hosts are server configuration, so a user cannot point the fetcher at an internal address.

**Live check (manual, not a test):** on 2026-11-16 an unauthenticated run against `octocat/Hello-World` pinned commit
`7fd1a60b01f91b314f59955a4e4d4e80d8edf11d`, produced one file (`README`, 13 bytes) and manifest id
`da9f4c10835ccb471db82f8ab713de11c5a245d95d52228a468bc0cb32f3dc4f`, twice with identical manifests, and a nonexistent repository gave
`REPO_NOT_FOUND`. That repository is tiny; it says nothing about large-repository behaviour.

## Not built

Phase 2: an API endpoint and durable job for GitHub ingestion; storing the snapshot in the object store; persisting `SourceSnapshot`;
credential configuration for private repositories (private repositories are refused by design for now); rate-limit state shared
across workers; language identification beyond file extensions; a large-repository test.

Phase 3: multipart upload sessions (create, upload part, resume, complete, abort, expiry cleanup) through the API; direct-to-object-store
uploads with short-lived authorisation; whole-archive checksum verification against the declared one; nested-archive policy
(archives inside the archive are listed as files, never extracted); frontend upload flow; a test with a multi-gigabyte archive and a
memory measurement. The `LocalObjectStore` multipart contract exists from Phase 0 but no ingestion path uses it yet.

## Security notes

- Extraction limits default to values in `ExtractLimits`; the ingestion quotas in `enterprise/quotas.py` override them for GitHub.
- A refusal removes the partial extraction directory; a non-empty target is refused and left untouched.
- The extractor is the only code that writes archive content to disk, and it is shared by both phases.
