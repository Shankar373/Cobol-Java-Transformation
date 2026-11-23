#!/usr/bin/env bash
# Build a Docker image in CI, retrying transient registry and DNS failures.
# Usage: scripts/ci/build-image.sh <Dockerfile> <tag> [platform [context-dir]]
#
# Two transient failure classes have failed whole CI jobs:
#  * Maven Central 502s while the offline Maven image downloads its precache with strict checksums
#    (certification run 41494148954, twice, different artifacts);
#  * the build container could not resolve archive.ubuntu.com / security.ubuntu.com for the pinned
#    GnuCOBOL apt install (CI, certification and supply-chain runs of f0418a1, 2026-11-11, two attempts each).
#
# Up to five attempts with a growing pause; Docker's layer cache resumes at the layer that failed. Before each
# attempt the runner's own resolver is checked and the result is printed, so an outage is visible in the log and
# never hidden. From the second attempt the build uses the host network: the bridge network's DNS forwarder is
# where the failures were seen, and the host resolver is the one the rest of the job already relies on. Nothing
# about the build changes - same Dockerfile, same pinned base digest and package versions, same smoke test - and a
# deterministic build error fails every attempt, so the job still fails; this only absorbs transient network errors.
#
# Optional persistent layer cache (CI only): when DOCKER_BUILDX_CACHE_ROOT names a directory (the workflows restore
# and save it with actions/cache) and `docker buildx` is available, the image is built with `docker buildx build
# --load` and a local cache (`--cache-from` / `--cache-to ... mode=max`) kept per Dockerfile + platform under that
# directory. The cache only skips layers whose inputs (instruction text, parent layer, copied files, pinned base
# digest) are identical; it changes neither the Dockerfile, the pins, the smoke tests nor the retry behaviour, and
# without the variable (local builds, scripts/deploy/build-production.sh) the build is the plain `docker build`.
set -euo pipefail

dockerfile="${1:?Usage: build-image.sh <Dockerfile> <tag>}"
tag="${2:?Usage: build-image.sh <Dockerfile> <tag> [platform [context-dir]]}"
platform="${3:-}"   # e.g. linux/s390x (needs QEMU binfmt on the runner); empty builds for the runner's architecture
context="${4:-.}"
attempts=5
cache_root="${DOCKER_BUILDX_CACHE_ROOT:-}"
use_buildx=0
if [ -n "$cache_root" ] && docker buildx version >/dev/null 2>&1; then
  use_buildx=1
  # One cache directory per Dockerfile and platform: a rebuilt layer of one image never evicts another image's.
  cache_name="$(printf '%s|%s' "$dockerfile" "${platform:-native}" | sha256sum | cut -c1-16)"
  cache_dir="$cache_root/$cache_name"
  mkdir -p "$cache_root"
fi

dns_report() {
  for host in archive.ubuntu.com security.ubuntu.com repo.maven.apache.org; do
    if getent hosts "$host" >/dev/null 2>&1; then
      echo "dns: $host resolves on the runner" >&2
    else
      echo "dns: $host does NOT resolve on the runner" >&2
    fi
  done
}

for attempt in $(seq 1 "$attempts"); do
  dns_report
  network=()
  if [ "$attempt" -gt 1 ]; then
    network=(--network host)
    echo "attempt $attempt/$attempts: building $tag on the host network" >&2
  fi
  args=()
  # The Ubuntu mirror fallback: only when this runner cannot resolve archive.ubuntu.com, only from the second
  # attempt, only for a Dockerfile that declares ARG APT_MIRROR. Same archive content and signatures.
  if [ "$attempt" -gt 1 ] && ! getent hosts archive.ubuntu.com >/dev/null 2>&1 && grep -q '^ARG APT_MIRROR' "$dockerfile"; then
    args=(--build-arg APT_MIRROR=mirrors.edge.kernel.org)
    echo "attempt $attempt/$attempts: archive.ubuntu.com does not resolve here; apt uses mirrors.edge.kernel.org" >&2
  fi
  if [ -n "$platform" ]; then args+=(--platform "$platform"); fi
  if [ "$use_buildx" -eq 1 ]; then
    # The docker-container builder runs BuildKit in its own container: the host network needs an explicit
    # entitlement (the workflows create the builder with --allow-insecure-entitlement network.host).
    bx_network=()
    if [ "${#network[@]}" -gt 0 ]; then bx_network=("${network[@]}" --allow network.host); fi
    rm -rf "$cache_dir.new"
    cache_args=(--cache-to "type=local,dest=$cache_dir.new,mode=max")
    if [ -d "$cache_dir" ]; then cache_args+=(--cache-from "type=local,src=$cache_dir"); fi
    if docker buildx build --load --pull "${bx_network[@]}" "${args[@]}" "${cache_args[@]}" -f "$dockerfile" -t "$tag" "$context"; then
      # Replace the previous cache by the freshly exported one (it contains every layer this build used).
      if [ -d "$cache_dir.new" ]; then rm -rf "$cache_dir" && mv "$cache_dir.new" "$cache_dir"; fi
      exit 0
    fi
    rm -rf "$cache_dir.new"
  elif docker build --pull "${network[@]}" "${args[@]}" -f "$dockerfile" -t "$tag" "$context"; then
    exit 0
  fi
  if [ "$attempt" -lt "$attempts" ]; then
    echo "build of $tag failed (attempt $attempt/$attempts); retrying in $((attempt * 30))s" >&2
    sleep $((attempt * 30))
  fi
done
echo "build of $tag failed after $attempts attempts" >&2
exit 1
