"""The one entrypoint-selection rule, shared by the planner and the generator.

Never guesses - not from file order, class order or name order:

* a requested entrypoint must match exactly one candidate (compared with
  ``normalise``: case-, dash-, underscore- and whitespace-insensitive);
* with none requested, the entrypoint is the only candidate, or the only candidate that no
  *other* candidate CALLs (a self-CALL does not make a program non-root);
* several roots, or none (every program is a CALL target), is an error naming them.

``resolve_entrypoint`` returns ``(name, "")`` or ``("", reason)``; callers must treat a
non-empty reason as a refusal and never substitute another candidate.
"""
from __future__ import annotations

import re
from collections.abc import Sequence


def normalise(name: str) -> str:
    """Normalise a program-id / class name for comparison."""
    return re.sub(r"[-_\s]+", "", name or "").upper()


def resolve_entrypoint(
    candidates: Sequence[str],
    requested: str,
    call_edges: Sequence[tuple[str, str]] = (),
) -> tuple[str, str]:
    """Select the entrypoint among ``candidates`` or return ``("", reason)``."""
    if not candidates:
        return "", "No program class is available to be the application entrypoint"
    listing = ", ".join(sorted(candidates))

    wanted = requested.strip() if requested else ""
    if wanted:
        matches = [name for name in candidates if normalise(name) == normalise(wanted)]
        if len(matches) == 1:
            return matches[0], ""
        if not matches:
            return "", f"Requested entrypoint '{wanted}' matches no program (programs: {listing})"
        return "", (f"Requested entrypoint '{wanted}' is ambiguous: "
                    f"{len(matches)} programs share that name")

    if len(candidates) == 1:
        return candidates[0], ""

    called = {normalise(target) for source, target in call_edges if normalise(source) != normalise(target)}
    roots = [name for name in candidates if normalise(name) not in called]
    if len(roots) == 1:
        return roots[0], ""
    if not roots:
        return "", ("No entrypoint can be derived: every program is the target of "
                    f"a CALL (programs: {listing}); request one explicitly")
    return "", ("Entrypoint is ambiguous: no entrypoint was requested and "
                f"{len(roots)} programs are not called by any other "
                f"({', '.join(sorted(roots))}); request one explicitly")
