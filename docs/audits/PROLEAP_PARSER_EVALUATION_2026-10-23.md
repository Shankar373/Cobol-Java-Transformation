# ProLeap COBOL Parser Evaluation (isolated experiment)

**Document type:** Open-source evaluation record (Phase 4 experiment only)
**Date:** 2026-10-23
**Branch / state:** `codex/universal-core`, HEAD `b8a5499`, uncommitted working
tree (no commit, no push; the experiment lives entirely **outside** the
repository working tree)
**Outcome:** evaluated, **not integrated**, existing parser **not replaced**

## 1. Scope and ground rules

This evaluation answers three questions only:

1. What is the exact version and license of the ProLeap COBOL parser?
2. What are its runtime dependencies, and where does the artifact come from?
3. How do its parse results compare with this repository's existing parser on
   real fixtures?

It does **not** modify production code, tests, CI, or dependency manifests.
The experiment ran in an isolated workspace
(`%TEMP%\opencode\proleap-eval\`), never on the production build path. No
AGPL component was involved (ProLeap is MIT); no component was added to the
SystemaOps build.

## 2. Identity, license, dependencies (verified from source)

| Property | Verified value | How verified |
|---|---|---|
| Upstream | `github.com/uwol/proleap-cobol-parser` | cloned (`--depth 1`, commit `d1bfe75`) |
| Version | `4.0.0` | `pom.xml` `<version>` of upstream `main` |
| License | **MIT** (Copyright (c) 2017 Ulrich Wolffgang) | upstream `LICENSE` file + `pom.xml` `<licenses>` (both read) |
| Build requirement | JDK 17+ (built and run on the host JDK 21.0.12.1), Maven 3.9.16 | local build exit 0 |
| Compile dependencies | `org.antlr:antlr4:4.7.2`, `org.antlr:antlr4-runtime:4.7.2`, `org.slf4j:slf4j-api:2.0.9` | upstream `pom.xml` |
| Test dependencies | `junit:junit:4.13.1`, `ch.qos.logback:logback-classic:1.4.14` (test scope only) | upstream `pom.xml` |
| Distribution | **Not on Maven Central** (search API `numFound: 0`; `repo1` 404 for `io/github/uwol`). Not found under the published coordinate on the SciJava repository either. | live queries 2026-10-23 |

Distribution note: consuming ProLeap as a binary dependency would require
building from source or trusting a non-Central repository. This is a
supply-chain consideration for any future integration decision.

## 3. Experiment setup

- **Workspace (outside the repo):** `%TEMP%\opencode\proleap-eval\`
  - `proleap-cobol-parser/` — upstream clone, built with
    `mvn -q -DskipTests install` (exit 0), installed to the local Maven repo
  - `eval/` — one-class harness `eval.ProleapEval`
    (`analyzeFile(File, CobolSourceFormatEnum)` → prints
    `file \t OK|REJECT \t detail`; never throws on bad input)
  - `compare_parsers.py` — runs both parsers over the same fixture set and
    writes `results/parse-comparison.json`
- **Fixture set (5 real repository fixtures):**

| Fixture | Detected format (production detector) | Why selected |
|---|---|---|
| `fixtures/workload-copybook/cobol/MAIN.cob` | free | runtime-proven lane, contains COPY |
| `fixtures/workload-arithmetic/cobol/ARITH.cob` | fixed | fixed-format representative (oracle-proven lane) |
| `fixtures/workload-file-write-read/cobol/MAIN.cob` | free | smallest end-to-end runtime-proven workload |
| `fixtures/workload-comp/cobol/MAIN.cob` | free | capability-borderline fixture |
| `fixtures/workload-indexed-file/cobol/MAIN.cob` | free | BL-134 certified-subset fixture |

- **Format selection:** our side needs no format argument (the parser reads
  the text directly); the oracle's own `DockerOracleAdapter.detect_source_format`
  classified each file. ProLeap requires an explicit
  `CobolSourceFormatEnum` (see finding F-1) — the free-format files were run
  under `FIXED`, the closest available mode, with the mapping recorded in the
  results JSON.
- **SystemaOps side:** `engine.transformation.cobol_parser.CobolParser().parse(text)`
  (a non-exception result counts as OK). This is a parse-acceptance
  comparison, **not** a capability claim: capability classification (e.g. the
  COMP family remaining UNSUPPORTED at the capability layer) is a separate,
  stricter gate in this repository.

## 4. Results (exact, from `results/parse-comparison.json`)

| Fixture | Format | SystemaOps parser | ProLeap 4.0.0 (mode FIXED) |
|---|---|---|---|
| workload-copybook/MAIN.cob | free | OK | **REJECT** — `syntax error in line 1:7 mismatched input 'ENTIFICATION'` |
| workload-arithmetic/ARITH.cob | fixed | OK | **OK** (ASG built) |
| workload-file-write-read/MAIN.cob | free | OK | **REJECT** — same sequence-area error |
| workload-comp/MAIN.cob | free | OK | **REJECT** — same sequence-area error |
| workload-indexed-file/MAIN.cob | free | OK | **REJECT** — same sequence-area error |

Score: SystemaOps 5/5 accept, ProLeap 1/5 accept (the single fixed-format
fixture). The `ENTIFICATION` error is mechanical: ProLeap's FIXED
preprocessor strips columns 1–6 as the sequence area, chopping
`IDENTIFICATION` to `ENTIFICATION` for sources that begin at column 1.

Reproduction (from the experiment workspace):

```bash
mvn -q compile exec:java -Dexec.mainClass=eval.ProleapEval \
    -Dexec.args="FIXED <repo>/fixtures/workload-arithmetic/cobol/ARITH.cob"
python compare_parsers.py
```

Evidence copy (not committed, never staged):
`test-artifacts/p0-verification-2026-10-23/proleap-parse-comparison.json`
(SHA-256 recorded in that directory's `sha256sums.txt`).

## 5. Findings

- **F-1 (blocking for our estate): no free-format support exists in ProLeap
  4.0.0.** `CobolSourceFormatEnum` offers exactly `FIXED`, `TANDEM`,
  `VARIABLE`; a source-wide search for `FREE`/free-format in upstream
  `src/` returns **zero matches**, and `CobolParserParams` exposes no
  alternate flag. Our fixture estate is predominantly free-format (the
  production oracle detector classifies it so, and the certified runtime
  proofs run it as free format), so ProLeap in its current form cannot parse
  the majority of this repository's sources at all.
- **F-2: fixed-format parsing works** — the fixed-format fixture parsed
  cleanly and built its ASG, so the grammar itself is functional where the
  line format matches its only modes.
- **F-3: distribution gap** — not published to Maven Central; a binary
  dependency would need build-from-source (as done here) or a third-party
  repository, which the supply-chain posture of this repository (pinned,
  digest-verified images; pip/npm audits in CI) treats as a material
  consideration.
- **F-4: license is clean** — MIT, verified against both the `LICENSE` file
  and the POM. No AGPL component was involved at any point.

## 6. Verdict

**Evaluated, not integrated.** ProLeap is a legitimate MIT-licensed,
ANTLR4-based COBOL 85 parser, and it parsed the one fixture whose source
format matches its only supported modes. It is nevertheless **not a viable
replacement for, or addition to, the existing parser today**, because (a) it
cannot consume the free-format sources that dominate this repository's
certified fixture estate (F-1), (b) it is not distributed on Maven Central
(F-3), and (c) integration would add a second parsing stack whose output
would have to be reconciled with the existing IR and capability registry —
without any functional gain over the current oracle-proven parsing lane.

The existing parser, IR, and capability registry remain the single canonical
parsing path. This experiment changed no production file, no dependency
manifest, and no test.
