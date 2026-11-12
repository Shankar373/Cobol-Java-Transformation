# Validation summaries - certified corpus, four runtimes

Per-application validation summaries (Conversion, Compilation with JDK, Runtime, Business equivalence, unsupported
constructs, warnings, what is not proven) produced by `GET /runs/{id}/validation-summary`
(`engine/verification/validation_summary.py`) while the corpus certification ran. Each field is derived from the run's
stored evidence only; nothing is estimated.

| | |
|---|---|
| Code commit that produced them | `801d2315b150b732ffa8bd5c3391c0bae684b2c4` |
| Corpus certification run | [43188835053](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43188835053) - success, `plain_java`, `spring_boot`, `quarkus`, `micronaut` each CERTIFIED (55 apps, 45 VERIFIED, independent AGREE 45/45) |
| Supply chain run on that commit | [43188835063](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43188835063) - success |
| CI run on that commit | [43188835001](https://github.com/Shankar373/Cobol-Java-Transformation/actions/runs/43188835001) - **its "Dependency map is current" step failed** (the map was regenerated while the new module was still untracked); fixed in the next commit. The summaries are unaffected, since they come from the certification run |

Files: `validation_summaries_<runtime>.jsonl` (one row per application that reached a verdict), and three rendered
examples in `samples/`.

## What the rows show

Each runtime has 46 rows. The other 9 corpus applications are refused by name at the capability gate: they have no run
verdict, so there is nothing to summarise and no summary is invented for them.

| Runtime | Rows | Conversion / Compilation / Runtime / Business equivalence | Others |
|---|---|---|---|
| plain_java | 46 | 45 x SUCCESS/PASS/PASS/PASS | 1 x SUCCESS/FAIL/NOT_RUN/NOT_EVALUATED (`workload-studentproc`, verdict UNAVAILABLE; the evidence records a build-phase exit 1, so no behaviour was compared) |
| spring_boot | 46 | 45 x SUCCESS/PASS/PASS/PASS | same single application |
| quarkus | 46 | 45 x SUCCESS/PASS/PASS/PASS | same single application |
| micronaut | 46 | 45 x SUCCESS/PASS/PASS/PASS | same single application |

All 46 applications get identical statuses on all four runtimes. The recorded JDK is OpenJDK 21.0.12 in every row
(required floor: 17).

## What PASS means - and does not

Business equivalence PASS means every comparator (stdout, stderr, exit status, files) MATCHed the GnuCOBOL 3.1.2 reference
for the recorded input, with no skipped or unavailable checks. It does **not** mean IBM equivalence (no IBM runtime
evidence exists), equivalence for other inputs, or verified REST/HTTP behaviour. Jakarta EE is not certified and is absent
from this evidence; Quarkus and Micronaut are certified in command mode only.
