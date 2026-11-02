#!/usr/bin/env bash
# Build a Docker image in CI, retrying transient registry failures.
# Usage: scripts/ci/build-image.sh <Dockerfile> <tag>
#
# The offline Maven image downloads its precache from Maven Central with
# strict checksums (-C); a single 502 from Central failed a whole CI job
# (certification run 41494148954, twice, different artifacts). Up to three
# attempts with a growing pause; Docker's layer cache resumes at the layer
# that failed. A deterministic build error fails all three attempts and the
# job still fails - this only absorbs transient network errors.
set -euo pipefail

dockerfile="${1:?Usage: build-image.sh <Dockerfile> <tag>}"
tag="${2:?Usage: build-image.sh <Dockerfile> <tag>}"

for attempt in 1 2 3; do
  if docker build --pull -f "$dockerfile" -t "$tag" .; then
    exit 0
  fi
  if [ "$attempt" -lt 3 ]; then
    echo "build of $tag failed (attempt $attempt/3); retrying in $((attempt * 30))s" >&2
    sleep $((attempt * 30))
  fi
done
echo "build of $tag failed after 3 attempts" >&2
exit 1
