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
  - ``number(line, width)`` / ``decimal(line, i, s)`` — unsigned
    PIC 9(n) / PIC 9(i)V9(s): ``digits`` reproduces GnuCOBOL's
    alphanumeric-to-numeric-display move (libcob ``move.c``) on the first
    i+s bytes: leading spaces and one sign skipped, integer digits
    right-aligned (excess high-order digits dropped), spaces and ``,``
    ignored, one ``.`` starts the decimals, and a bad character or second
    ``.`` met before the field is full zeroes the whole field.  The
    earlier rule (strip spaces, one sign, digits only) disagreed with the
    oracle on inputs such as ``1.5``, ``1,2`` and ``+12+``.
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
     * ACCEPT into unsigned PIC 9(n): the digits of {@link #digits} as a
     * long (n <= 18).
     */
    static long number(String line, int width) {
        return Long.parseLong(digits(line, width, 0));
    }

    /**
     * ACCEPT into unsigned PIC 9(i)V9(s): the digits of {@link #digits}
     * at scale s.
     */
    static java.math.BigDecimal decimal(String line, int intDigits, int scale) {
        return new java.math.BigDecimal(
            new java.math.BigInteger(digits(line, intDigits, scale)), scale);
    }

    /**
     * GnuCOBOL 3.1.2's alphanumeric-to-numeric-display move of an ACCEPTed
     * line into unsigned PIC 9(i)V9(s), as i+s digit characters.
     *
     * Only the first i+s bytes of the line are read. Leading white space
     * and one leading sign are skipped. Integer digits are right-aligned;
     * excess high-order digits are dropped (with any non-digits between
     * them). Digits then fill the field left to right: white space and
     * ',' are ignored, the first '.' starts the decimals. A second '.' or
     * any other character met before the field is full makes the whole
     * field zero; once it is full the rest of the line is ignored.
     */
    static String digits(String line, int intDigits, int scale) {
        byte[] src = line.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        int size = intDigits + scale;
        int end = Math.min(src.length, size);
        char[] dst = new char[size];
        java.util.Arrays.fill(dst, '0');
        int s1 = 0;
        while (s1 < end && isSpace(src[s1])) {
            s1++;
        }
        if (s1 < end && (src[s1] == '+' || src[s1] == '-')) {
            s1++;
        }
        int count = 0;
        for (int p = s1; p < end && src[p] != '.'; p++) {
            if (isDigit(src[p])) {
                count++;
            }
        }
        int s2 = 0;
        if (count < intDigits) {
            s2 = intDigits - count;
        } else {
            while (count-- > intDigits) {
                while (!isDigit(src[s1++])) {
                    // skip to and past the next dropped high-order digit
                }
            }
        }
        int points = 0;
        for (; s1 < end && s2 < size; s1++) {
            byte c = src[s1];
            if (isDigit(c)) {
                dst[s2++] = (char) c;
            } else if (c == '.') {
                if (points++ > 0) {
                    return "0".repeat(size);
                }
            } else if (!(isSpace(c) || c == ',')) {
                return "0".repeat(size);
            }
        }
        return new String(dst);
    }

    private static boolean isDigit(byte c) {
        return c >= '0' && c <= '9';
    }

    /** C isspace in the "C" locale. */
    private static boolean isSpace(byte c) {
        return c == ' ' || (c >= 9 && c <= 13);
    }
}
'''
