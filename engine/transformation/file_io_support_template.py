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

    private CobolFileIo() {}

    /** OPEN file: mode INPUT/OUTPUT/I-O/EXTEND; keyLen 0 = sequential, keyLen < 0 = relative (RRN store). */
    static String open(String path, String mode, int keyLen) {
        try {
            if (keyLen < 0) {
                // RELATIVE organization: records keyed by 1-based RRN.
                if (!mode.equalsIgnoreCase("INPUT") && REL.get(path) instanceof DiskRel) {
                    REL.remove(path);
                }
                if (mode.equalsIgnoreCase("OUTPUT")) {
                    REL.put(path, new java.util.TreeMap<>());
                    new java.io.File(path).delete();
                    persistRelative(path);
                } else if (!REL.containsKey(path) && !loadRelative(path, mode.equalsIgnoreCase("INPUT"))) {
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
                    OUT.put(path, new java.io.BufferedWriter(new java.io.FileWriter(path, false)));
                }
                return "00";
            }
            if (mode.equalsIgnoreCase("INPUT")) {
                if (keyLen > 0) {
                    READ_ONLY.add(path);
                    ensureIndex(path, keyLen);
                    return "00";
                }
                IN.put(path, new java.io.BufferedReader(new java.io.FileReader(path)));
                return "00";
            }
            // I-O / EXTEND
            if (keyLen > 0) {
                READ_ONLY.remove(path);
                if (IDX.get(path) instanceof DiskIndex) {
                    IDX.remove(path);
                }
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
            if (IDX.containsKey(path) && !(IDX.get(path) instanceof DiskIndex)) {
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
        if (READ_ONLY.contains(path) && f.exists() && f.length() >= diskThreshold()) {
            try {
                DiskIndex disk = new DiskIndex(f);
                KEYLEN.put(path, disk.headerKeyLen() > 0 ? disk.headerKeyLen() : keyLen);
                IDX.put(path, disk);
                return;
            } catch (Exception e) {
                // fall back to the in-memory load below
            }
        }
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

    private static final int DISK_STRIDE = 256;
    private static final java.util.Set<String> READ_ONLY = new java.util.HashSet<>();

    /** Files at least this large are opened INPUT through a disk-backed index
     *  (memory proportional to size / DISK_STRIDE). Smaller files, and every
     *  file opened for update, use the in-memory map. */
    private static long diskThreshold() {
        return Long.getLong("cobolio.diskIndexBytes", 32L * 1024 * 1024);
    }

    /** A sorted line image (``key U+0001 data``) addressed through a sparse
     *  in-memory index: every DISK_STRIDE-th line's key and byte offset.  A
     *  lookup seeks to a block and scans at most that block, and a sequential
     *  scan continues from the previous position, so memory does not grow
     *  with the number of records. */
    static final class SparseLines {
        static final int FLOOR = 0;
        static final int LOWER = 1;
        static final int CEIL = 2;
        static final int HIGHER = 3;
        private final java.io.File file;
        private final java.util.Comparator<String> order;
        private final java.util.ArrayList<String> blockKeys = new java.util.ArrayList<>();
        private final java.util.ArrayList<Long> blockOffsets = new java.util.ArrayList<>();
        long count;
        int headerKeyLen = -1;
        String firstKey;
        private java.io.BufferedInputStream stream;
        private long streamPos = -1;
        private String lastKey;
        private long lastEnd = -1;

        SparseLines(java.io.File file, java.util.Comparator<String> order) throws java.io.IOException {
            this.file = file;
            this.order = order;
            try (java.io.BufferedInputStream in = new java.io.BufferedInputStream(
                    new java.io.FileInputStream(file), 1 << 16)) {
                long[] used = new long[1];
                long start = 0;
                String previous = null;
                String line;
                while ((line = readLine(in, used)) != null) {
                    long lineStart = start;
                    start += used[0];
                    used[0] = 0;
                    int sep = line.indexOf('\\u0001');
                    if (lineStart == 0 && sep < 0) {
                        if (line.startsWith("K")) {
                            try {
                                headerKeyLen = Integer.parseInt(line.substring(1));
                            } catch (NumberFormatException nfe) {
                                headerKeyLen = -1;
                            }
                        }
                        continue;
                    }
                    if (sep <= 0) {
                        continue;
                    }
                    String key = line.substring(0, sep);
                    if (previous != null && order.compare(previous, key) >= 0) {
                        throw new java.io.IOException("image is not sorted");
                    }
                    previous = key;
                    if (count % DISK_STRIDE == 0) {
                        blockKeys.add(key);
                        blockOffsets.add(lineStart);
                    }
                    if (count == 0) {
                        firstKey = key;
                    }
                    count++;
                }
            }
        }

        private static String readLine(java.io.InputStream in, long[] used) throws java.io.IOException {
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream(128);
            int b;
            boolean any = false;
            while ((b = in.read()) >= 0) {
                any = true;
                used[0]++;
                if (b == '\\n') {
                    break;
                }
                bytes.write(b);
            }
            if (!any) {
                return null;
            }
            byte[] raw = bytes.toByteArray();
            int n = raw.length;
            if (n > 0 && raw[n - 1] == '\\r') {
                n--;
            }
            return new String(raw, 0, n, java.nio.charset.StandardCharsets.UTF_8);
        }

        private int blockFor(String key, boolean strict) {
            int lo = 0;
            int hi = blockKeys.size() - 1;
            int ans = -1;
            while (lo <= hi) {
                int mid = (lo + hi) >>> 1;
                int c = order.compare(blockKeys.get(mid), key);
                if (strict ? c < 0 : c <= 0) {
                    ans = mid;
                    lo = mid + 1;
                } else {
                    hi = mid - 1;
                }
            }
            return ans;
        }

        private java.io.BufferedInputStream streamAt(long from) throws java.io.IOException {
            if (stream != null && streamPos == from) {
                return stream;
            }
            if (stream != null) {
                stream.close();
            }
            java.io.FileInputStream fis = new java.io.FileInputStream(file);
            fis.getChannel().position(from);
            stream = new java.io.BufferedInputStream(fis, 1 << 16);
            streamPos = from;
            return stream;
        }

        private java.util.Map.Entry<String, String> remember(java.util.Map.Entry<String, String> e, long end) {
            if (e != null) {
                lastKey = e.getKey();
                lastEnd = end;
            }
            return e;
        }

        java.util.Map.Entry<String, String> find(String key, int mode) {
            if (count == 0) {
                return null;
            }
            try {
                long from;
                if (mode == HIGHER && key.equals(lastKey) && lastEnd >= 0) {
                    from = lastEnd;
                } else {
                    int b = blockFor(key, mode == LOWER);
                    if (b < 0 && (mode == FLOOR || mode == LOWER)) {
                        return null;
                    }
                    from = blockOffsets.get(Math.max(b, 0));
                }
                java.io.BufferedInputStream in = streamAt(from);
                java.util.Map.Entry<String, String> prev = null;
                long prevEnd = -1;
                long pos = from;
                long[] used = new long[1];
                String line;
                while ((line = readLine(in, used)) != null) {
                    long lineStart = pos;
                    pos += used[0];
                    used[0] = 0;
                    int sep = line.indexOf('\\u0001');
                    if (sep <= 0) {
                        continue;
                    }
                    String k = line.substring(0, sep);
                    java.util.Map.Entry<String, String> cur =
                        new java.util.AbstractMap.SimpleImmutableEntry<>(k, line.substring(sep + 1));
                    int c = order.compare(k, key);
                    if (mode == CEIL && c >= 0 || mode == HIGHER && c > 0) {
                        streamPos = pos;
                        return remember(cur, pos);
                    }
                    if (mode == FLOOR && c <= 0 || mode == LOWER && c < 0) {
                        prev = cur;
                        prevEnd = pos;
                        continue;
                    }
                    if (mode == FLOOR || mode == LOWER) {
                        streamPos = pos;
                        return remember(prev, prevEnd);
                    }
                }
                streamPos = pos;
                return (mode == FLOOR || mode == LOWER) ? remember(prev, prevEnd) : null;
            } catch (java.io.IOException e) {
                throw new java.io.UncheckedIOException(e);
            }
        }
    }

    /** Read-only, disk-backed stand-in for the in-memory indexed-file map. */
    @SuppressWarnings("serial")
    static final class DiskIndex extends java.util.TreeMap<String, String> {
        private final transient SparseLines lines;

        DiskIndex(java.io.File f) throws java.io.IOException {
            lines = new SparseLines(f, java.util.Comparator.naturalOrder());
        }

        int headerKeyLen() {
            return lines.headerKeyLen;
        }

        private java.util.Map.Entry<String, String> at(Object key, int mode) {
            return key == null ? null : lines.find(key.toString(), mode);
        }

        @Override public boolean isEmpty() { return lines.count == 0; }
        @Override public int size() { return (int) Math.min(lines.count, Integer.MAX_VALUE); }
        @Override public String firstKey() {
            if (lines.count == 0) {
                throw new java.util.NoSuchElementException();
            }
            return lines.firstKey;
        }
        @Override public java.util.Map.Entry<String, String> firstEntry() {
            return lines.count == 0 ? null : at(lines.firstKey, SparseLines.FLOOR);
        }
        @Override public String get(Object key) {
            java.util.Map.Entry<String, String> e = at(key, SparseLines.FLOOR);
            return e != null && e.getKey().equals(key) ? e.getValue() : null;
        }
        @Override public boolean containsKey(Object key) {
            java.util.Map.Entry<String, String> e = at(key, SparseLines.FLOOR);
            return e != null && e.getKey().equals(key);
        }
        @Override public java.util.Map.Entry<String, String> floorEntry(String key) { return at(key, SparseLines.FLOOR); }
        @Override public java.util.Map.Entry<String, String> lowerEntry(String key) { return at(key, SparseLines.LOWER); }
        @Override public java.util.Map.Entry<String, String> ceilingEntry(String key) { return at(key, SparseLines.CEIL); }
        @Override public java.util.Map.Entry<String, String> higherEntry(String key) { return at(key, SparseLines.HIGHER); }
        @Override public String put(String key, String value) { throw new UnsupportedOperationException("read-only index"); }
        @Override public String remove(Object key) { throw new UnsupportedOperationException("read-only index"); }
    }

    /** Read-only, disk-backed stand-in for the in-memory relative-file map. */
    @SuppressWarnings("serial")
    static final class DiskRel extends java.util.TreeMap<Integer, String> {
        private final transient SparseLines lines;

        DiskRel(java.io.File f) throws java.io.IOException {
            lines = new SparseLines(f, (a, b) -> Long.compare(Long.parseLong(a), Long.parseLong(b)));
        }

        @Override public boolean isEmpty() { return lines.count == 0; }
        @Override public int size() { return (int) Math.min(lines.count, Integer.MAX_VALUE); }
        @Override public String get(Object key) {
            java.util.Map.Entry<String, String> e = key == null ? null : lines.find(key.toString(), SparseLines.FLOOR);
            return e != null && e.getKey().equals(key.toString()) ? e.getValue() : null;
        }
        @Override public boolean containsKey(Object key) { return get(key) != null; }
        @Override public String put(Integer key, String value) { throw new UnsupportedOperationException("read-only relative image"); }
        @Override public String remove(Object key) { throw new UnsupportedOperationException("read-only relative image"); }
    }

    /** Load an existing RELATIVE image ``<path>.rel`` (an ``R`` line, then
     *  ``rrn U+0001 record`` lines); false when no image exists or it is unreadable. */
    private static boolean loadRelative(String path, boolean readOnly) {
        java.io.File f = new java.io.File(path + ".rel");
        if (!f.exists()) {
            return false;
        }
        if (readOnly && f.length() >= diskThreshold()) {
            try {
                REL.put(path, new DiskRel(f));
                return true;
            } catch (Exception e) {
                // fall back to the in-memory load below
            }
        }
        java.util.TreeMap<Integer, String> m = new java.util.TreeMap<>();
        try (java.io.BufferedReader r = new java.io.BufferedReader(new java.io.InputStreamReader(
                new java.io.FileInputStream(f), java.nio.charset.StandardCharsets.UTF_8))) {
            r.readLine();
            String l;
            while ((l = r.readLine()) != null) {
                int sep = l.indexOf('\\u0001');
                if (sep > 0) {
                    m.put(Integer.parseInt(l.substring(0, sep)), l.substring(sep + 1));
                }
            }
        } catch (Exception e) {
            return false;
        }
        REL.put(path, m);
        return true;
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
        java.util.Map.Entry<String, String> found = cur == null
            ? (m.isEmpty() ? null : m.firstEntry())
            : m.higherEntry(cur);
        if (found == null) {
            return null;
        }
        CURSOR.put(path, found.getKey());
        return pad(found.getKey(), kl, false) + (found.getValue() == null ? "" : found.getValue());
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