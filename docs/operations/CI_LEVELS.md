# CI levels: fast checks, full validation, corpus certification

Three workflows, three different claims. A green run of one never implies another. Deterministic, open-source,
no LLM; nothing here lowers a threshold, skips a test or weakens a gate - work moved between levels, and the
re-assembly of the sharded lane is itself checked (`tools/ci_shard_proofs.py`).

| Level | Workflow (status name) | Runs on | Proves | Does **not** prove |
|---|---|---|---|---|
| A | `ci.yml` - **CI fast checks** | every push and PR | lint, type check, capability-truth gate (Linux + Windows) incl. the dependency-map check, byte-identical generation hashes, focused backend suites (discovery, evidence, tools, transformation), frontend tests + production build (Linux + Windows) | the complete suite, coverage floor, Windows suite, Docker/oracle, PostgreSQL, VSAM, corpus |
| B | `ci-full.yml` - **Full integration validation** | nightly; push to `main`, `release/**` or a tag; manual dispatch; a commit message containing `[full]` | the whole backend suite (Linux no-Docker, Windows), the coverage floor (>= 88, may only rise), the Docker/oracle lane (GnuCOBOL oracle, OCESQL + PostgreSQL, s390x big-endian witness, VSAM proofs) sharded and re-assembled | four-runtime corpus certification |
| C | `certification.yml` - **Corpus certification (GnuCOBOL, all runtimes)** | commit message containing `[certify]`; manual dispatch | every fixture application on `spring_boot`, `plain_java`, `quarkus`, `micronaut` through the API, independent verifier re-check, certification against the accepted evidence, exact-run summary | - |

On an ordinary branch push level B and C exist as runs whose jobs are **skipped** (shown as skipped, never as
passed). The supply-chain workflow (`supply-chain.yml`) is separate: the gating Python and npm audits run on every
push; the report-only Trivy image scan runs weekly, on manual dispatch and on tags only.

## Why the Docker lane was the problem, and what sharding does

Measured on run 45050810212 (`9655239`): the Docker job took 72 min, of which the four image builds were 2 min 50 s
and the single serial pytest process 68 min 39 s (8,158 tests, 4,097 s of test time; about 30 oracle files at 30-40 s
per Docker-backed test). Layer caching alone could therefore save at most about 3 minutes; the lever is parallelism.

* `tools/ci_shards.py` splits the test **files** (never single tests: file-scoped fixtures and ordering stay intact)
  over `SHARDS` runners by greedy longest-processing-time assignment over `tools/ci_test_durations.json` (seconds per
  file, from the measured JUnit report). Same tree + same manifest => same shards on every host. A new file is
  assigned like any other (unknown files weigh 2 s); a stale manifest entry is ignored. Nothing can be dropped.
* Every shard builds the same pinned images, has its **own** PostgreSQL service (no shared state), runs its files
  with `RUN_DOCKER_TESTS=1` (the conftest hook still turns an infrastructure skip into a failure) and uploads its
  JUnit report.
* `backend-oracle-complete` (`tools/ci_shard_proofs.py`) fails unless: every shard job succeeded; one report per
  shard; no failed or errored case; every case ran in the shard that owns its file; the executed case count equals
  `pytest --collect-only` for the whole tree (no test dropped or run twice); and the proof modules (VSAM API to Java,
  s390x oracle, Java consumer, consumer oracle, PostgreSQL database, VSAM worker) ran with **no skip**.
* To change the shard count edit `env.SHARDS` **and** the matrix in `ci-full.yml` (`tests/test_ci_levels.py` fails if
  they differ). Refresh the weights with
  `python tools/ci_shards.py --refresh-durations <backend-junit-shard-*.xml>` after a full run.

## Image layer cache (Buildx)

`scripts/ci/build-image.sh` builds with `docker buildx build --load --pull ... --cache-from/--cache-to
type=local,mode=max` **only when** `DOCKER_BUILDX_CACHE_ROOT` is set (the workflows set it after restoring the
directory with `actions/cache`); local builds and `scripts/deploy/build-production.sh` keep the plain `docker build`.
Preserved unchanged: pinned base digests and apt/package pins, smoke tests (`cobc --version`, OCESQL, JDK, Maven),
five attempts with growing pause, host-network retry (the builder is created with the `network.host` entitlement),
the apt-mirror fallback, `--pull`, the s390x platform check, provenance (`record_docker_image_provenance.py`,
`docker-images.json`). The cache is keyed by the Dockerfiles, `docker/maven-precache/**`, `docker/gnucobol-s390x/**`
and the build script, and only skips a layer whose instruction, parent layer, copied files and pinned base are
identical - verified locally: a cold and a cache-hit build of the same Dockerfile produced the same image ID.

