"""Job lifecycle for ingestion and migration jobs.

A job reaches SUCCEEDED only through PUBLISHING, and only when the completion
evidence proves processing, validation, checksum verification and artifact
publication all happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class JobState(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    VALIDATING = "VALIDATING"
    PUBLISHING = "PUBLISHING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


TERMINAL_STATES = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.REFUSED,
        JobState.CANCELLED,
        JobState.EXPIRED,
    }
)

_S = JobState
_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    _S.CREATED: frozenset({_S.QUEUED, _S.CANCELLED, _S.REFUSED, _S.FAILED, _S.EXPIRED}),
    _S.QUEUED: frozenset({_S.RUNNING, _S.CANCELLED, _S.EXPIRED, _S.FAILED}),
    _S.RUNNING: frozenset(
        {_S.RETRYING, _S.VALIDATING, _S.FAILED, _S.CANCELLED, _S.REFUSED}
    ),
    _S.RETRYING: frozenset({_S.QUEUED, _S.RUNNING, _S.FAILED, _S.CANCELLED}),
    _S.VALIDATING: frozenset({_S.PUBLISHING, _S.FAILED, _S.CANCELLED, _S.REFUSED}),
    _S.PUBLISHING: frozenset({_S.SUCCEEDED, _S.FAILED}),
}


class InvalidTransition(Exception):
    """The requested job state change is not allowed."""


class IncompleteEvidence(InvalidTransition):
    """SUCCEEDED was requested without complete completion evidence."""


@dataclass(frozen=True)
class CompletionEvidence:
    processed: bool = False
    validated: bool = False
    checksum_verified: bool = False
    published: bool = False

    def missing(self) -> list[str]:
        return [name for name, ok in vars(self).items() if not ok]


def is_terminal(state: JobState) -> bool:
    return state in TERMINAL_STATES


def can_transition(current: JobState, target: JobState) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


def next_state(
    current: JobState,
    target: JobState,
    evidence: CompletionEvidence | None = None,
) -> JobState:
    """Validate ``current -> target`` and return ``target``."""
    if not can_transition(current, target):
        raise InvalidTransition(f"{current.value} -> {target.value} is not allowed")
    if target is JobState.SUCCEEDED:
        missing = (evidence or CompletionEvidence()).missing()
        if missing:
            raise IncompleteEvidence(
                "SUCCEEDED requires completed " + ", ".join(missing)
            )
    return target
