"""Shared ``CobolPacked`` Java support-class template: COMP-3 (packed decimal) and COMP (big-endian binary) record bytes.

Emitted by the plain and Spring Boot generators whenever generated bodies reference ``CobolPacked``. A record is a Java
``String`` of ISO-8859-1 characters, one character per byte (the file runtime reads and writes such files as
ISO-8859-1). Encodings, pinned by the GnuCOBOL 3.1.2 differential ``tests/integration/test_binary_record_oracle.py``:

* COMP-3: ``digits / 2 + 1`` bytes, two digits per byte, the last nibble is the sign: ``C`` positive, ``D`` negative,
  ``F`` for an unsigned field; a value that does not fit keeps its low-order digits (MOVE truncation is applied to the
  field before it is encoded);
* COMP: 1, 2, 4 or 8 bytes for 1-2, 3-4, 5-9 or 10-18 digits, big-endian, two's complement when signed;
* the implied decimal point (``V``) is not stored: the unscaled digits are.
"""

from __future__ import annotations

COBOL_PACKED_JAVA = '''final class CobolPacked {
    private CobolPacked() {}

    static int packedBytes(int digits) {
        return digits / 2 + 1;
    }

    static int binaryBytes(int digits) {
        return digits <= 2 ? 1 : digits <= 4 ? 2 : digits <= 9 ? 4 : 8;
    }

    static String packed(long v, int digits, boolean signed) {
        return packed(java.math.BigDecimal.valueOf(v), digits, 0, signed);
    }

    static String packed(java.math.BigDecimal v, int digits, int scale, boolean signed) {
        java.math.BigDecimal s = v.setScale(scale, java.math.RoundingMode.DOWN);
        boolean negative = s.signum() < 0;
        String d = s.abs().unscaledValue().toString();
        int nibbles = packedBytes(digits) * 2 - 1;
        if (d.length() > digits) {
            d = d.substring(d.length() - digits);
        }
        StringBuilder digitsText = new StringBuilder();
        for (int i = d.length(); i < nibbles; i++) {
            digitsText.append('0');
        }
        digitsText.append(d);
        int sign = signed ? (negative ? 0xD : 0xC) : 0xF;
        StringBuilder out = new StringBuilder();
        int bytes = packedBytes(digits);
        for (int i = 0; i < bytes; i++) {
            int hi = digitsText.charAt(2 * i) - '0';
            int lo = i == bytes - 1 ? sign : digitsText.charAt(2 * i + 1) - '0';
            out.append((char) ((hi << 4) | lo));
        }
        return out.toString();
    }

    static java.math.BigDecimal unpackDecimal(String s, int scale) {
        java.math.BigInteger n = java.math.BigInteger.ZERO;
        int last = s.length() - 1;
        for (int i = 0; i <= last; i++) {
            int b = s.charAt(i) & 0xFF;
            n = n.multiply(java.math.BigInteger.TEN).add(java.math.BigInteger.valueOf(b >> 4));
            if (i < last) {
                n = n.multiply(java.math.BigInteger.TEN).add(java.math.BigInteger.valueOf(b & 0x0F));
            }
        }
        int sign = s.isEmpty() ? 0xC : s.charAt(last) & 0x0F;
        if (sign == 0xD || sign == 0xB) {
            n = n.negate();
        }
        return new java.math.BigDecimal(n, scale);
    }

    static long unpackLong(String s) {
        return unpackDecimal(s, 0).longValue();
    }

    static String binary(long v, int digits, boolean signed) {
        int bytes = binaryBytes(digits);
        StringBuilder out = new StringBuilder();
        for (int i = bytes - 1; i >= 0; i--) {
            out.append((char) ((v >> (8 * i)) & 0xFF));
        }
        return out.toString();
    }

    static String binary(java.math.BigDecimal v, int digits, int scale, boolean signed) {
        return binary(v.setScale(scale, java.math.RoundingMode.DOWN).unscaledValue().longValue(), digits, signed);
    }

    static long unbinary(String s, boolean signed) {
        long v = 0;
        for (int i = 0; i < s.length(); i++) {
            v = (v << 8) | (s.charAt(i) & 0xFF);
        }
        int bits = s.length() * 8;
        if (signed && bits < 64 && (v & (1L << (bits - 1))) != 0) {
            v -= (1L << bits);
        }
        return v;
    }

    static java.math.BigDecimal unbinaryDecimal(String s, boolean signed, int scale) {
        return java.math.BigDecimal.valueOf(unbinary(s, signed), scale);
    }
}'''
