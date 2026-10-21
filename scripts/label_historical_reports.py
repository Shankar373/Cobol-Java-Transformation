#!/usr/bin/env python3
"""Label historical status reports per Master README §78/§76.6.

Historical reports stay **evidence of their own commit** and are never rewritten;
this script only inserts a one-line HISTORICAL banner directly under the H1 (or at
the top when there is no H1) so a reader cannot mistake them for current status.

Safety rules:
- Strict UTF-8 decode; a file that is not valid UTF-8 is skipped (reported), never
  re-encoded, so no content can be corrupted.
- Files already containing a HISTORICAL/Superseded banner are left untouched.
- Content is otherwise byte-identical apart from the inserted banner line.

Usage:
    python scripts/label_historical_reports.py --dry-run
    python scripts/label_historical_reports.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Paths (repo-relative) flagged as historical by the 2026-10-21 documentation audit.
TARGETS = [
    "docs/PHASE_6_7_FINAL_REPORT.md",
    "docs/PHASE2_COMPLETION_REPORT.md",
    "docs/PHASE3_COMPLETION_REPORT.md",
    "docs/PHASE4B_COMPLETION_REPORT.md",
    "docs/PHASE5A_COMPLETION_REPORT.md",
    "docs/PHASE5A1_COMPLETION_REPORT.md",
    "docs/PHASE5D_COMPLETION_REPORT.md",
    "docs/PHASE5D1_FINAL_FORENSIC_REVIEW.md",
    "docs/PHASE5E_COMPLETION_REPORT.md",
    "docs/PHASE5F1_COMPLETION_REPORT.md",
    "docs/PHASE5F2_COMPLETION_REPORT.md",
    "docs/PHASE5F2_FEATURE_MATRIX.md",
    "docs/PHASE5G_COMPLETION_REPORT.md",
    "docs/PHASE6A_UNIVERSAL_IR.md",
    "docs/PHASE7C_FINAL_EVIDENCE.md",
    "docs/PHASE7C_FORENSIC_CORRECTION.md",
    "PHASE7C_FINAL_EVIDENCE.md",
    "PHASE7C_FORENSIC_CORRECTION.md",
    "PHASE7D_COMPLETION_REPORT.md",
    "docs/RELEASE_GATE_WS4.md",
    "docs/CODE_AUDIT_REPORT.md",
    "docs/verification/CURRENT_CAPABILITY_VERIFICATION.md",
    "tests/verification/FINAL_REPORT.md",
    "tests/verification/results_fresh2/FINAL_REPORT.md",
]

MARKER_TOKENS = ("historical", "superseded", "dated snapshot")

BANNER = (
    "> **HISTORICAL REPORT (Master README §78, labeled 2026-10-21):** this document is "
    "evidence of the repository state at its own recorded commit/date only. It is not a "
    "current status claim — current status lives in `opencode.md`, `docs/BACKLOG.md` and "
    "the current capability/verification documents. Content is unchanged; only this label "
    "was added."
)


def already_labeled(text: str) -> bool:
    head = "\n".join(text.splitlines()[:14]).lower()
    return any(token in head for token in MARKER_TOKENS)


def insert_banner(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if lines and lines[0].lstrip().startswith("#"):
        # H1 line (with its trailing newline) then the banner, then the rest.
        head = lines[0]
        rest = "".join(lines[1:])
        sep = "" if head.endswith("\n") else "\n"
        return f"{head}{sep}> {BANNER}\n{rest}"
    return f"> {BANNER}\n\n{text}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    changed, skipped_missing, skipped_labeled, skipped_encoding = [], [], [], []
    for rel in TARGETS:
        path = REPO_ROOT / rel
        if not path.is_file():
            skipped_missing.append(rel)
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            skipped_encoding.append(rel)
            continue
        if already_labeled(text):
            skipped_labeled.append(rel)
            continue
        new_text = insert_banner(text)
        if not args.dry_run:
            path.write_bytes(new_text.encode("utf-8"))
        changed.append(rel)

    print(f"{'would label' if args.dry_run else 'labeled'}: {len(changed)}")
    for rel in changed:
        print(f"  + {rel}")
    if skipped_labeled:
        print(f"already labeled: {len(skipped_labeled)}")
    if skipped_missing:
        print(f"missing (not in this tree): {len(skipped_missing)}")
        for rel in skipped_missing:
            print(f"  - {rel}")
    if skipped_encoding:
        print(f"SKIPPED non-UTF8 (left byte-identical): {len(skipped_encoding)}")
        for rel in skipped_encoding:
            print(f"  ! {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
