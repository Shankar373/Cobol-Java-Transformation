## Docker socket exposure (hardening note)

The production compose file mounts `/var/run/docker.sock` into the API container
so the COBOL oracle lane can invoke the host daemon. This grants the API
process effective host-level Docker control and is an accepted risk for the
certified oracle workflow.

Mitigations already in place:
- API image runs as non-root uid 10001 with `group_add` limited to the socket's
  group; container hardening flags (`no-new-privileges`, `--cap-drop ALL`) apply
  to sandbox containers via `engine/execution/container_hardening.py`.
- Only the six sandbox image names are invoked; no arbitrary image pull/run is
  exposed through the API.

If your policy forbids socket mounting:
1. Run the API process directly on the Docker host (no container) so it uses the
   local daemon without a socket mount, or
2. Provide a scoped Docker proxy (e.g. `tecnativa/docker-socket-proxy`) that
   permits only `CONTAINERS`/`IMAGES`/`EXEC` on the allowed sandbox images, and
   point `DOCKER_HOST` at it. The proxy must still expose the six sandbox images.

Never grant the API container `--privileged` or a writable socket on an
untrusted host. Re-evaluate this decision per deployment; it is a documented
accepted risk, not a silently enabled default.
EOF
