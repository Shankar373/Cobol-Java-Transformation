"""Record immutable Docker identities for candidate verification.

This script uses the same image-provenance contract as
``DockerSpringBootCandidateAdapter``. It resolves the locally built Maven
image to either its registry RepoDigest or its immutable local Image ID, and
it requires the pulled Java runtime image to match the immutable RepoDigest
configured in ``DockerSpringBootConfig``.

Run from the repository root:

    python scripts/record_docker_image_provenance.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.candidate.docker_spring_boot_adapter import DockerSpringBootConfig
from engine.candidate.image_provenance import (
    DEFAULT_PROVENANCE_PATH,
    record_adapter_provenance,
    write_adapter_provenance,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the recorder command-line interface."""
    config = DockerSpringBootConfig()
    parser = argparse.ArgumentParser(
        description="Record immutable Docker identities for candidate verification."
    )
    parser.add_argument(
        "--build-image",
        default=config.build_image,
        help="Locally built Maven image reference.",
    )
    parser.add_argument(
        "--runtime-image",
        default=config.runtime_image,
        help="Externally pulled Java runtime image reference.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_PROVENANCE_PATH),
        help="Where to write the auditable provenance record.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Record provenance and print the identities selected for verification."""
    args = build_parser().parse_args(argv)
    config = DockerSpringBootConfig()

    try:
        provenance = record_adapter_provenance(
            build_image=args.build_image,
            runtime_image=args.runtime_image,
            expected_runtime_digest=config.runtime_digest,
        )
        output_path = write_adapter_provenance(provenance, args.output)
    except ValueError as exc:
        print(f"docker provenance recording failed: {exc}", file=sys.stderr)
        return 2

    print(f"build identity ({provenance.build_identity_kind}): {provenance.build_identity}")
    print(f"runtime identity (repo-digest): {provenance.runtime_identity}")
    print(f"provenance record: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
