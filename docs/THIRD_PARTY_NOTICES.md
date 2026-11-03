# Third-Party Notices

**Status:** Dependency inventory. The project is licensed under the
Apache License 2.0 (`LICENSE`, `NOTICE`; decided 2026-11-03).
This document records the direct/transitive dependencies and their stated
licenses for attribution purposes. It is not a license grant.

## Shipped dependencies

Generated from the lockfiles by `scripts/supply-chain/generate_notices.py`
(licenses as declared in PyPI / npm metadata for the pinned version);
`--check` runs in the test suite and fails when a locked package is missing
or listed at another version. Development and CI tooling (pytest, httpx,
vite, vitest, TypeScript, testing-library, jsdom, pip-audit, cyclonedx-bom)
does not ship and is not listed.

<!-- BEGIN GENERATED: scripts/supply-chain/generate_notices.py -->

### Python (production image: `requirements.lock`)

| Package | Version | License | Platform |
|---|---|---|---|
| `annotated-doc` | 0.0.5 | MIT | all |
| `annotated-types` | 0.7.0 | MIT License | all |
| `anyio` | 4.14.2 | MIT | all |
| `click` | 8.4.2 | BSD-3-Clause | all |
| `colorama` | 0.4.6 | BSD License | sys_platform == "win32" |
| `fastapi` | 0.141.1 | MIT | all |
| `h11` | 0.16.0 | MIT License | all |
| `httptools` | 0.8.0 | MIT | all |
| `idna` | 3.15 | BSD-3-Clause | all |
| `pydantic` | 2.13.4 | MIT | all |
| `pydantic_core` | 2.46.4 | MIT | all |
| `python-dotenv` | 1.2.4 | BSD-3-Clause | all |
| `python-multipart` | 0.0.32 | Apache-2.0 | all |
| `PyYAML` | 6.0.3 | MIT License | all |
| `starlette` | 1.3.1 | BSD-3-Clause | all |
| `typing-extensions` | 4.15.0 | PSF-2.0 | all |
| `typing-inspection` | 0.4.2 | MIT | all |
| `uvicorn` | 0.52.3 | BSD-3-Clause | all |
| `uvloop` | 0.23.0 | Apache Software License / MIT License | sys_platform != "win32" |
| `watchfiles` | 1.2.0 | MIT License | all |
| `websockets` | 17.0.1 | BSD-3-Clause | all |

### Frontend (bundled into the SPA: non-dev `frontend/package-lock.json`)

| Package | Version | License |
|---|---|---|
| `js-tokens` | 4.0.0 | MIT |
| `loose-envify` | 1.4.0 | MIT |
| `react` | 18.3.1 | MIT |
| `react-dom` | 18.3.1 | MIT |
| `scheduler` | 0.23.2 | MIT |

<!-- END GENERATED -->

## Container / external tools (process boundary, not linked)
- eclipse-temurin (JDK) — GPLv2 + Classpath Exception
- gnucobol (oracle) — compiler `cobc` GPL-3.0; runtime library `libcob4`
  LGPL-3.0 (Ubuntu 22.04 `gnucobol3 3.1.2-5`; invoked as a separate process
  via docker run)
- Oracle image libraries (Ubuntu 22.04 packages, read from the built image
  2026-11-02): Berkeley DB `libdb5.3 5.3.28` — Sleepycat License (BDB
  before 6.0; copyleft-style source-availability condition on
  redistribution); GMP `libgmp10 6.2.1` — LGPL-3.0 / GPL-2.0 dual;
  ncurses `6.3` — MIT-style (X11); libxml2 `2.9.13` — MIT. The oracle
  image is built locally from `Dockerfile.gnucobol` and is not distributed
  by this project; distributing it requires legal review (Sleepycat).
- maven — Apache-2.0
- docker CLI — Apache-2.0
- nginx — BSD-2-Clause
- node/npm — MIT

## Notes
- GnuCOBOL is invoked as a separate process (oracle) and is not linked into
  this project's code; running it does not impose GPL on this project. Any
  plan to vendor/embed GnuCOBOL source or ship a monolithic image requires
  legal review.
- Generated Java output is produced from project-owned templates; no
  third-party template license applies to the generated source. The
  generated *build* pulls framework dependencies, and the runnable jar
  bundles them: Spring Boot 3.2.5 (fat jar) — Apache-2.0; Quarkus 3.15.1
  (uber-jar) — Apache-2.0; Micronaut platform 4.6.3 (shaded jar) —
  Apache-2.0; SLF4J `slf4j-nop` 2.0.16 — MIT. A distributed generated jar
  must carry those notices (Maven puts the dependencies' `META-INF`
  license files in the jar; a shaded jar should be checked with the
  shade plugin's notice handling before distribution).
