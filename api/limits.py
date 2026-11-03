"""Shared positive-integer environment limit parsing for the control plane."""

from __future__ import annotations

import logging
import os


def env_int_limit(name: str, default: int, logger: logging.Logger) -> int:
    """Read a positive integer limit from ``name`` in the environment.

    Unset, blank, invalid, or non-positive values fall back to ``default``;
    invalid values log one warning through ``logger``.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %d", name, raw, default)
        return default
    return value if value > 0 else default
