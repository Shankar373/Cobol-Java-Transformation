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
  deterministic side file ``<path>.idx``.  Records are keyed on the first
  ``keyLen`` bytes of the record area, matching the ``RECORD KEY IS`` field
  when it starts at offset 0.
- Relative files (``keyLen < 0``) keep records by RRN and persist them to
  ``<path>.rel`` after every change; WRITE onto an occupied RRN is ``22``
  (GnuCOBOL 3.1.2).
- The verification pipeline compares both side files with the oracle's
  files by their records (``engine/comparators/indexed_records.py``).
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
    // ACCESS MODE SEQUENTIAL on indexed files: open mode, key of the last READ, last written key, end state
    private static final java.util.Map<String, String> MODE = new java.util.HashMap<>();
    // files whose records carry packed / binary bytes: read and written as ISO-8859-1 (one char per byte),
    // indexed record data persisted as hex
    private static final java.util.Set<String> BINARY = new java.util.HashSet<>();
    private static final java.util.Map<String, String> LASTKEY = new java.util.HashMap<>();
    private static final java.util.Map<String, String> LASTW = new java.util.HashMap<>();
    private static final java.util.Map<String, String> RSTAT = new java.util.HashMap<>();
    private static final java.util.Set<String> EOFS = new java.util.HashSet<>();

    private CobolFileIo() {}

    /**
     * File name resolution by DD name (pinned against the oracle runtime): a name
     * without a directory is looked up as DD_name, then dd_name, then name in the
     * environment; an absolute result is used as is, a relative one (or the plain
     * name) goes under COB_FILE_PATH when set, else the working directory.
     */
    static String map(String name) {
        if (name.indexOf('/') >= 0 || name.indexOf('\\\\') >= 0) {
            return name;
        }
        String value = System.getenv("DD_" + name);
        if (value == null) {
            value = System.getenv("dd_" + name);
        }
        if (value == null) {
            value = System.getenv(name);
        }
        String file = value != null ? value : name;
        if (file.startsWith("/")) {
            return file;
        }
        String base = System.getenv("COB_FILE_PATH");
        return (base != null && !base.isEmpty()) ? base + "/" + file : file;
    }

    static void setBinary(String path) {
        BINARY.add(map(path));
    }

    private static java.nio.charset.Charset charsetOf(String path) {
        return BINARY.contains(path) ? java.nio.charset.StandardCharsets.ISO_8859_1
                : java.nio.charset.Charset.defaultCharset();
    }

    private static java.io.BufferedWriter wr(String path, boolean append) throws Exception {
        return new java.io.BufferedWriter(new java.io.OutputStreamWriter(
            new java.io.FileOutputStream(path, append), charsetOf(path)));
    }

    private static java.io.BufferedReader rd(String path) throws Exception {
        return new java.io.BufferedReader(new java.io.InputStreamReader(
            new java.io.FileInputStream(path), charsetOf(path)));
    }

    private static String encodeValue(String path, String v) {
        if (!BINARY.contains(path)) {
            return v;
        }
        StringBuilder h = new StringBuilder();
        for (int i = 0; i < v.length(); i++) {
            h.append(String.format("%02x", (int) v.charAt(i) & 0xFF));
        }
        return h.toString();
    }

    private static String decodeValue(String path, String v) {
        if (!BINARY.contains(path)) {
            return v;
        }
        StringBuilder b = new StringBuilder();
        for (int i = 0; i + 1 < v.length(); i += 2) {
            b.append((char) Integer.parseInt(v.substring(i, i + 2), 16));
        }
        return b.toString();
    }

    /** OPEN file: mode INPUT/OUTPUT/I-O/EXTEND; keyLen 0 = sequential, keyLen < 0 = relative (RRN store). */
    static String open(String path, String mode, int keyLen) {
        path = map(path);
        MODE.put(path, mode.toUpperCase());
        LASTKEY.remove(path);
        LASTW.remove(path);
        RSTAT.remove(path);
        EOFS.remove(path);
        try {
            if (keyLen < 0) {
                // RELATIVE organization: records keyed by 1-based RRN.
                if (mode.equalsIgnoreCase("OUTPUT")) {
                    REL.put(path, new java.util.TreeMap<>());
                    new java.io.File(path).delete();
                    persistRelative(path);
                } else if (!REL.containsKey(path)) {
                    return "35";
                }
                return "00";
            }
            // INPUT / I-O / EXTEND of a file that does not exist: status 35
            // (file not found) for every organization.
            if (!mode.equalsIgnoreCase("OUTPUT")
                    && !(keyLen > 0 && IDX.containsKey(path))
                    && !new java.io.File(keyLen > 0 ? path + ".idx" : path).exists()) {
                return "35";
            }
            if (mode.equalsIgnoreCase("OUTPUT")) {
                if (keyLen > 0) {
                    IDX.put(path, new java.util.TreeMap<>());
                    KEYLEN.put(path, keyLen);
                    new java.io.File(path).delete();
                    new java.io.File(path + ".idx").delete();
                } else {
                    OUT.put(path, wr(path, false));
                }
                return "00";
            }
            if (mode.equalsIgnoreCase("INPUT")) {
                if (keyLen > 0) {
                    ensureIndex(path, keyLen);
                    return "00";
                }
                IN.put(path, rd(path));
                return "00";
            }
            // I-O / EXTEND
            if (keyLen > 0) {
                ensureIndex(path, keyLen);
                return "00";
            }
            boolean append = mode.equalsIgnoreCase("EXTEND");
            OUT.put(path, wr(path, append));
            return "00";
        } catch (Exception e) {
            return "23";
        }
    }

    /** CLOSE file: flush state, persist the emulated index, release handles. */
    static String close(String path) {
        path = map(path);
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
        path = map(path);
        try {
            java.util.TreeMap<Integer, String> rel = REL.get(path);
            if (rel != null && !IDX.containsKey(path)) {
                if (rel.containsKey(keyLenOrRrn)) {
                    return "22";
                }
                rel.put(keyLenOrRrn, rec == null ? "" : rec);
                persistRelative(path);
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
        path = map(path);
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

    /** WRITE to a record-sequential file: the fixed-length record area,
     *  no line terminator. */
    static String writeRecord(String path, String rec) {
        path = map(path);
        try {
            java.io.BufferedWriter w = OUT.get(path);
            if (w == null) {
                return "23";
            }
            w.write(rec);
            w.flush();
            return "00";
        } catch (Exception e) {
            return "23";
        }
    }

    /** READ the next fixed-length record of a record-sequential file;
     *  null at end of file. */
    static String readRecord(String path, int width) {
        path = map(path);
        try {
            java.io.BufferedReader r = IN.get(path);
            if (r == null) {
                return null;
            }
            char[] buf = new char[width];
            int n = 0;
            while (n < width) {
                int k = r.read(buf, n, width - n);
                if (k < 0) {
                    break;
                }
                n += k;
            }
            return n == 0 ? null : new String(buf, 0, n);
        } catch (Exception e) {
            return null;
        }
    }

    /** Explicit READ ... NEXT: same sequential/cursor semantics as read(). */
    static String readNext(String path) {
        path = map(path);
        return read(path);
    }

    /** READ relative record at RRN; null = not found (INVALID KEY). */
    static String readRelative(String path, int rrn) {
        path = map(path);
        java.util.TreeMap<Integer, String> m = REL.get(path);
        if (m == null) {
            return null;
        }
        return m.get(rrn);
    }

    /** READ ... KEY IS key for indexed files; null = not found (INVALID KEY). */
    static String readKey(String path, String key) {
        path = map(path);
        java.util.TreeMap<String, String> m = IDX.get(path);
        if (m == null) {
            return null;
        }
        Integer klI = KEYLEN.get(path);
        int kl = klI == null ? (key == null ? 0 : key.length()) : klI;
        java.util.Map.Entry<String, String> e = m.floorEntry(key);
        if (e == null || !e.getKey().equals(key)) {
            return null;  // a failed keyed READ leaves the position where it was
        }
        EOFS.remove(path);
        CURSOR.put(path, e.getKey());
        return pad(e.getKey(), kl, false) + (e.getValue() == null ? "" : e.getValue());
    }

    /** START file KEY IS rel key; positions the cursor for indexed reads. */
    static String start(String path, String op, String key) {
        path = map(path);
        java.util.TreeMap<String, String> m = IDX.get(path);
        if (m == null || m.isEmpty()) {
            EOFS.add(path);
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
            EOFS.add(path);
            return "23";
        }
        EOFS.remove(path);
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
        path = map(path);
        try {
            java.util.TreeMap<Integer, String> rel = REL.get(path);
            if (rel != null && !IDX.containsKey(path)) {
                if (!rel.containsKey(keyLenOrRrn)) {
                    return "23";
                }
                rel.put(keyLenOrRrn, rec == null ? "" : rec);
                persistRelative(path);
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
        path = map(path);
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
        path = map(path);
        java.util.TreeMap<Integer, String> m = REL.get(path);
        if (m == null || !m.containsKey(rrn)) {
            return "23";
        }
        m.remove(rrn);
        try {
            persistRelative(path);
        } catch (Exception e) {
            return "30";
        }
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
                        m.put(first.substring(0, sep), decodeValue(path, first.substring(sep + 1)));
                    }
                }
                String l;
                while ((l = r.readLine()) != null) {
                    int sep = l.indexOf('\\u0001');
                    if (sep > 0) {
                        m.put(l.substring(0, sep), decodeValue(path, l.substring(sep + 1)));
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
                w.write(encodeValue(path, e.getValue()));
                w.newLine();
            }
        }
    }

    /** The RELATIVE emulation image ``<path>.rel``: an ``R`` line, then one
     *  ``rrn U+0001 record`` line per live record in RRN order. */
    private static void persistRelative(String path) throws Exception {
        StringBuilder image = new StringBuilder("R\\n");
        for (java.util.Map.Entry<Integer, String> e : REL.get(path).entrySet()) {
            image.append(e.getKey()).append('\\u0001').append(e.getValue()).append('\\n');
        }
        java.nio.file.Files.write(
            java.nio.file.Paths.get(path + ".rel"),
            image.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
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

    /** READ (next) on an ACCESS MODE SEQUENTIAL indexed file; null with statusSeq() 10 (end), 46 (no next record), 47. */
    static String readNextSeq(String path) {
        path = map(path);
        String mode = MODE.get(path);
        if (!"INPUT".equals(mode) && !"I-O".equals(mode)) {
            RSTAT.put(path, "47");
            return null;
        }
        if (EOFS.contains(path)) {
            RSTAT.put(path, "46");
            return null;
        }
        String rec = readNextCursor(path);
        if (rec == null) {
            EOFS.add(path);
            RSTAT.put(path, "10");
            LASTKEY.remove(path);
            return null;
        }
        Integer klI = KEYLEN.get(path);
        LASTKEY.put(path, keyOf(rec, klI == null ? 0 : klI));
        RSTAT.put(path, "00");
        return rec;
    }

    /** Status of the last readNextSeq. */
    static String statusSeq(String path) {
        String s = RSTAT.get(map(path));
        return s == null ? "00" : s;
    }

    /** WRITE on an ACCESS MODE SEQUENTIAL indexed file: OUTPUT/EXTEND only, keys strictly ascending (21), 22 on a duplicate. */
    static String writeSeq(String path, String rec, int keyLen) {
        path = map(path);
        LASTKEY.remove(path);  // any WRITE, even a refused one, ends the "record last READ"
        String mode = MODE.get(path);
        if (!"OUTPUT".equals(mode) && !"EXTEND".equals(mode)) {
            return "48";
        }
        String key = keyOf(rec, keyLen);
        String last = LASTW.get(path);
        // OUTPUT: not above the last key written is out of order (21, also an equal key); EXTEND: only a lower key is
        // (an equal key is a duplicate of a record already there: 22)
        int order = last == null ? 1 : key.compareTo(last);
        if (order < 0 || (order == 0 && "OUTPUT".equals(mode))) {
            return "21";
        }
        LASTW.put(path, key);  // a key that passed the order check is the new "last", also when it is a duplicate (22)
        return write(path, rec, keyLen);
    }

    /** REWRITE the record last READ (43 without one, 49 in INPUT); a changed key moves the record, 22 if that key exists. */
    static String rewriteSeq(String path, String rec, int keyLen) {
        path = map(path);
        if ("INPUT".equals(MODE.get(path))) {
            return "49";
        }
        String lk = LASTKEY.get(path);
        if (lk == null) {
            return "43";
        }
        try {
            ensureIndex(path, keyLen);
            String key = keyOf(rec, keyLen);
            java.util.TreeMap<String, String> m = IDX.get(path);
            if (!key.equals(lk)) {
                if (m.containsKey(key)) {
                    // the reference behaviour removes the old record first and then fails to insert the new key (22): the record
                    // is gone and the "record last READ" ends
                    m.remove(lk);
                    persistIndex(path);
                    LASTKEY.remove(path);
                    return "22";
                }
                m.remove(lk);
            }
            m.put(key, dataOf(rec, keyLen));
            persistIndex(path);
            LASTKEY.remove(path);
            return "00";
        } catch (Exception e) {
            return "30";
        }
    }

    /** DELETE the record last READ (43 without one, 49 in INPUT). */
    static String deleteSeq(String path, int keyLen) {
        path = map(path);
        if ("INPUT".equals(MODE.get(path))) {
            return "49";
        }
        String lk = LASTKEY.get(path);
        if (lk == null) {
            return "43";
        }
        try {
            ensureIndex(path, keyLen);
            IDX.get(path).remove(lk);
            persistIndex(path);
            LASTKEY.remove(path);
            return "00";
        } catch (Exception e) {
            return "30";
        }
    }

    /** START on an ACCESS MODE SEQUENTIAL indexed file; a failed START leaves no next record (READ gives 46). */
    static String startSeq(String path, String op, String key) {
        path = map(path);
        String mode = MODE.get(path);
        if (!"INPUT".equals(mode) && !"I-O".equals(mode)) {
            return "47";
        }
        String st = start(path, op, key);
        LASTKEY.remove(path);
        if ("00".equals(st)) {
            EOFS.remove(path);
            RSTAT.remove(path);
        } else {
            EOFS.add(path);
        }
        return st;
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