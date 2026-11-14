"""Role-based access control for the control plane (roadmap unit 19, identity source pluggable).

Three roles, ordered: ``viewer`` (read), ``operator`` (read and start work: ingest, upload, modernize,
validate), ``approver`` (everything, including recording an approval).  Tokens map to roles through
``CONTROL_PLANE_ROLE_TOKENS``, a JSON object ``{"<token>": "<role>"}``.  The single
``CONTROL_PLANE_API_TOKEN`` keeps working and, in role mode, is the ``approver`` (administrator) token.

This module decides *what a role may do*; it does not decide *who a caller is*.  Mapping an OIDC identity
to one of the three roles needs an identity provider and is an owner decision (see
``docs/audits/OWNER_DECISIONS.md``): that mapping would call :func:`allows` with the role it resolves.

Fail closed: an unparsable or invalid ``CONTROL_PLANE_ROLE_TOKENS`` grants nobody anything.
"""

from __future__ import annotations

import hmac
import json
import re

ROLES = ("viewer", "operator", "approver")
_RANK = {role: index for index, role in enumerate(ROLES)}
_APPROVAL_PATH = re.compile(r"^/runs/[^/]+/approval/?$")
_SAFE_METHODS = frozenset({"GET", "HEAD"})
#: Converted datasets and their reports are customer data (rejection reasons quote field values): reading either
#: needs more than the read-only role.
_DATASET_DOWNLOAD_PATH = re.compile(r"^/applications/[^/]+/vsam/migrations/[^/]+(/download)?/?$")

#: Shortest token accepted for a role (the production floor for the shared token is 32).
MIN_ROLE_TOKEN_LENGTH = 16


class RoleConfigError(ValueError):
    """``CONTROL_PLANE_ROLE_TOKENS`` is not a valid token-to-role mapping."""


def parse_role_tokens(raw: "str | None") -> dict[str, str]:
    """Validate and return the mapping; ``{}`` when unset or blank."""
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RoleConfigError(f"CONTROL_PLANE_ROLE_TOKENS is not valid JSON: {error.msg}") from error
    if not isinstance(data, dict) or not data:
        raise RoleConfigError("CONTROL_PLANE_ROLE_TOKENS must be a non-empty JSON object")
    for token, role in data.items():
        if not isinstance(token, str) or len(token) < MIN_ROLE_TOKEN_LENGTH:
            raise RoleConfigError(
                f"every role token must be a string of at least {MIN_ROLE_TOKEN_LENGTH} characters")
        if role not in _RANK:
            raise RoleConfigError(f"role {role!r} is not one of {', '.join(ROLES)}")
    return dict(data)


def required_role(method: str, path: str) -> str:
    """The least role allowed to call ``method path``."""
    if method.upper() in _SAFE_METHODS:
        return "operator" if _DATASET_DOWNLOAD_PATH.match(path) else "viewer"
    if method.upper() == "POST" and _APPROVAL_PATH.match(path):
        return "approver"
    return "operator"


def allows(role: str, method: str, path: str) -> bool:
    return _RANK.get(role, -1) >= _RANK[required_role(method, path)]


def role_for_token(provided: str, role_tokens: dict[str, str], admin_token: "str | None") -> "str | None":
    """The role of a presented token, comparing against every candidate in constant time."""
    if not provided:
        return None
    found: "str | None" = None
    for token, role in role_tokens.items():
        if hmac.compare_digest(provided.encode("utf-8"), token.encode("utf-8")):
            found = role
    if admin_token and hmac.compare_digest(provided.encode("utf-8"), admin_token.encode("utf-8")):
        found = "approver"
    return found
