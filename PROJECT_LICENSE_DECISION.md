# Project License Decision Report

Date: 2026-10-30
Status: **DECIDED 2026-11-03 - Apache-2.0** (owner decision during the architecture audit).
`LICENSE` (canonical Apache License 2.0 text) and `NOTICE` are committed at the
repository root; sections 1-3 below record the state before the decision.

## 1. Current state

- No top-level `LICENSE` file exists.
- No copyright header policy is enforced.
- Third-party notices: `docs/THIRD_PARTY_NOTICES.md` exists.
- Dependencies: Python (FastAPI, uvicorn, httpx, pytest) MIT/Apache/BSD; frontend (React, Vite, Vitest) MIT.
- Generated artifacts include Java source intended for customer deployment; license terms affect redistribution.

## 2. Owner decision required

Select one SPDX license for the platform source and generated-artifact terms.

## 3. Options

| Option | SPDX | Commercial use | Modification | Distribution | Patent grant | Notes |
|---|---|---|---|---|---|---|
| Apache-2.0 | Apache-2.0 | Yes | Yes | Yes (with notice) | Yes | Recommended for enterprise tooling; protects against patent claims |
| MIT | MIT | Yes | Yes | Yes | No | Simple; minimal friction |
| BSD-3-Clause | BSD-3-Clause | Yes | Yes | Yes | No | Similar to MIT with non-endorsement clause |
| Proprietary / commercial | (custom) | Restricted | Restricted | Restricted | Custom | Required if generated artifacts must not be redistributed |

## 4. Dependency and redistribution impact

- All direct runtime dependencies are permissive (MIT/Apache/BSD), compatible with all four options.
- No copyleft (GPL/AGPL) dependencies identified in requirements.txt or frontend package.json.
- Generated Java *source* incorporates no third-party source beyond the standard JDK. The generated *runnable jars* bundle framework dependencies (Spring Boot fat jar, Quarkus uber-jar, Micronaut shaded jar — Apache-2.0; `slf4j-nop` — MIT), so a distributed jar must carry their notices (corrected 2026-11-02, Phase 4; see `docs/THIRD_PARTY_NOTICES.md`).
- If the platform is offered as SaaS, AGPL is not triggered because no AGPL dependency exists.

## 5. Recommendation

Apache-2.0 is recommended because it provides an express patent grant and is compatible with enterprise adoption while remaining permissive. Final selection remains owner-blocked.

## 6. Prepared (not committed) changes

- Add top-level `LICENSE` with chosen SPDX text.
- Update `README.md` license section.
- Add license headers policy to contribution docs if required.
- Update `docs/THIRD_PARTY_NOTICES.md` if a notice appendix is required by the chosen license.

## 7. Blocker

Owner must approve the license choice before committing `LICENSE`.
