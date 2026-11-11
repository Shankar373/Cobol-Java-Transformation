"""NEXT SENTENCE, lowered by a source rewrite before parsing.

``NEXT SENTENCE`` transfers control to the statement after the sentence's separator period.  Inside a
sentence that has no scope terminator (END-IF, END-EVALUATE, ...) nothing of the sentence follows the
construct that holds it except the other branches of that construct, which cannot run once this branch
was taken.  So when ``NEXT SENTENCE`` is the last statement of its branch (the next word is ELSE or
the period) it is exactly ``CONTINUE``.  Any other shape - an explicit scope terminator anywhere in the
sentence, statements after it in the branch, or the two words split across lines - is reported, never
guessed.  Only a sentence with at most one IF and none of EVALUATE, SEARCH, PERFORM or a file-phrase
is accepted: the parser mis-lowers CONTINUE inside nested IF ... ELSE ... ELSE and EVALUATE arms (found while
proving this rewrite), so those shapes stay refused instead of being routed through it.
"""

from __future__ import annotations

import re

_NEXT_SENTENCE = re.compile(r"(?<![\w-])NEXT\s+SENTENCE(?![\w-])", re.IGNORECASE)
_SCOPE_END = re.compile(r"(?<![\w-])END-[A-Z]+(?![\w-])", re.IGNORECASE)
_CONTAINER = re.compile(r"(?<![\w-])(?:EVALUATE|WHEN|SEARCH|PERFORM|AT|ON|INVALID)(?![\w-])", re.IGNORECASE)
_IF = re.compile(r"(?<![\w-])IF(?![\w-])", re.IGNORECASE)
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")


def _mask(text: str) -> str:
    return _QUOTED.sub(lambda m: " " * len(m.group(0)), text)


def _after_is_branch_end(masked: str, end: int) -> bool:
    rest = masked[end:].lstrip()
    return rest == "" or rest.startswith(".") or bool(re.match(r"ELSE(?![\w-])", rest, re.IGNORECASE))


def rewrite_next_sentence(lines: list[str]) -> tuple[list[str], list[str]]:
    """Replace each accepted NEXT SENTENCE by CONTINUE; return (lines, problems for the refused ones)."""
    start = next((i for i, l in enumerate(lines) if "PROCEDURE DIVISION" in l.upper()), None)
    if start is None or not _NEXT_SENTENCE.search(_mask(" ".join(l.strip() for l in lines[start:]))):
        return lines, []
    out = list(lines)
    problems: list[str] = []
    i = start + 1
    while i < len(out):
        j = i
        while j < len(out) - 1 and not _mask(out[j]).rstrip().endswith("."):
            j += 1
        block = out[i:j + 1]
        masked_lines = [_mask(l) for l in block]
        joined = " ".join(m.strip() for m in masked_lines)
        found = list(_NEXT_SENTENCE.finditer(joined))
        if found:
            why = ""
            if _SCOPE_END.search(joined):
                why = "the sentence has an explicit scope terminator, so the words after NEXT SENTENCE would run"
            elif _CONTAINER.search(joined) or len(_IF.findall(joined)) > 1:
                why = ("only a single IF ... ELSE sentence is certified (no nested IF, EVALUATE, SEARCH, PERFORM or "
                       "AT END / ON / INVALID KEY phrase)")
            elif any(not _after_is_branch_end(joined, m.end()) for m in found):
                why = "NEXT SENTENCE is followed by statements in its branch"
            elif sum(len(_NEXT_SENTENCE.findall(m)) for m in masked_lines) != len(found):
                why = "NEXT and SENTENCE are split across lines"
            if why:
                problems.append(f"NEXT SENTENCE is recognised but not lowered: {why}")
            else:
                for k, text in enumerate(block):
                    mk = masked_lines[k]
                    pieces, last = [], 0
                    for m in _NEXT_SENTENCE.finditer(mk):
                        pieces += [text[last:m.start()], "CONTINUE"]
                        last = m.end()
                    pieces.append(text[last:])
                    out[i + k] = "".join(pieces)
        i = j + 1
    return out, problems
