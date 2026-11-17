# Security status (2026-11-18)

Overall: **AMBER**. Dependency audits are clean and ingestion code is defensive, but several documented design risks remain and the
production container carries scanner findings that need an owner decision.

## Scan results (supply-chain run 43777133111 on `a9a72b4`; the jobs rerun on every push)

| Check | Result |
|---|---|
| `pip-audit`, runtime lock (22 packages) | 0 known vulnerabilities |
| `pip-audit`, dev (30), type-check (6) and coverage (1) locks | 0 known vulnerabilities |
| `npm audit` (frontend) | 0 vulnerabilities of any severity |
| Frontend bundle secret guard (`verify-bundle-secrets.mjs`) | OK on every build |
| SBOMs (CycloneDX) for Python and frontend, release dependency manifest | produced and uploaded as workflow artifacts |
| Trivy, `systemaops-api` production image (before the base refresh) | 3 critical, 140 high |
| Trivy, GnuCOBOL and OCESQL oracle images | about 16 critical, 480 high each (Debian packages with no fixed version; test-only images) |
| Trivy, project Maven image | 5 critical, 64 high (62 high and 4 critical have fixes; test-only image) |

Trivy runs report-only in CI: a finding does not fail the build. That is a policy gap, not a pass.

### Production image findings

- **Fixed in this baseline:** the Python base image pin moved from `…0a310eee…` to `…a83ba18a…` (Debian 12.15, OpenSSL 3.0.22-1~deb12u2, apt 2.6.2),
  which removes the fixable OpenSSL and apt findings. The change is in `Dockerfile.production` and the backup and restore scripts. Its effect
  on the scan is confirmed by the supply-chain run on the baseline commit (see `TEST_AND_CI_EVIDENCE.md`).
- **Not fixed, owner decision:** the image bundles the static Docker CLI 27.3.1, built with Go 1.22.7. Most remaining fixable findings (1 critical and
  about 28 high) are Go standard-library issues in that binary. Moving to a newer CLI is a major-version change whose compatibility with the Docker
  engine on the deployment host cannot be tested here. The CLI is a client run inside the container, not a network-facing server.
- **No fix exists:** `libsqlite3-0` (CVE-2025-7458) and `zlib1g` (CVE-2023-45853) are critical in the scanner but have no fixed Debian package.

## Design risks on record (`docs/FINAL_GAP_REGISTER.md`)

- **G-01 (HIGH):** the production compose file mounts `/var/run/docker.sock` into the API container, which is root-equivalent on the host if the API is
  compromised. Documented in `docs/security/DOCKER_SOCKET_HARDENING.md`; needs rootless Docker or a remote sandbox host.
- **G-02 (HIGH):** authentication is three static shared bearer tokens (32+ characters). No users, OIDC, rotation, revocation or per-tenant ownership.
- **G-03:** artifact seals are hashes, not signatures; there is no key custody.
- **G-05:** with no token configured outside production the API is open (production refuses absent or trivial tokens).
- Tenant isolation, rate limiting and audit trails are not implemented for the new enterprise routes.

## Ingestion and archive safety (new code, tested)

- ZIP extraction refuses path traversal, absolute and non-portable names, symlinks and devices (by default), encrypted entries, case-colliding
  duplicates, count, depth, size and compression-ratio limits, counts bytes actually written, never overwrites and removes partial output.
- GitHub ingestion accepts only a strict `https://github.com/<owner>/<repo>` URL, allows redirects only to configured hosts, sends a token only to
  those hosts, never puts it in an error, never executes repository content, and refuses private repositories.
- The streaming VSAM upload path bypasses the generic body-size limit on purpose and enforces `Content-Length == dataset_bytes` and the dataset quota.

## Licences

`psycopg` and `psycopg-binary` are LGPL-3.0-only (listed in `docs/THIRD_PARTY_NOTICES.md`). Confirm they fit your distribution policy.

## Not verified

No penetration test, no threat model document, no secret scanning beyond the frontend bundle guard, no authorization tests for tenant isolation.
