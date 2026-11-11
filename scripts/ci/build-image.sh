#!/usr/bin/env bash
# Build a Docker image in CI, retrying transient registry and DNS failures.
# Usage: scripts/ci/build-image.sh <Dockerfile> <tag>
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
set -euo pipefail

dockerfile="${1:?Usage: build-image.sh <Dockerfile> <tag>}"
tag="${2:?Usage: build-image.sh <Dockerfile> <tag>}"
attempts=5

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
  if docker build --pull "${network[@]}" "${args[@]}" -f "$dockerfile" -t "$tag" .; then
    exit 0
  fi
  if [ "$attempt" -lt "$attempts" ]; then
    echo "build of $tag failed (attempt $attempt/$attempts); retrying in $((attempt * 30))s" >&2
    sleep $((attempt * 30))
  fi
done
echo "build of $tag failed after $attempts attempts" >&2
exit 1
