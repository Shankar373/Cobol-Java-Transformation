"""Type-check gate: mypy must report no error that is not in the committed baseline, and the baseline must
not list an error that no longer occurs.

The baseline (``tests/mypy_baseline.txt``) records the type errors that existed when the gate was introduced,
one ``count<TAB>path|[code]|message`` line each (no line numbers, so an edit above an error does not
break the gate).  The gate is a ratchet:

* a **new** error -- or more occurrences of a known one -- fails;
* a **stale** baseline entry (the error was fixed) fails too, so the baseline can only shrink.

Usage::

    python tools/mypy_gate.py --check     # CI
    python tools/mypy_gate.py --update    # after fixing errors: rewrite the baseline (never to add errors)
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "tests" / "mypy_baseline.txt"
_ERROR = re.compile(r"^(?P<path>[^:\n]+):\d+(?::\d+)?: error: (?P<message>.*?)(?:\s+\[(?P<code>[a-z0-9-]+)\])?$")


def normalize(output: str) -> Counter:
    """``Counter`` of ``path|[code]|message`` keys from mypy's text output."""
    keys: Counter = Counter()
    for line in output.splitlines():
        match = _ERROR.match(line.strip())
        if not match:
            continue
        path = match.group("path").replace("\\", "/")
        # a line number inside the message ("already defined on line 5393") moves with every edit above it
        message = re.sub(r"\bon line \d+", "on line N", match.group("message"))
        keys[f"{path}|[{match.group('code') or ''}]|{message}"] += 1
    return keys


def read_baseline(text: str) -> Counter:
    keys: Counter = Counter()
    for raw in text.splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        count, _, key = raw.partition("\t")
        keys[key] += int(count)
    return keys


def write_baseline(keys: Counter) -> str:
    header = (
        "# mypy baseline: errors that existed when the type-check gate was introduced.\n"
        "# Format: count<TAB>path|[code]|message. It may only shrink (tools/mypy_gate.py).\n"
    )
    return header + "".join(f"{count}\t{key}\n" for key, count in sorted(keys.items()))


def compare(current: Counter, baseline: Counter) -> tuple[list[str], list[str]]:
    """``(new, stale)``: errors above the baseline, and baseline entries that are no longer produced."""
    new = [f"{current[k] - baseline.get(k, 0)}x {k}" for k in sorted(current) if current[k] > baseline.get(k, 0)]
    stale = [f"{baseline[k] - current.get(k, 0)}x {k}" for k in sorted(baseline)
             if baseline[k] > current.get(k, 0)]
    return new, stale


def run_mypy() -> str:
    done = subprocess.run(
        [sys.executable, "-m", "mypy", "--config-file", str(REPO / "mypy.ini")],
        capture_output=True, text=True, cwd=REPO, check=False,
    )
    if done.returncode not in (0, 1):
        raise SystemExit(f"mypy failed to run (exit {done.returncode}):\n{done.stdout}\n{done.stderr}")
    return done.stdout


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "--check"
    current = normalize(run_mypy())
    if mode == "--update":
        BASELINE.write_text(write_baseline(current), encoding="utf-8", newline="\n")
        print(f"wrote {BASELINE.relative_to(REPO)}: {sum(current.values())} errors")
        return 0
    new, stale = compare(current, read_baseline(BASELINE.read_text(encoding="utf-8")))
    for line in new:
        print(f"NEW type error: {line}")
    for line in stale:
        print(f"STALE baseline entry (fixed - run tools/mypy_gate.py --update): {line}")
    if new or stale:
        return 1
    print(f"type check clean against the baseline ({sum(current.values())} known errors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
