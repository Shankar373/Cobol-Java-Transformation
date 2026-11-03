#!/usr/bin/env python3
"""Validate the Phase 0 closure metadata table in docs/BACKLOG.md.

Every row must have exactly 7 columns and a unique BL-### id.
Exits non-zero on any structural problem so CI/scripts can gate on it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKLOG = Path(__file__).resolve().parent.parent / "docs" / "BACKLOG.md"
ROW_RE = re.compile(r"^\|\s*(BL-\d+)\s*\|")


def main() -> int:
    if not BACKLOG.is_file():
        print(f"ERROR: {BACKLOG} not found", file=sys.stderr)
        return 1

    lines = BACKLOG.read_text(encoding="utf-8").splitlines()
    in_register = False
    rows: list[tuple[int, str, int]] = []
    seen: dict[str, int] = {}
    errors: list[str] = []

    for lineno, line in enumerate(lines, 1):
        if line.startswith("## Phase 0 closure metadata"):
            in_register = True
            continue
        if in_register and line.startswith("## "):
            break
        if not in_register:
            continue
        if not line.startswith("|"):
            continue
        if line.startswith("|---") or line.startswith("| ---"):
            continue
        # header row
        if re.match(r"^\|\s*ID\s*\|", line, re.IGNORECASE):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # markdown tables escape pipes as \|
        # re-split respecting escaped pipes
        raw = line.strip().strip("|")
        parts = re.split(r"(?<!\\)\|", raw)
        cells = [p.strip() for p in parts]
        if len(cells) != 7:
            errors.append(f"line {lineno}: expected 7 columns, got {len(cells)}")
            continue
        m = ROW_RE.match(line)
        if not m:
            errors.append(f"line {lineno}: first cell is not a BL-### id: {cells[0]!r}")
            continue
        bl_id = m.group(1)
        if bl_id in seen:
            errors.append(
                f"line {lineno}: duplicate id {bl_id} (first at line {seen[bl_id]})"
            )
        seen[bl_id] = lineno
        rows.append((lineno, bl_id, len(cells)))

    if not rows:
        print("ERROR: no register rows found", file=sys.stderr)
        return 1

    print(f"OK: {len(rows)} register rows, all 7 columns, unique ids")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
