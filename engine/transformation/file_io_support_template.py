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
    // ALTERNATE RECORD KEY: per path the {offset, length, duplicates} of each alternate key (image offsets),
    // write sequence numbers (duplicates are ordered by them), the key of reference and the alternate cursor
    private static final java.util.Map<String, java.util.List<int[]>> ALTS = new java.util.HashMap<>();
    private static final java.util.Map<String, java.util.Map<String, long[]>> SEQN = new java.util.HashMap<>();
    // START places the cursor on the selected entry, unread: the next READ NEXT returns it (or, when it was deleted
    // meanwhile, the entry after its position). PENDOP holds the target's primary key, PENDKEY/PENDSEQ its place in
    // the alternate order
    private static final java.util.Map<String, String> PENDOP = new java.util.HashMap<>();
    private static final java.util.Map<String, String> PENDKEY = new java.util.HashMap<>();
    private static final java.util.Map<String, Long> PENDSEQ = new java.util.HashMap<>();
    private static final java.util.Map<String, Long> SEQC = new java.util.HashMap<>();
    private static final java.util.Map<String, Integer> REF = new java.util.HashMap<>();
    private static final java.util.Map<String, String> ACURK = new java.util.HashMap<>();
    private static final java.util.Map<String, Long> ACURS = new java.util.HashMap<>();
    private static final java.util.Map<String, java.util.Map<Integer, java.util.TreeMap<String, java.util.TreeMap<Long, String>>>> ACACHE
        = new java.util.HashMap<>();
    private static final java.util.Map<String, String> LASTKEY = new java.util.HashMap<>();
    private static final java.util.Map<String, String> LASTW = new java.util.HashMap<>();
    private static final java.util.Map<String, String> RSTAT = new java.util.HashMap<>();
    private static final java.util.Set<String> EOFS = new java.util.HashSet<>();
    // a failed START leaves the file with no position (READ NEXT answers 46) until a START or keyed READ succeeds;
    // unlike the end-of-file state (EOFS: a second consecutive READ NEXT answers 46) no keyed READ clears it
    private static final java.util.Set<String> NOPOS = new java.util.HashSet<>();

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

    /** Files with alternate keys keep each record's write sequence (16 hex digits) in front of its data. */
    private static String seqPrefix(String path, String key) {
        if (!ALTS.containsKey(path)) {
            return "";
        }
        java.util.Map<String, long[]> seqs = SEQN.get(path);
        long[] all = seqs == null ? null : seqs.get(key);
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < ALTS.get(path).size(); i++) {
            out.append(String.format("%016x", all == null || i >= all.length ? 0L : all[i]));
        }
        return out.toString();
    }

    private static void putLoaded(String path, java.util.TreeMap<String, String> m, String key, String raw) {
        int keys = ALTS.containsKey(path) ? ALTS.get(path).size() : 0;
        if (keys > 0 && raw.length() >= 16 * keys) {
            long[] all = new long[keys];
            for (int i = 0; i < keys; i++) {
                all[i] = Long.parseLong(raw.substring(16 * i, 16 * i + 16), 16);
                SEQC.merge(path, all[i], Math::max);
            }
            SEQN.computeIfAbsent(path, p -> new java.util.HashMap<>()).put(key, all);
            raw = raw.substring(16 * keys);
        }
        m.put(key, decodeValue(path, raw));
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
        NOPOS.remove(path);
        REF.remove(path);
        PENDOP.remove(path);
        PENDKEY.remove(path);
        for (int i = 1; i <= 3; i++) {
            PENDOP.remove(path + "#" + i);
            PENDKEY.remove(path + "#" + i);
            PENDSEQ.remove(path + "#" + i);
            ACURK.remove(path + "#" + i);
            ACURS.remove(path + "#" + i);
            EOFS.remove(path + "#" + i);
        }
        ACACHE.remove(path);
        if (mode.equalsIgnoreCase("OUTPUT")) {
            SEQN.remove(path);
            SEQC.remove(path);
        }
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
                    placeAtOpen(path);
                    return "00";
                }
                IN.put(path, rd(path));
                return "00";
            }
            // I-O / EXTEND
            if (keyLen > 0) {
                ensureIndex(path, keyLen);
                placeAtOpen(path);
                return "00";
            }
            boolean append = mode.equalsIgnoreCase("EXTEND");
            OUT.put(path, wr(path, append));
            return "00";
        } catch (Exception e) {
            return "23";
        }
    }

    /** OPEN INPUT / I-O of an indexed file that holds records puts the cursor on its first record, unread (as the
     *  oracle does): a record written afterwards below that key is never reached by READ NEXT, and when the record is
     *  deleted first the READ NEXT returns the one after it. An empty file has no position until the first READ NEXT. */
    private static void placeAtOpen(String path) {
        java.util.TreeMap<String, String> m = IDX.get(path);
        if (m != null && !m.isEmpty()) {
            PENDOP.put(path, m.firstKey());
            PENDKEY.put(path, m.firstKey());
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
                String altStatus = altCheckWrite(path, rec, key);
                if ("22".equals(altStatus)) {
                    return "22";
                }
                m.put(key, dataOf(rec, keyLen));
                altNoteWrite(path, key);
                persistIndex(path);
                return altStatus == null ? "00" : altStatus;
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
            // a failed keyed READ names its key as the key of reference; each key keeps its own cursor, and the
            // end-of-file condition survives it: after a READ NEXT reached the end (10) the next READ NEXT answers 46
            // (oracle-pinned, tests/integration/test_alternate_key_browse_oracle.py)
            boolean atEnd = endReachedOnAnyKey(path);
            // an alternate-key START still pending when a primary READ fails: the primary cursor goes back to its
            // current record, unread, so the next READ NEXT returns that record again (oracle-pinned)
            Integer along = REF.get(path);
            if (along != null && along > 0 && PENDOP.containsKey(path + "#" + along) && CURSOR.get(path) != null) {
                PENDOP.put(path, CURSOR.get(path));
                PENDKEY.put(path, CURSOR.get(path));
            }
            REF.remove(path);
            if (atEnd) {
                EOFS.add(path);
            }
            return null;
        }
        clearEof(path);
        NOPOS.remove(path);
        REF.remove(path);
        PENDOP.remove(path);
        PENDKEY.remove(path);
        // a successful primary READ consumes an alternate-key START that is still pending: the alternate cursor stays
        // on that entry, read, and a later READ NEXT along that key continues after it (oracle-pinned)
        for (int i = 1; i <= 3; i++) {
            String pendKey = PENDKEY.remove(path + "#" + i);
            Long pendSeq = PENDSEQ.remove(path + "#" + i);
            if (PENDOP.remove(path + "#" + i) != null && pendKey != null && pendSeq != null) {
                ACURK.put(path + "#" + i, pendKey);
                ACURS.put(path + "#" + i, pendSeq);
            }
        }
        CURSOR.put(path, e.getKey());
        return pad(e.getKey(), kl, false) + (e.getValue() == null ? "" : e.getValue());
    }

    /** START file KEY IS rel key; positions the cursor for indexed reads. */
    static String start(String path, String op, String key) {
        path = map(path);
        java.util.TreeMap<String, String> m = IDX.get(path);
        if (m == null || m.isEmpty()) {
            REF.remove(path);
            NOPOS.add(path);
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
            REF.remove(path);
            NOPOS.add(path);
            return "23";
        }
        clearEof(path);
        NOPOS.remove(path);
        REF.remove(path);
        // the cursor is on the selected record, unread
        PENDOP.put(path, e.getKey());
        PENDKEY.put(path, e.getKey());
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
            // a unique alternate key that another record already holds is refused (22) before a missing record (23)
            String altStatus = altCheckRewrite(path, rec, key);
            if ("22".equals(altStatus)) {
                return "22";
            }
            if (!m.containsKey(key)) {
                return "23";
            }
            altNoteRewrite(path, rec, key);
            m.put(key, dataOf(rec, keyLen));
            persistIndex(path);
            return altStatus == null ? "00" : altStatus;
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
            altNoteDelete(path, key);
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
                        putLoaded(path, m, first.substring(0, sep), first.substring(sep + 1));
                    }
                }
                String l;
                while ((l = r.readLine()) != null) {
                    int sep = l.indexOf('\\u0001');
                    if (sep > 0) {
                        putLoaded(path, m, l.substring(0, sep), l.substring(sep + 1));
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
                w.write(seqPrefix(path, e.getKey()) + encodeValue(path, e.getValue()));
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
        Integer ref = REF.get(path);
        if (ref != null && ref > 0) {
            return readNextAlt(path, ref);
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
        if (NOPOS.contains(path) || EOFS.contains(eofKey(path))) {
            RSTAT.put(path, "46");
            return null;
        }
        String rec;
        String pendKey = eofKey(path);
        String pendTarget = PENDOP.remove(pendKey);
        String pendValue = PENDKEY.remove(pendKey);
        Long pendSeq = PENDSEQ.remove(pendKey);
        if (pendTarget != null) {
            rec = resolvePending(path, pendTarget, pendValue, pendSeq);
        } else {
            rec = readNextCursor(path);
        }
        if (rec == null) {
            EOFS.add(eofKey(path));
            RSTAT.put(path, "10");
            LASTKEY.remove(path);
            return null;
        }
        Integer klI = KEYLEN.get(path);
        LASTKEY.put(path, keyOf(rec, klI == null ? 0 : klI));
        RSTAT.put(path, "00");
        Integer along = REF.get(path);
        if (along != null && along > 0) {
            consumePrimaryPending(path);  // reading along an alternate key, not START alone, consumes it
        }
        return rec;
    }

    /** True when a READ NEXT reached the end along any key: the condition holds for the file, not for one key. */
    private static boolean endReachedOnAnyKey(String path) {
        boolean atEnd = EOFS.contains(path);
        for (int i = 1; i <= 3 && !atEnd; i++) {
            atEnd = EOFS.contains(path + "#" + i);
        }
        return atEnd;
    }

    private static void clearEof(String path) {
        EOFS.remove(path);
        for (int i = 1; i <= 3; i++) {
            EOFS.remove(path + "#" + i);
        }
    }

    /** The end-of-file / no-position flag of the current key of reference (the primary key uses the path itself). */
    private static String eofKey(String path) {
        Integer ref = REF.get(path);
        return ref == null || ref == 0 ? path : path + "#" + ref;
    }

    /** The entry a START selected: returned when it still exists; when it was deleted meanwhile, the cursor stays at its
     *  place and the entry after it is returned (null at the end). */
    private static String resolvePending(String path, String target, String key, Long seq) {
        Integer ref = REF.get(path);
        java.util.TreeMap<String, String> m = IDX.get(path);
        if (ref != null && ref > 0) {
            String cursorKey = path + "#" + ref;
            int[] spec = ALTS.get(path).get(ref - 1);
            if (m != null && m.containsKey(target) && altValue(imageOf(path, target), spec).equals(key)) {
                // the record is still there with the value the START selected: it is the cursor entry. A record whose
                // alternate value was changed since (REWRITE) has left the entry, like a deleted one: the cursor stays
                // at its place and the READ NEXT continues after it (oracle-pinned)
                long[] all = SEQN.get(path) == null ? null : SEQN.get(path).get(target);
                ACURK.put(cursorKey, key);
                ACURS.put(cursorKey, all == null ? seq : all[ref - 1]);
                return imageOf(path, target);
            }
            ACURK.put(cursorKey, key);
            ACURS.put(cursorKey, seq);
            return readNextAlt(path, ref);
        }
        if (m != null && m.containsKey(target)) {
            CURSOR.put(path, target);
            return imageOf(path, target);
        }
        CURSOR.put(path, target);
        return readNextCursor(path);
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
            clearEof(path);
            NOPOS.remove(path);
            RSTAT.remove(path);
        } else {
            NOPOS.add(path);
        }
        return st;
    }

    /** Register alternate key ``ord`` (1-based): its offset and length in the stored (key-first) image. */
    static void altKey(String path, int ord, int offset, int length, boolean duplicates) {
        path = map(path);
        java.util.List<int[]> list = ALTS.computeIfAbsent(path, p -> new java.util.ArrayList<>());
        while (list.size() < ord) {
            list.add(null);
        }
        list.set(ord - 1, new int[] {offset, length, duplicates ? 1 : 0});
    }

    private static String imageOf(String path, String key) {
        Integer klI = KEYLEN.get(path);
        return pad(key, klI == null ? 0 : klI, false) + IDX.get(path).get(key);
    }

    private static String altValue(String image, int[] spec) {
        String v = image.length() >= spec[0] + spec[1] ? image.substring(spec[0], spec[0] + spec[1])
                : pad(image.length() > spec[0] ? image.substring(spec[0]) : "", spec[1], false);
        return v;
    }

    private static java.util.TreeMap<String, java.util.TreeMap<Long, String>> altIndex(String path, int ord) {
        java.util.Map<Integer, java.util.TreeMap<String, java.util.TreeMap<Long, String>>> perPath =
            ACACHE.computeIfAbsent(path, p -> new java.util.HashMap<>());
        java.util.TreeMap<String, java.util.TreeMap<Long, String>> ix = perPath.get(ord);
        if (ix != null) {
            return ix;
        }
        ix = new java.util.TreeMap<>();
        int[] spec = ALTS.get(path).get(ord - 1);
        java.util.Map<String, long[]> seqs = SEQN.computeIfAbsent(path, p -> new java.util.HashMap<>());
        int keys = ALTS.get(path).size();
        for (String pk : IDX.get(path).keySet()) {
            long[] all = seqs.get(pk);
            if (all == null) {
                all = new long[keys];
                for (int i = 0; i < keys; i++) {
                    all[i] = SEQC.merge(path, 1L, Long::sum);
                }
                seqs.put(pk, all);
            }
            long seq = all[ord - 1];
            ix.computeIfAbsent(altValue(imageOf(path, pk), spec), v -> new java.util.TreeMap<>()).put(seq, pk);
        }
        perPath.put(ord, ix);
        return ix;
    }

    /** null: no alternate key is in conflict; "02": a duplicate of a WITH DUPLICATES key; "22": a duplicate of a unique key. */
    private static String altCheckWrite(String path, String image, String key) {
        java.util.List<int[]> list = ALTS.get(path);
        if (list == null) {
            return null;
        }
        String status = null;
        for (int ord = 1; ord <= list.size(); ord++) {
            int[] spec = list.get(ord - 1);
            if (spec == null) {
                continue;
            }
            java.util.TreeMap<Long, String> same = altIndex(path, ord).get(altValue(image, spec));
            if (same != null && !same.isEmpty()) {
                if (spec[2] == 0) {
                    return "22";
                }
                status = "02";
            }
        }
        return status;
    }

    private static void altNoteWrite(String path, String key) {
        if (!ALTS.containsKey(path)) {
            return;
        }
        long[] all = new long[ALTS.get(path).size()];
        for (int i = 0; i < all.length; i++) {
            all[i] = SEQC.merge(path, 1L, Long::sum);
        }
        SEQN.computeIfAbsent(path, p -> new java.util.HashMap<>()).put(key, all);
        ACACHE.remove(path);
    }

    private static String altCheckRewrite(String path, String image, String key) {
        java.util.List<int[]> list = ALTS.get(path);
        if (list == null) {
            return null;
        }
        String old = IDX.get(path).containsKey(key) ? imageOf(path, key) : null;
        String status = null;
        for (int ord = 1; ord <= list.size(); ord++) {
            int[] spec = list.get(ord - 1);
            if (spec == null) {
                continue;
            }
            if (old != null && altValue(old, spec).equals(altValue(image, spec))) {
                continue;  // an unchanged alternate value is neither a duplicate nor a conflict
            }
            java.util.TreeMap<Long, String> same = altIndex(path, ord).get(altValue(image, spec));
            boolean other = false;
            if (same != null) {
                for (String pk : same.values()) {
                    if (!pk.equals(key)) {
                        other = true;
                    }
                }
            }
            if (other) {
                if (spec[2] == 0) {
                    return "22";
                }
                status = "02";
            }
        }
        return status;
    }

    /** A changed alternate value moves the record to the end of its new duplicate chain (a new write sequence). */
    private static void altNoteRewrite(String path, String image, String key) {
        java.util.List<int[]> list = ALTS.get(path);
        if (list == null) {
            return;
        }
        String old = imageOf(path, key);
        java.util.Map<String, long[]> seqs = SEQN.computeIfAbsent(path, p -> new java.util.HashMap<>());
        long[] all = seqs.get(key);
        if (all == null) {
            all = new long[list.size()];
            for (int i = 0; i < all.length; i++) {
                all[i] = SEQC.merge(path, 1L, Long::sum);
            }
            seqs.put(key, all);
        }
        for (int i = 0; i < list.size(); i++) {
            int[] spec = list.get(i);
            if (spec != null && !altValue(old, spec).equals(altValue(image, spec))) {
                all[i] = SEQC.merge(path, 1L, Long::sum);
            }
        }
        ACACHE.remove(path);
    }

    private static void altNoteDelete(String path, String key) {
        if (!ALTS.containsKey(path)) {
            return;
        }
        java.util.Map<String, long[]> seqs = SEQN.get(path);
        if (seqs != null) {
            seqs.remove(key);
        }
        ACACHE.remove(path);
    }

    /** READ ... KEY IS alternate key: the first record with that value; null (position kept) when there is none. */
    static String readAlt(String path, int ord, String key) {
        path = map(path);
        java.util.List<int[]> list = ALTS.get(path);
        if (list == null || IDX.get(path) == null || ord > list.size() || list.get(ord - 1) == null) {
            return null;
        }
        int[] spec = list.get(ord - 1);
        String k = pad(key, spec[1], false);
        java.util.TreeMap<Long, String> same = altIndex(path, ord).get(k);
        if (same == null || same.isEmpty()) {
            // the key of reference changes, the cursor of that key stays where it was; a failed alternate READ does
            // not clear the end-of-file condition, which holds for the file whatever the key: the next READ NEXT
            // answers 46 when an earlier READ NEXT reached the end (oracle-pinned)
            boolean atEnd = endReachedOnAnyKey(path);
            REF.put(path, ord);
            if (atEnd) {
                EOFS.add(eofKey(path));
            }
            // a failed alternate READ leaves the cursor where it was: an entry a START selected stays unread (its
            // pending mark is kept), an entry a READ already returned stays consumed, so READ NEXT continues after it
            return null;
        }
        java.util.Map.Entry<Long, String> first = same.firstEntry();
        REF.put(path, ord);
        consumePrimaryPending(path);
        PENDOP.remove(path + "#" + ord);
        PENDKEY.remove(path + "#" + ord);
        PENDSEQ.remove(path + "#" + ord);
        ACURK.put(path + "#" + ord, k);
        ACURS.put(path + "#" + ord, first.getKey());
        clearEof(path);
        NOPOS.remove(path);
        return imageOf(path, first.getValue());
    }

    /** Reading along an alternate key (a successful alternate READ, or a READ NEXT that returns a record) consumes the
     *  primary cursor's unread position (the first record at OPEN): a later READ NEXT along the primary key continues after it (oracle-pinned,
     *  tests/integration/test_alternate_key_browse_oracle.py). */
    private static void consumePrimaryPending(String path) {
        String primaryPending = PENDOP.remove(path);
        PENDKEY.remove(path);
        if (primaryPending != null) {
            CURSOR.put(path, primaryPending);
        }
    }

    private static String readNextAlt(String path, int ord) {
        java.util.TreeMap<String, java.util.TreeMap<Long, String>> ix = altIndex(path, ord);
        String ck = ACURK.get(path + "#" + ord);
        Long cs = ACURS.get(path + "#" + ord);
        String nk = null;
        Long ns = null;
        String pk = null;
        if (ck != null) {
            java.util.TreeMap<Long, String> same = ix.get(ck);
            java.util.Map.Entry<Long, String> e = same == null ? null : same.higherEntry(cs == null ? -1L : cs);
            if (e != null) {
                nk = ck;
                ns = e.getKey();
                pk = e.getValue();
            }
        }
        if (pk == null) {
            java.util.Map.Entry<String, java.util.TreeMap<Long, String>> g = ck == null ? ix.firstEntry() : ix.higherEntry(ck);
            if (g != null && !g.getValue().isEmpty()) {
                nk = g.getKey();
                ns = g.getValue().firstKey();
                pk = g.getValue().firstEntry().getValue();
            }
        }
        if (pk == null) {
            return null;
        }
        ACURK.put(path + "#" + ord, nk);
        ACURS.put(path + "#" + ord, ns);
        return imageOf(path, pk);
    }

    /** START ... KEY IS = | > | >= alternate key; the next READ NEXT returns the first record at or after it. */
    static String startAlt(String path, int ord, String op, String key) {
        path = map(path);
        java.util.List<int[]> list = ALTS.get(path);
        if (list == null || IDX.get(path) == null || ord > list.size() || list.get(ord - 1) == null) {
            return "23";
        }
        int[] spec = list.get(ord - 1);
        String k = pad(key, spec[1], false);
        java.util.TreeMap<String, java.util.TreeMap<Long, String>> ix = altIndex(path, ord);
        String o = (op == null || op.isEmpty()) ? "=" : op;
        java.util.Map.Entry<String, java.util.TreeMap<Long, String>> e;
        if (o.equals("=")) {
            e = ix.containsKey(k) ? ix.ceilingEntry(k) : null;
        } else if (o.equals(">=")) {
            e = ix.ceilingEntry(k);
        } else if (o.equals(">")) {
            e = ix.higherEntry(k);
        } else {
            e = null;
        }
        if (e == null || e.getValue().isEmpty()) {
            REF.put(path, ord);
            NOPOS.add(path);
            return "23";
        }
        clearEof(path);
        NOPOS.remove(path);
        REF.put(path, ord);
        PENDOP.put(path + "#" + ord, e.getValue().firstEntry().getValue());
        PENDKEY.put(path + "#" + ord, e.getKey());
        PENDSEQ.put(path + "#" + ord, e.getValue().firstKey());
        return "00";
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