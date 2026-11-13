# Lane B: GnuCOBOL 3.2 built from the official source tarball, for an independent compiler-version check.
# It does NOT replace the pinned 3.1.2 baseline image (gnucobol-ocesql) and says nothing about IBM VSAM.
# Source: https://ftp.gnu.org/gnu/gnucobol/gnucobol-3.2.tar.xz  (GNU, GPL-3.0-or-later compiler, LGPL-3.0-or-later runtime)
# Base image pinned by digest; tarball pinned by sha256 (recorded when this lane was added).
FROM ubuntu@sha256:74b12b11ffa550fba1929ad4d8d16533c34f6612728469671afba1b03b66881c
ARG GC_SHA256=3bb48af46ced4779facf41fdc2ee60e4ccb86eaa99d010b36685315df39c2ee2
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libdb-dev libgmp-dev libncurses-dev libxml2-dev libjson-c-dev ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/gnucobol.tar.xz https://ftp.gnu.org/gnu/gnucobol/gnucobol-3.2.tar.xz \
    && echo "${GC_SHA256}  /tmp/gnucobol.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/gnucobol.tar.xz -C /tmp \
    && cd /tmp/gnucobol-3.2 && ./configure --prefix=/usr/local --with-db && make -j"$(nproc)" && make install \
    && ldconfig && rm -rf /tmp/gnucobol* && cobc --version | head -1