Evaluated and **not** adopted: sharing built images between workflows through a registry or artifact. The four builds
take under 3 minutes, an image upload/download costs about as much, and publishing images adds a surface (needs
`packages: write`, a SHA-specific immutable tag and digest evidence). Cross-workflow reuse happens through the
content-keyed layer cache instead (the same cache key serves `ci-full`, `certification` and the Trivy job).
Coverage aggregation across shards was also not adopted: the coverage job runs the Docker-free suite in parallel with
the hermetic job already, so merging would only save runner minutes, not wall-clock time.

## Operating rules

* A change that alters generated output must update `docs/audits/generation_hashes.json` in the same commit
  (`python tools/generation_hashes.py --write docs/audits/generation_hashes.json`, with the reason in the commit).
  The baseline is **Linux-canonical** (written in a `python:3.11` container from the pre-Phase-0 code at `9655239`;
  the current code reproduces it byte for byte there, in all 110 builds) and Windows reproduces it too. The first
  baseline was written on Windows and failed the Linux CI job for nearly every file: the generator wrote files with
  `Path.write_text(..., encoding="utf-8")`, which turns `
` into `
` on Windows. Writers now pass
  `newline="
"` and `tests/test_generated_output_newlines.py` keeps it so. To rewrite the baseline on Linux:
  `docker run --rm -v "$PWD:/w" -w /w python:3.11 bash -c 'pip install -q --require-hashes -r requirements-dev.lock &&
  python tools/generation_hashes.py --write docs/audits/generation_hashes.json'`.
* `docs/audits/DEPENDENCY_MAP.md` is built from `git ls-files`: **stage new files first, then** run
  `python tools/dependency_map.py` and `--check`. Running it while new modules are untracked produced the stale map
  that failed the Linux gate on `95e2c7a`.
* Release candidates: tag the commit (`rc-*` / `v*`) or commit with `[full]`, then `[certify]`; both are tied to the
  exact SHA. Do not claim certification from level A or B.

## Measured durations (GitHub Actions API, job `started_at` to `completed_at`)

Wall-clock is the run's `created_at` to `updated_at`. Everything ran on `ubuntu-24.04` / `windows-2022` hosted runners.

| Run (SHA) | Workflow | Wall-clock | Notes |
|---|---|---|---|
| 45050810212 (`9655239`) | old single `ci.yml` | **72m 04s** | Docker job 72m00s (builds 2m50s + serial pytest 68m39s); every other job <= 7m47s |
| 45138109387 (`95e2c7a`) | old single `ci.yml` | **57m 08s** | Docker job 57m03s; failed only on the stale dependency map (fixed in `6f683dd`) |
| 45138109575 (`95e2c7a`) | certification | 17m 52s | four runtimes 11m01s / 11m46s / 17m34s / 17m34s (unchanged by this work) |
| 45147459800 (`276fe67`) | **CI fast checks** | **2m 08s** | slowest job: capability truth (Linux 1m52s, Windows 2m04s); lint 9s, type check 27s |
| 45152315981 (`cacdf60`) | **CI fast checks** | **2m 20s** | all nine jobs green, generation hashes 21s |
| 45147459656 (`276fe67`) | **Full validation**, cold cache | **29m 54s** | 6 shards 19m18s-29m03s (OCESQL image build 6m26s-13m34s with six cold builds at once); completeness proof passed |
| 45152357956 (`cacdf60`) | **Full validation**, warm cache | **14m 02s** | 6 shards 10m47s-13m16s (tests 8m-12m), Windows hermetic 8m03s, coverage 4m50s, Linux hermetic 4m38s, completeness proof 32s |

What the numbers say, without rounding in our favour:

* The 57-72 minute serial Docker job became 14 minutes warm (about 30 cold) - the gain is the sharding, not the cache.
* Image builds were never the bottleneck (2m50s of 72 min). Warm, they cost 6s (oracle), 15s (OCESQL), 16s (Maven) against
  17s / 50s / 45s before; the s390x step still takes about 1m25s because **77 s of it is `apt-get install qemu-user-static`**
  (19 s index update + 57 s download and unpack); the s390x image itself is about 8 s warm and 58 s cold.
  The big-endian proof is untouched. Replacing the apt install with a pinned `binfmt` image would save about a minute per
  shard and add a registry trust path; not adopted.
* A **cold** cache run is slower than it needs to be: with six shards missing the cache simultaneously, the OCESQL build took
  6-13 minutes each (the cause - mirror contention versus the `mode=max` cache export - was not isolated). It happens when a
  Dockerfile, `docker/maven-precache/**` or the build script changes and the cache entry (982 MB) misses.
* The shard weights of the first run (serial measurement) were off by up to about 40 % per shard (479-752 s of test time against an equal estimate); the weights in
  `tools/ci_test_durations.json` now come from the first in-CI run. Per-shard test time warm: 8m-12m.
* Not measured: the report-only Trivy job (moved to schedule / dispatch / tags, so it cost nothing on these pushes).
