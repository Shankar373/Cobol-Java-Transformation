# Third-Party Notices

**Status:** Dependency inventory. Project license not yet selected (see
`docs/decisions/` and `KNOWN_ISSUES.md`); no `LICENSE` file is shipped.
This document records the direct/transitive dependencies and their stated
licenses for attribution purposes. It is not a license grant.

## Python (requirements.lock)
Direct dependencies (from requirements.txt):
- fastapi — MIT
- python-multipart — Apache-2.0
- uvicorn[standard] — BSD-3-Clause
- httpx — BSD-3-Clause
- pytest — MIT
- pytest-asyncio — Apache-2.0

Transitive dependencies are pinned in `requirements.lock`; their licenses are
standard permissive (MIT/BSD/Apache-2.0/PSF). Regenerate this inventory from
the lockfile before distribution.

## Frontend (frontend/package.json)
- react — MIT
- react-dom — MIT
- react-router-dom — MIT
- vite — MIT
- vitest — MIT
- @testing-library/* — MIT
- jsdom — MIT
- typescript — Apache-2.0

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
