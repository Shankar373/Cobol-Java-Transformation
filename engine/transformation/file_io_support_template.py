"""Shared ``CobolFileIo`` Java support-class template.

Emitted as-is by both the plain ``JavaGenerator`` and the
``SpringBootGenerator`` whenever generated method bodies reference
``CobolFileIo`` (i.e. a COBOL program performs file I/O).

Design:
- Fully-qualified ``java.io``/``java.util`` names — no import block needed,
  so the class can be dropped next to any service/program source.
- Sequential files (``keyLen == 0``) emulate COBOL line-sequential
  semantics: ``WRITE`` emits ``record + newline``, ``READ`` returns one
  record per call, EOF is ``null`` (AT END).
- Indexed files (``keyLen > 0``) emulate a primary-key index with a
  deterministic side file ``<path>.idx`` (content is never compared by the
  verification harness; only STDOUT/EXIT_STATUS statuses are).  Records are
  keyed on the first ``keyLen`` bytes of the record area, matching the
  ``RECORD KEY IS`` field when it starts at offset 0.
- COBOL FILE STATUS semantics: each operation returns a 2-char status
  (``00`` ok, ``10`` AT END, ``22`` dup key, ``23`` not-found/not-open) that
  generated code assigns to the declared ``FILE STATUS IS`` field.
- State is keyed by path and intentionally survives ``close()`` so reopen
  sequences behave like a single COBOL run unit.
"""

from __future__ import annotations

