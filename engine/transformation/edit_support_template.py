"""Shared ``CobolEdit`` Java support-class template (numeric-edited PIC).

Emitted as-is by both the plain ``JavaGenerator`` and the
``SpringBootGenerator`` whenever generated method bodies reference
``CobolEdit`` (a COBOL program MOVEs a number into a numeric-edited item).

``CobolEdit.edit(value, srcScale, pic, blankWhenZero)`` reproduces the
GnuCOBOL 3.1.2 numeric-to-numeric-edited MOVE (libcob ``move.c``):

- the sender's digits are aligned on the decimal point; digits beyond the
  picture on either side are dropped (truncation, never rounding);
- ``9`` always shows its digit; ``Z`` / ``*`` show a space / asterisk for
  leading zeros; ``,`` ``B`` ``0`` ``/`` insert, and ``,`` / ``B`` inside a
  suppressed run take the suppression character;
- the first symbol of a floating ``$`` / ``+`` / ``-`` string is the symbol
  position, the others are digit positions; the symbol ends up immediately
  left of the first non-zero digit;
- a trailing ``+`` / ``-`` / ``CR`` / ``DB`` shows the sign; ``-`` and
  ``CR`` / ``DB`` show it only for a non-zero negative value, ``+`` shows
  ``+`` otherwise;
- an all-zero value under an all-suppressing picture is blank (``Z``) or
  asterisks except the decimal point (``*``); ``BLANK WHEN ZERO`` blanks it.

``pic`` is the picture with repeat counts expanded (``Z(5)`` -> ``ZZZZZ``).
The behaviour is pinned by ``tests/integration/test_numeric_edited_oracle.py``
(a seeded fuzz of pictures x values against the GnuCOBOL oracle).
"""

