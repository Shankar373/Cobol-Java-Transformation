"""Deterministic Java/Spring name derivation for CICS mapping.

CICS and COBOL identifiers use hyphens and upper case (``WS-CUST-ID``,
``CUSTINQ``).  These helpers derive stable, collision-reducible Java
identifiers without inventing names: every character is preserved.

Rules:
- A token is a maximal run of alphanumerics (``-`` and ``_`` separate tokens).
- ``pascal`` keeps each token's first letter upper-cased and the remainder
  lower-cased, then joins without separators.
- ``camel`` is ``pascal`` with the first letter lower-cased.

These helpers are pure and deterministic: the same input always yields the
same identifier.
"""

from __future__ import annotations

import re

_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def pascal(value: str) -> str:
    """Derive a PascalCase identifier from a COBOL/CICS name."""
    tokens = [t for t in _TOKEN_SPLIT.split(value or "") if t]
    return "".join(_capitalize(token) for token in tokens) or "Unknown"


def camel(value: str) -> str:
    """Derive a camelCase identifier from a COBOL/CICS name."""
    result = pascal(value)
    return result[0].lower() + result[1:] if result else "unknown"


def _capitalize(token: str) -> str:
    """Capitalize first letter and lower-case the remainder of a token."""
    lowered = token.lower()
    return lowered[0].upper() + lowered[1:]