COBOL_FILE_IO_JAVA = '''final class CobolFileIo {
    private static final java.util.Map<String, java.io.BufferedReader> IN = new java.util.HashMap<>();
    private static final java.util.Map<String, java.io.BufferedWriter> OUT = new java.util.HashMap<>();
    private static final java.util.Map<String, java.util.TreeMap<String, String>> IDX = new java.util.HashMap<>();
    private static final java.util.Map<String, java.util.TreeMap<Integer, String>> REL = new java.util.HashMap<>();
    private static final java.util.Map<String, String> CURSOR = new java.util.HashMap<>();
    private static final java.util.Map<String, Integer> KEYLEN = new java.util.HashMap<>();

    private CobolFileIo() {}

    /** OPEN file: mode INPUT/OUTPUT/I-O/EXTEND; keyLen 0 = sequential, keyLen < 0 = relative (RRN store). */
    static String open(String path, String mode, int keyLen) {
        try {
            if (keyLen < 0) {
                // RELATIVE organization: records keyed by 1-based RRN.
                if (mode.equalsIgnoreCase("OUTPUT")) {
                    REL.put(path, new java.util.TreeMap<>());
                    new java.io.File(path).delete();
                } else if (!REL.containsKey(path)) {
                    REL.put(path, new java.util.TreeMap<>());
                }
                return "00";
            }
            if (mode.equalsIgnoreCase("OUTPUT")) {
                if (keyLen > 0) {
                    IDX.put(path, new java.util.TreeMap<>());
                    KEYLEN.put(path, keyLen);
                    new java.io.File(path).delete();
                    new java.io.File(path + ".idx").delete();
                } else {
                    OUT.put(path, new java.io.BufferedWriter(new java.io.FileWriter(path, false)));
                }
                return "00";
            }
            if (mode.equalsIgnoreCase("INPUT")) {
                if (keyLen > 0) {
                    ensureIndex(path, keyLen);
                    return "00";
                }
                if (!new java.io.File(path).exists()) {
                    return "23";
                }
                IN.put(path, new java.io.BufferedReader(new java.io.FileReader(path)));
                return "00";
            }
            // I-O / EXTEND
            if (keyLen > 0) {
                ensureIndex(path, keyLen);
                return "00";
            }
            boolean append = mode.equalsIgnoreCase("EXTEND");
            OUT.put(path, new java.io.BufferedWriter(new java.io.FileWriter(path, append)));
            return "00";
        } catch (Exception e) {
            return "23";
        }
    }

    /** CLOSE file: flush state, persist the emulated index, release handles. */
    static String close(String path) {
        try {
            java.io.BufferedReader r = IN.remove(path);
            if (r != null) {
                r.close();
            }
            java.io.BufferedWriter w = OUT.remove(path);
            if (w != null) {
                w.close();
            }
            if (IDX.containsKey(path)) {
                persistIndex(path);
            }
            CURSOR.remove(path);
            return "00";
        } catch (Exception e) {
            return "23";
        }
    }

    /** WRITE record; keyLen 0 appends a line (sequential), else indexed insert.
     *  For relative files (opened with keyLen < 0), the third argument is the RRN. */
    static String write(String path, String rec, int keyLenOrRrn) {
        try {
            java.util.TreeMap<Integer, String> rel = REL.get(path);
            if (rel != null && !IDX.containsKey(path)) {
                rel.put(keyLenOrRrn, rec == null ? "" : rec);
                return "00";
            }
            int keyLen = keyLenOrRrn;
            if (keyLen > 0) {
                ensureIndex(path, keyLen);
                String key = keyOf(rec, keyLen);
                java.util.TreeMap<String, String> m = IDX.get(path);
                if (m.containsKey(key)) {
                    return "22";
                }
                m.put(key, dataOf(rec, keyLen));
                persistIndex(path);
                return "00";
            }
            java.io.BufferedWriter w = OUT.get(path);
            if (w == null) {
                return "23";
            }
            w.write(rec == null ? "" : rec);
            w.newLine();
            w.flush();
            return "00";
        } catch (Exception e) {
            return "23";
        }
    }

    /** READ next record (sequential line, or indexed cursor after START/READ KEY). */
    static String read(String path) {
        try {
            java.io.BufferedReader r = IN.get(path);
            if (r != null) {
                return r.readLine();
            }
            return readNextCursor(path);
        } catch (Exception e) {
            return null;
        }
    }

    /** Explicit READ ... NEXT — same sequential/cursor semantics as read(). */
    static String readNext(String path) {
        return read(path);
    }

    /** READ relative record at RRN; null = not found (INVALID KEY). */
    static String readRelative(String path, int rrn) {
        java.util.TreeMap<Integer, String> m = REL.get(path);
        if (m == null) {
            return null;
        }
        return m.get(rrn);
    }

    /** READ ... KEY IS key for indexed files; null = not found (INVALID KEY). */
    static String readKey(String path, String key) {
        java.util.TreeMap<String, String> m = IDX.get(path);
        if (m == null) {
            return null;
        }
        Integer klI = KEYLEN.get(path);
        int kl = klI == null ? (key == null ? 0 : key.length()) : klI;
        java.util.Map.Entry<String, String> e = m.floorEntry(key);
        if (e == null || !e.getKey().equals(key)) {
            return null;
        }
        CURSOR.put(path, e.getKey());
        return pad(e.getKey(), kl, false) + (e.getValue() == null ? "" : e.getValue());
    }

    /** START file KEY IS rel key; positions the cursor for indexed reads. */
    static String start(String path, String op, String key) {
        java.util.TreeMap<String, String> m = IDX.get(path);
        if (m == null || m.isEmpty()) {
            return "23";
        }
        String o = (op == null || op.isEmpty()) ? "=" : op;
        java.util.Map.Entry<String, String> e = null;
        if (o.equals("=")) {
            e = m.containsKey(key) ? new java.util.AbstractMap.SimpleEntry<>(key, m.get(key)) : null;
        } else if (o.equals(">=")) {
            e = m.ceilingEntry(key);
        } else if (o.equals(">")) {
            e = m.higherEntry(key);
        } else if (o.equals("<=")) {
            e = m.floorEntry(key);
        } else if (o.equals("<")) {
            e = m.lowerEntry(key);
        }
        if (e == null) {
            return "23";
        }
        // Position the cursor so the NEXT readNext returns e itself:
        // store the predecessor (or clear for the first key).
        java.util.Map.Entry<String, String> prev = m.lowerEntry(e.getKey());
        if (prev != null) {
            CURSOR.put(path, prev.getKey());
        } else {
            CURSOR.remove(path);
        }
        return "00";
    }

    /** REWRITE record (replace by key); "23" when the key is absent.
     *  Relative: third argument is RRN (file must be open in relative mode). */
    static String rewrite(String path, String rec, int keyLenOrRrn) {
        try {
            java.util.TreeMap<Integer, String> rel = REL.get(path);
            if (rel != null && !IDX.containsKey(path)) {
                if (!rel.containsKey(keyLenOrRrn)) {
                    return "23";
                }
                rel.put(keyLenOrRrn, rec == null ? "" : rec);
                return "00";
            }
            int keyLen = keyLenOrRrn;
            ensureIndex(path, keyLen);
            String key = keyOf(rec, keyLen);
            java.util.TreeMap<String, String> m = IDX.get(path);
            if (!m.containsKey(key)) {
                return "23";
            }
            m.put(key, dataOf(rec, keyLen));
            persistIndex(path);
            return "00";
        } catch (Exception e) {
            return "23";
        }
    }

    /** DELETE record by key; "23" when the key is absent.
     *  Relative overload: delete the record at RRN. */
    static String delete(String path, String key, int keyLen) {
        try {
            ensureIndex(path, keyLen);
            java.util.TreeMap<String, String> m = IDX.get(path);
            if (!m.containsKey(key)) {
                return "23";
            }
            m.remove(key);
            persistIndex(path);
            return "00";
        } catch (Exception e) {
            return "23";
        }
    }

    static String deleteRelative(String path, int rrn) {
        java.util.TreeMap<Integer, String> m = REL.get(path);
        if (m == null || !m.containsKey(rrn)) {
            return "23";
        }
        m.remove(rrn);
        return "00";
    }

    /** Pad/truncate a field to its display width (record display semantics). */
    static String pad(String s, int width, boolean numeric) {
        if (s == null) {
            s = "";
        }
        if (numeric) {
            while (s.length() < width) {
                s = "0" + s;
            }
            if (s.length() > width) {
                s = s.substring(s.length() - width);
            }
            return s;
        }
        while (s.length() < width) {
            s += " ";
        }
        if (s.length() > width) {
            s = s.substring(0, width);
        }
        return s;
    }

    private static void ensureIndex(String path, int keyLen) {
        if (IDX.containsKey(path)) {
            return;
        }
        java.util.TreeMap<String, String> m = new java.util.TreeMap<>();
        java.io.File f = new java.io.File(path + ".idx");
        if (f.exists()) {
            try (java.io.BufferedReader r = new java.io.BufferedReader(new java.io.FileReader(f))) {
                String first = r.readLine();
                if (first != null && first.startsWith("K")) {
                    try {
                        KEYLEN.put(path, Integer.parseInt(first.substring(1)));
                    } catch (NumberFormatException nfe) {
                        KEYLEN.put(path, keyLen);
                    }
                } else if (first != null) {
                    int sep = first.indexOf('\\u0001');
                    if (sep > 0) {
                        m.put(first.substring(0, sep), first.substring(sep + 1));
                    }
                }
                String l;
                while ((l = r.readLine()) != null) {
                    int sep = l.indexOf('\\u0001');
                    if (sep > 0) {
                        m.put(l.substring(0, sep), l.substring(sep + 1));
                    }
                }
            } catch (Exception e) {
                // best-effort load
            }
        }
        if (!KEYLEN.containsKey(path)) {
            KEYLEN.put(path, keyLen);
        }
        IDX.put(path, m);
    }

    private static void persistIndex(String path) throws Exception {
        java.util.TreeMap<String, String> m = IDX.get(path);
        int kl = KEYLEN.get(path) == null ? 0 : KEYLEN.get(path);
        try (java.io.BufferedWriter w = new java.io.BufferedWriter(new java.io.FileWriter(path + ".idx"))) {
            w.write("K" + kl);
            w.newLine();
            for (java.util.Map.Entry<String, String> e : m.entrySet()) {
                w.write(e.getKey());
                w.write('\\u0001');
                w.write(e.getValue());
                w.newLine();
            }
        }
    }

    private static String readNextCursor(String path) {
        java.util.TreeMap<String, String> m = IDX.get(path);
        if (m == null) {
            return null;
        }
        Integer klI = KEYLEN.get(path);
        int kl = klI == null ? 0 : klI;
        String cur = CURSOR.get(path);
        String foundKey = null;
        if (cur == null) {
            foundKey = m.isEmpty() ? null : m.firstKey();
        } else {
            java.util.Map.Entry<String, String> e = m.higherEntry(cur);
            if (e != null) {
                foundKey = e.getKey();
            }
        }
        if (foundKey == null) {
            return null;
        }
        CURSOR.put(path, foundKey);
        return pad(foundKey, kl, false) + (m.get(foundKey) == null ? "" : m.get(foundKey));
    }

    private static String keyOf(String rec, int keyLen) {
        if (rec == null) {
            return "";
        }
        return rec.length() >= keyLen ? rec.substring(0, keyLen) : pad(rec, keyLen, false);
    }

    private static String dataOf(String rec, int keyLen) {
        if (rec == null) {
            return "";
        }
        return rec.length() > keyLen ? rec.substring(keyLen) : "";
    }
}
'''