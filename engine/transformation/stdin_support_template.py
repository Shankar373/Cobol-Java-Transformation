"""Shared ``CobolStdin`` Java support-class template.

Emitted as-is by both the plain ``JavaGenerator`` and the
``SpringBootGenerator`` whenever generated method bodies reference
``CobolStdin`` (i.e. a COBOL program performs ``ACCEPT``).

Design:
- Fully-qualified ``java.io`` names — no import block needed, so the
  class can be dropped next to any service/program source.
- ONE shared ``BufferedReader`` over ``System.in`` for the whole program:
  a per-statement ``Scanner`` buffers stdin ahead and breaks the second
  ``ACCEPT`` (the original lowering shipped that bug).  ``ACCEPT``
  consumes one whole line per statement, sequentially, exactly like
  GnuCOBOL.
- EOF is an empty line, not an error: GnuCOBOL pads an alphanumeric
  target with spaces and zeroes a numeric target at end of input.
- Semantics are pinned by the GnuCOBOL 3.1.2 oracle probe matrix in
  ``tests/integration/test_accept_oracle_proof.py``:
  - ``alnum(line, width)`` — PIC X(n): first n characters, right-padded
    with spaces when the line is shorter.
  - ``number(line, width)`` — unsigned PIC 9(n): the first n bytes of
    the line have their spaces removed; one leading or trailing sign is
    tolerated (ignored for PIC 9); every remaining character must be a
    digit; anything else yields zero.
"""

from __future__ import annotations

COBOL_STDIN_JAVA = '''final class CobolStdin {
    private static final java.io.BufferedReader IN =
        new java.io.BufferedReader(new java.io.InputStreamReader(System.in));

    private CobolStdin() {}

    /** One whole standard-input line; EOF (or I/O error) is an empty line. */
    static String readLine() {
        try {
            String line = IN.readLine();
            return line == null ? "" : line;
        } catch (java.io.IOException e) {
            throw new RuntimeException(e);
        }
    }

    /** ACCEPT into PIC X(n): the first n characters, space-padded. */
    static String alnum(String line, int width) {
        if (line.length() >= width) {
            return line.substring(0, width);
        }
        StringBuilder sb = new StringBuilder(line);
        while (sb.length() < width) {
            sb.append(' ');
        }
        return sb.toString();
    }

    /**
     * ACCEPT into unsigned PIC 9(n): GnuCOBOL's alphanumeric-to-numeric
     * move on the first n bytes - spaces are removed, one leading or
     * trailing sign is tolerated (ignored for PIC 9), every remaining
     * character must be a digit, anything else yields zero.
     */
    static long number(String line, int width) {
        String digits = line.length() > width ? line.substring(0, width) : line;
        digits = digits.replace(" ", "");
        if (digits.isEmpty()) {
            return 0L;
        }
        int lo = 0;
        int hi = digits.length();
        char first = digits.charAt(0);
        if (first == '+' || first == '-') {
            lo = 1;
        } else {
            char last = digits.charAt(hi - 1);
            if (last == '+' || last == '-') {
                hi = hi - 1;
            }
        }
        if (lo >= hi) {
            return 0L;
        }
        for (int i = lo; i < hi; i++) {
            char c = digits.charAt(i);
            if (c < '0' || c > '9') {
                return 0L;
            }
        }
        return Long.parseLong(digits.substring(lo, hi));
    }
}
'''