COBOL_EDIT_JAVA = '''final class CobolEdit {
    private CobolEdit() {}

    static String edit(java.math.BigDecimal value, int srcScale, String pic, boolean blankWhenZero) {
        boolean neg = value.signum() < 0;
        String digits = value.abs().setScale(srcScale, java.math.RoundingMode.DOWN)
            .unscaledValue().toString();
        int srcInt = digits.length() - srcScale;

        // Picture symbols (CR / DB are one symbol of width two).
        java.util.List<Character> syms = new java.util.ArrayList<>();
        for (int i = 0; i < pic.length(); i++) {
            char c = pic.charAt(i);
            if ((c == 'C' && i + 1 < pic.length() && pic.charAt(i + 1) == 'R')
                    || (c == 'D' && i + 1 < pic.length() && pic.charAt(i + 1) == 'B')) {
                syms.add(c);
                i++;
            } else {
                syms.add(c);
            }
        }

        // A lone leading $ / + / - is a fixed symbol (no digit position); a
        // run of two or more is a floating string.
        char fixedLead = 0;
        if (!syms.isEmpty()) {
            char first = syms.get(0);
            if (first == '$' || first == '+' || first == '-') {
                int run = 0;
                for (char c : syms) {
                    if (c == first) {
                        run++;
                    } else if (",B0/".indexOf(c) < 0) {
                        break;
                    }
                }
                if (run == 1) {
                    fixedLead = first;
                }
            }
        }

        // Digit places before the decimal point.
        int count = 0;
        boolean countSign = true;
        boolean countCurr = true;
        for (char c : syms) {
            if (c == '9' || c == 'Z' || c == '*') {
                count++;
                countSign = false;
                countCurr = false;
            } else if (countCurr && c == '$') {
                count++;
            } else if (countSign && (c == '+' || c == '-')) {
                count++;
            } else if (c == 'V' || c == '.') {
                break;
            }
        }
        int src = srcInt - count;

        StringBuilder out = new StringBuilder();
        char pad = ' ';
        boolean suppress = true;
        boolean isZero = true;
        boolean trailingSign = false;
        boolean trailingCurr = false;
        int decimalPoint = -1;
        int signFirst = 0;
        char signSymbol = 0;
        char currSymbol = 0;
        int end = -1; // exclusive end of the "body" once a trailing symbol is placed

        boolean first = true;
        for (char c : syms) {
            if (first && fixedLead != 0) {
                first = false;
                char x = digitAt(digits, src++);
                if (x != '0') {
                    isZero = false;
                    suppress = false;
                }
                out.append(fixedLead == '$' ? '$' : ' ');
                continue;
            }
            first = false;
            switch (c) {
                case '0':
                case '/':
                    out.append(c);
                    break;
                case 'B':
                    out.append(suppress ? pad : 'B');
                    break;
                case '9': {
                    char x = digitAt(digits, src++);
                    out.append(x);
                    if (x != '0') {
                        isZero = false;
                    }
                    suppress = false;
                    trailingSign = true;
                    trailingCurr = true;
                    break;
                }
                case 'V':
                    decimalPoint = out.length() - 1;
                    break;
                case '.':
                    out.append('.');
                    decimalPoint = out.length() - 1;
                    break;
                case ',':
                    out.append(suppress ? pad : ',');
                    break;
                case 'C':
                case 'D':
                    end = out.length();
                    if (neg && !isZero) {
                        out.append(c == 'C' ? "CR" : "DB");
                    } else {
                        out.append("  ");
                    }
                    break;
                case 'Z':
                case '*': {
                    char x = digitAt(digits, src++);
                    if (x != '0') {
                        isZero = false;
                        suppress = false;
                    }
                    pad = (c == '*') ? '*' : ' ';
                    out.append(suppress ? pad : x);
                    trailingSign = true;
                    trailingCurr = true;
                    break;
                }
                case '+':
                case '-': {
                    char x = digitAt(digits, src++);
                    if (x != '0') {
                        isZero = false;
                        suppress = false;
                    }
                    if (trailingSign) {
                        if (neg && !isZero) {
                            out.append('-');
                        } else if (c == '+') {
                            out.append('+');
                        } else {
                            out.append(' ');
                        }
                        end = out.length() - 1;
                    } else if (out.length() == 0 || suppress) {
                        out.append(pad);
                        signSymbol = c;
                        if (currSymbol == 0) {
                            signFirst++;
                        }
                    } else {
                        out.append(x);
                    }
                    break;
                }
                case '$': {
                    char x = digitAt(digits, src++);
                    if (x != '0') {
                        isZero = false;
                        suppress = false;
                    }
                    if (trailingCurr) {
                        out.append('$');
                        end = out.length() - 1;
                    } else if (out.length() == 0 || suppress) {
                        out.append(pad);
                        currSymbol = '$';
                    } else {
                        out.append(x);
                    }
                    break;
                }
                default:
                    out.append('?');
            }
        }
        char[] f = out.toString().toCharArray();
        int size = f.length;
        if (end < 0) {
            end = size;
        }

        if (suppress || (isZero && blankWhenZero)) {
            if (pad == ' ' || blankWhenZero) {
                java.util.Arrays.fill(f, ' ');
            } else {
                for (int i = 0; i < size; i++) {
                    if (f[i] != '.') {
                        f[i] = pad;
                    }
                }
            }
        } else {
            if (decimalPoint >= 0) {
                for (int i = decimalPoint + 1; i < end; i++) {
                    char ch = f[i];
                    if (!(ch >= '0' && ch <= '9') && ",+-/B".indexOf(ch) < 0) {
                        f[i] = '0';
                    }
                }
            }
            if (fixedLead == '+' || fixedLead == '-') {
                f[0] = (neg && !isZero) ? '-' : (fixedLead == '+' ? '+' : ' ');
            }
            if (signFirst > 0 || currSymbol != 0) {
                int dst = end - 1;
                while (dst > 0 && f[dst] != ' ') {
                    dst--;
                }
                if (signSymbol != 0 && currSymbol != 0) {
                    if (signFirst > 0) {
                        f[dst] = currSymbol;
                        if (dst - 1 >= 0) {
                            f[dst - 1] = (neg && !isZero) ? '-' : (signSymbol == '+' ? '+' : ' ');
                        }
                    } else {
                        f[dst] = (neg && !isZero) ? '-' : (signSymbol == '+' ? '+' : ' ');
                        if (dst - 1 >= 0) {
                            f[dst - 1] = currSymbol;
                        }
                    }
                } else if (signSymbol != 0) {
                    if (neg && !isZero) {
                        f[dst] = '-';
                    } else if (signSymbol == '+') {
                        f[dst] = '+';
                    } else {
                        f[dst] = ' ';
                    }
                } else {
                    f[dst] = currSymbol;
                }
            }
            int seen = 0;
            for (int i = 0; i < end; i++) {
                if (f[i] == 'B') {
                    f[i] = (seen == 0) ? pad : ' ';
                } else {
                    seen++;
                }
            }
        }
        return new String(f);
    }

    private static char digitAt(String digits, int index) {
        return (index >= 0 && index < digits.length()) ? digits.charAt(index) : '0';
    }
}
'''
