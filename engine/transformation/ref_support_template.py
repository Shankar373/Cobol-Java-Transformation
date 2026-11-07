"""Shared ``CobolRef`` Java support-class template: reference modification ``name(start:length)``.

Emitted by the plain and Spring Boot generators whenever generated bodies reference ``CobolRef``. A reference
modification names ``length`` characters of an alphanumeric item (or of the digits of an unsigned integer DISPLAY item)
from the 1-based position ``start``; a missing length means "to the end". Behaviour pinned by the GnuCOBOL 3.1.2
differential ``tests/integration/test_refmod_oracle.py``:

* as a MOVE sender the characters are moved like any alphanumeric value (padded or truncated on the right);
* as a MOVE receiver only those characters of the item change, the rest keeps its value;
* in a comparison the shorter operand is padded with spaces.

A reference outside the item (start < 1, length < 1, start + length - 1 > size) has no defined meaning in COBOL
(GnuCOBOL without runtime checks reads the adjacent storage); the generated Java throws ``IllegalStateException``
instead of inventing a value, so such a program fails loudly rather than printing something different.
"""

from __future__ import annotations

COBOL_REF_JAVA = '''final class CobolRef {
    private CobolRef() {}

    private static void check(String value, long start, long length) {
        if (start < 1 || length < 1 || start + length - 1 > value.length()) {
            throw new IllegalStateException("reference modification (" + start + ":" + length + ") outside an item of "
                + value.length() + " characters");
        }
    }

    /** value(start:length) */
    static String sub(String value, long start, long length) {
        check(value, start, length);
        return value.substring((int) start - 1, (int) (start - 1 + length));
    }

    /** value(start:) : to the end of the item */
    static String subRest(String value, long start) {
        check(value, start, 1);
        return value.substring((int) start - 1);
    }

    /** the characters of ``piece`` fitted to ``length`` (padded with spaces or truncated on the right) */
    static String fit(String piece, long length) {
        StringBuilder out = new StringBuilder(piece);
        while (out.length() < length) {
            out.append(' ');
        }
        return out.substring(0, (int) length);
    }

    /** FUNCTION UPPER-CASE / LOWER-CASE / REVERSE (same length as the argument) */
    static String upper(String value) {
        return value.toUpperCase(java.util.Locale.ROOT);
    }

    static String lower(String value) {
        return value.toLowerCase(java.util.Locale.ROOT);
    }

    static String reverse(String value) {
        return new StringBuilder(value).reverse().toString();
    }

    /** FUNCTION TRIM: spaces removed at the ``mode`` end(s); an all-space argument gives the empty string */
    static String trim(String value, String mode) {
        int from = 0;
        int to = value.length();
        if (!mode.equals("TRAILING")) {
            while (from < to && value.charAt(from) == ' ') {
                from++;
            }
        }
        if (!mode.equals("LEADING")) {
            while (to > from && value.charAt(to - 1) == ' ') {
                to--;
            }
        }
        return value.substring(from, to);
    }

    /** ``length`` copies of ``ch`` (a figurative constant moved to a reference-modified receiver) */
    static String fill(char ch, long length) {
        StringBuilder out = new StringBuilder();
        for (long i = 0; i < length; i++) {
            out.append(ch);
        }
        return out.toString();
    }

    /** ``ALL pattern`` repeated across ``length`` characters and cut at the last one */
    static String repeat(String pattern, long length) {
        StringBuilder out = new StringBuilder();
        while (out.length() < length) {
            out.append(pattern);
        }
        return out.substring(0, (int) length);
    }

    /** value with value(start:length) replaced by ``piece`` (already ``length`` characters) */
    static String put(String value, long start, long length, String piece) {
        check(value, start, length);
        return value.substring(0, (int) start - 1) + fit(piece, length) + value.substring((int) (start - 1 + length));
    }

    /** put through value(start:) */
    static String putRest(String value, long start, String piece) {
        check(value, start, 1);
        return put(value, start, value.length() - start + 1, piece);
    }

    /** alphanumeric relation: the shorter operand is padded with spaces, then compared in ASCII order */
    static int compare(String a, String b) {
        int width = Math.max(a.length(), b.length());
        return fit(a, width).compareTo(fit(b, width));
    }
}'''
