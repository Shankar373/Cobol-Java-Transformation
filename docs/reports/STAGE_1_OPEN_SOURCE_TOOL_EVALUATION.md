# Stage 1 open-source tool evaluation

Date: 2026-11-13. Scope: tools that could add independent verification value to the COBOL + VSAM migration. Every claim is
marked **verified** (observed in this session) or **not verified** (stated from general knowledge or a listing and not checked).

## Verified environment facts

| Fact | Evidence |
|---|---|
| Reference image `gnucobol-ocesql:latest` runs GnuCOBOL **3.1.2.0**, indexed file handler **BDB** (Berkeley DB), sequential handler built-in, variable file format 0, arch amd64, id `sha256:4c60283d...`, repo digest `gnucobol-ocesql@sha256:4c60283d12f9...` | `cobc --version`, `cobc --info`, `docker image inspect` |
| Docker can run `linux/s390x` containers (QEMU emulation); `uname -m` prints `s390x` | `docker run --platform linux/s390x alpine uname -m` |
| `debian:bookworm` has no s390x manifest from this registry; `ubuntu:22.04`, `ubuntu:24.04`, `alpine:3.20` do | `docker manifest inspect` |
| Ubuntu 22.04 package `gnucobol3` gives GnuCOBOL 3.1.2.0 on s390x, indexed handler BDB | `docker build docker/gnucobol-s390x` |
| The GnuCOBOL 3.2 source tarball and the VBISAM SourceForge page are reachable from this host | HTTP 200 from `ftp.gnu.org/gnu/gnucobol/gnucobol-3.2.tar.xz` and `sourceforge.net/projects/vbisam/files/` |
| GCBLUnit: GPL-2.0, not archived, last push 2021-02-27 | GitHub API |
| COBOL Check: Apache-2.0, **archived**, last push 2026-05-28 | GitHub API |
| Zowe CLI: EPL-2.0, not archived, active | GitHub API |

## Decisions

| Tool | Purpose | Decision | Reason |
|---|---|---|---|
| **GnuCOBOL 3.1.2** (existing image) | reference compiler and runtime | **Adopted (existing baseline)** | already pinned and used by every oracle test; not replaced |
| **GnuCOBOL 3.1.2 on linux/s390x** (`docker/gnucobol-s390x`) | independent big-endian witness for COMP-5 byte order | **Adopted as an optional test oracle (Lane D)** | real compiled program on a big-endian CPU; the s390x records converted to x86 equal the x86 records byte for byte. Built from the Ubuntu package, base image not yet pinned by digest (**open**). Linux on s390x is not z/OS: byte order only |
| **GnuCOBOL 3.2** | second compiler version for compatibility | **Built and run (local lane)** | `docker/gnucobol-3.2` builds GnuCOBOL 3.2.0 from the official tarball (hash-pinned), image id `sha256:9081711f49195451c8923055cf7afea1b63710eb1989b0c53459ef7d871aea0d`. The 25 Docker-lane differentials pass with `VSAM_ORACLE_IMAGE=gnucobol-3.2:local` (the override was proven by a bogus image failing). Local only: CI does not build this image, so these tests skip there. Not a substitute for the 3.1.2 baseline | Provenance: release 2023-07-28 (NEWS, GNU FTP). GNU publishes only a `.sig` for the tarball, no checksum file: the pinned SHA-256 in the Dockerfile was computed from the download when the lane was added and the `.sig` was **not** verified; licence (GPL-3.0-or-later compiler, LGPL-3.0-or-later runtime) is the project's documented licence but was not re-read from the tarball. **Decision: adopt as an optional local lane (not part of required CI)**; it never replaces 3.1.2 |
| **VBISAM** (alternate ISAM backend for GnuCOBOL) | check that results do not depend on the BDB backend | **Deferred (not built)** | Source: SourceForge project `vbisam`; latest release found is 2.0 (2013-03-06), no later upstream release found, upstream effectively unmaintained; a 2016 report says 2.0 fails to build on Ubuntu 16.04. Licence: README says GPL or LGPL with COPYING/COPYING.LIB; the LGPL version was **not** verified. GnuCOBOL 3.2 `configure.ac` offers `--with-vbisam` (needs libvbisam >= 2.0). Reason for deferral: it is a file-handler backend, not a VSAM emulator, and Stage 1 conversions are proved on byte layouts of fixed and RDW files, not through indexed-file internals, so it adds no independent verification of the claims made here; an unmaintained 2013 library with a reported build failure is a poor trade for an optional lane. Revisit only if indexed-file behaviour (not layouts) becomes part of a claim. Facts come from a web check on 2026-11-14 (project page not fetched directly; one fact from a search snippet) |
| **GCBLUnit** | COBOL unit tests | **Rejected** | GPL-2.0 and unmaintained since 2021; the pytest plus GnuCOBOL harness already covers the need |
| **COBOL Check** | COBOL unit tests | **Rejected** | archived upstream; not introduced as a dependency |
| **Zowe / zowe-cli** | access to a real z/OS | **Not usable now** | needs an authorized z/OS environment and credentials, which are not available; running the client proves nothing about z/OS. IBM runtime validation is **externally blocked** |
| **NIST COBOL85 test suite** | compiler conformance | **Not used** | not part of this project's scope; GnuCOBOL's own conformance is not what is being tested |

## What this means for the verdict

No open-source tool provides IBM VSAM or IBM Enterprise COBOL behaviour. The strongest independent evidence available is: GnuCOBOL
3.1.2 on x86-64 and on s390x (byte order and width), plus an independent GnuCOBOL consumer reading migrated data. IBM-specific
claims stay unverified and BLOCKED on access to a licensed IBM environment (an owner decision).
