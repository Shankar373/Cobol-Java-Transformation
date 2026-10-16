#!/usr/bin/env bash
# Build + tag a production release of the SystemaOps stack.
# Usage: ./scripts/deploy/build-production.sh [TAG]
# Builds: API image, gnucobol oracle image, maven-offline image, and pulls
# the pinned Java runtime image (same digest the engine executes).
set -euo pipefail
cd "$(dirname "$0")/../.."

TAG="${1:-production}"
RUNTIME_DIGEST="$(python3 -c 'from engine.candidate.docker_spring_boot_adapter import DockerSpringBootConfig; print(DockerSpringBootConfig().runtime_digest)')"

docker build --pull -f Dockerfile.production -t "systemaops-api:${TAG}" .
docker build --pull -f Dockerfile.gnucobol -t gnucobol-ocesql:latest .
docker build --pull -f Dockerfile.maven-offline -t maven-offline-springboot:latest .
docker pull "$RUNTIME_DIGEST"
docker tag "$RUNTIME_DIGEST" eclipse-temurin:21-jdk

python3 scripts/record_docker_image_provenance.py \
  --build-image maven-offline-springboot:latest \
  --runtime-image eclipse-temurin:21-jdk \
  --output "test-artifacts/docker-image-provenance.${TAG}.json"

echo "OK: release images built and tagged systemaops-api:${TAG}"
