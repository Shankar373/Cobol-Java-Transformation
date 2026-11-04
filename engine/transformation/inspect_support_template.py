"""Shared ``CobolInspect`` Java support-class template.

Emitted by the plain and Spring Boot generators whenever generated method bodies reference
``CobolInspect`` (a COBOL program performs a certified ``INSPECT``).

The scan mirrors the way the oracle runtime evaluates the statement, which differs from a
naive left-to-right, all-phrases-at-once scan: phrases are applied one after the other in
source order, each over its own BEFORE/AFTER area, and a position consumed by an earlier
phrase is *marked* and can no longer match a later one.  ``LEADING`` stops at the first
position that does not match; ``FIRST`` acts once.  Replacements are applied at the end, so a
replacement never produces a new match.  The semantics are pinned by the GnuCOBOL oracle
differential in ``tests/integration/test_inspect_oracle.py``.

Phrase encoding (``String...`` varargs, six strings per phrase): kind, pattern,
replacement, bound order (``""``, ``"A"``, ``"B"``, ``"AB"``, ``"BA"``), AFTER literal,
BEFORE literal.  Kinds: ``CHARACTERS``, ``ALL``, ``LEADING``, ``FIRST``, ``CONVERTING``.
"""

from __future__ import annotations

COBOL_INSPECT_JAVA = '''final class CobolInspect {
    private CobolInspect() {}

    private static int indexOf(char[] data, int from, int to, String needle) {
        int n = needle.length();
        for (int p = from; p <= to - n; p++) {
            int k = 0;
            while (k < n && data[p + k] == needle.charAt(k)) {
                k++;
            }
            if (k == n) {
                return p;
            }
        }
        return -1;
    }

    private static boolean matches(char[] data, int at, String needle) {
        for (int k = 0; k < needle.length(); k++) {
            if (data[at + k] != needle.charAt(k)) {
                return false;
            }
        }
        return true;
    }

    /** Apply the phrases; returns the occurrence count (TALLYING) and rewrites {@code data} in place. */
    private static long run(char[] data, boolean tally, String[] p) {
        int size = data.length;
        char[] out = data.clone();
        boolean[] marked = new boolean[size];
        long count = 0;
        for (int q = 0; q + 5 < p.length; q += 6) {
            String kind = p[q];
            String pattern = p[q + 1];
            String repl = p[q + 2];
            int start = 0;
            int end = size;
            for (int b = 0; b < p[q + 3].length(); b++) {
                if (p[q + 3].charAt(b) == 'A') {
                    int hit = indexOf(data, start, end, p[q + 4]);
                    start = hit < 0 ? end : hit + p[q + 4].length();
                } else {
                    int hit = indexOf(data, start, end, p[q + 5]);
                    if (hit >= 0) {
                        end = hit;
                    }
                }
            }
            if (kind.equals("CONVERTING")) {
                for (int i = start; i < end; i++) {
                    int j = pattern.indexOf(data[i]);
                    if (j >= 0) {
                        out[i] = repl.charAt(j);
                    }
                }
                continue;
            }
            if (kind.equals("CHARACTERS")) {
                for (int i = start; i < end; i++) {
                    if (!marked[i]) {
                        marked[i] = true;
                        count++;
                        if (!tally) {
                            out[i] = repl.charAt(0);
                        }
                    }
                }
                continue;
            }
            int n = pattern.length();
            for (int i = start; i + n <= end; i++) {
                boolean hit = matches(data, i, pattern);
                for (int k = 0; hit && k < n; k++) {
                    if (marked[i + k]) {
                        hit = false;
                    }
                }
                if (!hit) {
                    if (kind.equals("LEADING")) {
                        break;
                    }
                    continue;
                }
                for (int k = 0; k < n; k++) {
                    marked[i + k] = true;
                    if (!tally) {
                        out[i + k] = repl.charAt(k);
                    }
                }
                count++;
                i += n - 1;
                if (kind.equals("FIRST")) {
                    break;
                }
            }
        }
        System.arraycopy(out, 0, data, 0, size);
        return count;
    }

    /** INSPECT ... REPLACING / CONVERTING: the new contents of the field. */
    static String rewrite(String field, String... phrases) {
        char[] data = field.toCharArray();
        run(data, false, phrases);
        return new String(data);
    }

    /** INSPECT ... TALLYING: the counter after adding the occurrences, kept to {@code digits} digits. */
    static long tally(String field, long counter, int digits, String... phrases) {
        long total = counter + run(field.toCharArray(), true, phrases);
        long modulus = 1;
        for (int i = 0; i < digits; i++) {
            modulus *= 10;
        }
        return total % modulus;
    }
}
'''
