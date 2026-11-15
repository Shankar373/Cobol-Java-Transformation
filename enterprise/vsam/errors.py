"""Explicit refusals. A refusal never produces published output."""

from __future__ import annotations


class VsamRefusal(Exception):
    """The export cannot be migrated safely; ``code`` is a stable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class MigrationInterrupted(Exception):
    """The migration stopped on request (lost lease); its partial output and checkpoint are kept for the next run."""
