"""Frontend dependency-audit gate with one narrowly scoped, self-expiring exception.

Reads ``npm audit --json`` (the *complete* tree, dev dependencies included) on stdin and fails on every actionable finding except the
documented exception in ``docs/supply-chain/NPM_AUDIT_EXCEPTION.md``:

* advisory ``GHSA-fc5q-39xc-vjpf`` (picomatch ReDoS), and the packages that are flagged only because they depend on picomatch;
* the exception is honoured only while ``npm ls picomatch --omit=dev`` shows picomatch is absent from the production tree;
* it expires when an upstream release outside the vulnerable range exists (``--latest-picomatch``) or on ``EXPIRES``.

Usage: ``npm audit --json | python tools/npm_audit_gate.py --prod-tree "$(npm ls picomatch --omit=dev --json)" [--latest-picomatch X.Y.Z]``
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys

ADVISORY = "GHSA-fc5q-39xc-vjpf"
EXCEPTED_PACKAGE = "picomatch"
EXPIRES = datetime.date(2027, 3, 1)  # review date: remove the exception once an upstream fix exists
FIXED_BEYOND = (4, 0, 7)  # the last vulnerable release; anything newer must be taken, not excepted


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("-")[0].split(".")[:3] if part.isdigit())


def _only_via(name: str, vulns: dict, allowed: set[str]) -> bool:
    """True when every cause of *name* is the excepted advisory or an allowed package."""
    for item in vulns[name]["via"]:
        if isinstance(item, str):
            if item not in allowed:
                return False
        elif not item.get("url", "").endswith(ADVISORY):
            return False
    return True


def evaluate(audit: dict, prod_tree: dict, latest_picomatch: str | None, today: datetime.date) -> list[str]:
    """Return the reasons the gate fails (empty = pass)."""
    vulns = audit.get("vulnerabilities", {})
    if not vulns:
        return []
    problems: list[str] = []
    if "dependencies" in prod_tree and EXCEPTED_PACKAGE in json.dumps(prod_tree["dependencies"]):
        problems.append(f"{EXCEPTED_PACKAGE} is in the PRODUCTION dependency tree: the dev-only exception does not apply")
    if today > EXPIRES:
        problems.append(f"the {ADVISORY} exception expired on {EXPIRES}: re-review or remove it")
    if latest_picomatch and _version(latest_picomatch) > FIXED_BEYOND:
        problems.append(f"picomatch {latest_picomatch} is published: upgrade instead of excepting {ADVISORY}")
    allowed = {EXCEPTED_PACKAGE}
    changed = True
    while changed:  # packages flagged only because of the excepted ones
        changed = False
        for name in vulns:
            if name not in allowed and _only_via(name, vulns, allowed):
                allowed.add(name)
                changed = True
    for name, entry in sorted(vulns.items()):
        if name not in allowed:
            problems.append(f"{name} ({entry.get('severity')}): not covered by the exception")
        elif name == EXCEPTED_PACKAGE and not _only_via(name, vulns, set()):
            problems.append(f"{name}: an advisory other than {ADVISORY} also applies")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod-tree", default="{}", help="JSON of `npm ls picomatch --omit=dev --json`")
    parser.add_argument("--latest-picomatch", default=None)
    args = parser.parse_args(argv)
    audit = json.load(sys.stdin)
    problems = evaluate(audit, json.loads(args.prod_tree or "{}"), args.latest_picomatch, datetime.date.today())
    excepted = sorted(audit.get("vulnerabilities", {}))
    if problems:
        print("npm audit gate FAILED:", *problems, sep="\n  - ")
        return 1
    if excepted:
        print(f"npm audit gate passed with the documented exception for {ADVISORY}; excepted packages: {', '.join(excepted)}")
    else:
        print("npm audit gate passed: no vulnerabilities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
