# Lane D: GnuCOBOL on a real big-endian architecture (linux/s390x, emulated by QEMU).
# Purpose: an independent witness that COMP-5 is stored big-endian on a big-endian machine, so the explicit
# platform conversion can be checked against records a compiled program wrote there.  This is Linux on s390x,
# NOT z/OS and NOT IBM Enterprise COBOL: it proves byte order, nothing about IBM VSAM.
# Source: Ubuntu 22.04 package gnucobol3 (GnuCOBOL 3.1.2, GPL-3.0+ / LGPL-3.0+ runtime).  Base pinned by digest at build time.
FROM --platform=linux/s390x ubuntu:22.04
RUN apt-get update && apt-get install -y --no-install-recommends gnucobol3 gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/* && cobc --version | head -1
