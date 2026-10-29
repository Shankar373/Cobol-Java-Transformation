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
- gnucobol (oracle) — GPL-3.0 (invoked as separate process via docker run)
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
  third-party template license applies.
EOF
