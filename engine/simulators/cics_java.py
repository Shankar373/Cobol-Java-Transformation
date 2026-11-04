"""Java implementation of SIMCICS-1 (``engine.simulators.cics`` is the reference).

``SIMCICS_JAVA`` is one self-contained source file (class ``SimCics``); its ``main`` runs a script file and
prints the canonical trace.  ``tests/integration/test_simcics_conformance.py`` holds it equal to the model.
"""

from __future__ import annotations

SIMCICS_JAVA = '''import java.util.*;

public final class SimCics {
    static final String SPEC_VERSION = "SIMCICS-1.0";
    static final int NORMAL = 0, FILENOTFOUND = 12, NOTFND = 13, DUPREC = 14, INVREQ = 16, NOTOPEN = 19,
        ENDFILE = 20, LENGERR = 22, ITEMERR = 26, QIDERR = 44;

    static String name(int code) {
        switch (code) {
            case NORMAL: return "NORMAL"; case FILENOTFOUND: return "FILENOTFOUND"; case NOTFND: return "NOTFND";
            case DUPREC: return "DUPREC"; case INVREQ: return "INVREQ"; case NOTOPEN: return "NOTOPEN";
            case ENDFILE: return "ENDFILE"; case LENGERR: return "LENGERR"; case ITEMERR: return "ITEMERR";
            case QIDERR: return "QIDERR"; default: return Integer.toString(code);
        }
    }

    static final class FileDef {
        final String name; final int keyLength, recordLength; boolean open;
        final TreeMap<String, String> records = new TreeMap<>();
        String held, cursor, position; boolean browsing;
        FileDef(String name, int keyLength, int recordLength, boolean open) {
            this.name = name; this.keyLength = keyLength; this.recordLength = recordLength; this.open = open;
        }
    }

    static final class Out {
        int resp; String data = ""; int item;
        Out(int resp) { this.resp = resp; }
    }

    final Map<String, FileDef> files = new LinkedHashMap<>();
    final Map<String, List<String>> queues = new LinkedHashMap<>();
    final Map<String, Integer> nextCursor = new HashMap<>();
    final Deque<Runnable> undo = new ArrayDeque<>();

    void define(String name, int keyLength, int recordLength, boolean open) {
        files.put(name, new FileDef(name, keyLength, recordLength, open));
    }

    void load(String name, String record) {
        FileDef f = files.get(name);
        if (record.length() != f.recordLength) throw new IllegalArgumentException("LOAD " + name + ": wrong record length");
        f.records.put(record.substring(0, f.keyLength), record);
    }

    int check(String name, FileDef[] out) {
        FileDef f = files.get(name);
        if (f == null) return FILENOTFOUND;
        if (!f.open) return NOTOPEN;
        out[0] = f;
        return NORMAL;
    }

    Out read(String name, String key, boolean update) {
        FileDef[] fh = new FileDef[1];
        int r = check(name, fh);
        if (r != NORMAL) return new Out(r);
        FileDef f = fh[0];
        if (key.length() != f.keyLength) return new Out(LENGERR);
        String record = f.records.get(key);
        if (record == null) return new Out(NOTFND);
        if (update) f.held = key;
        Out o = new Out(NORMAL); o.data = record; return o;
    }

    int write(String name, String key, String data) {
        FileDef[] fh = new FileDef[1];
        int r = check(name, fh);
        if (r != NORMAL) return r;
        FileDef f = fh[0];
        if (data.length() != f.recordLength || key.length() != f.keyLength) return LENGERR;
        if (!data.substring(0, f.keyLength).equals(key)) return INVREQ;
        if (f.records.containsKey(key)) return DUPREC;
        f.records.put(key, data);
        undo.push(() -> f.records.remove(key));
        return NORMAL;
    }

    int rewrite(String name, String data) {
        FileDef[] fh = new FileDef[1];
        int r = check(name, fh);
        if (r != NORMAL) return r;
        FileDef f = fh[0];
        if (f.held == null) return INVREQ;
        if (data.length() != f.recordLength) return LENGERR;
        if (!data.substring(0, f.keyLength).equals(f.held)) return INVREQ;
        String key = f.held, previous = f.records.get(key);
        f.records.put(key, data);
        f.held = null;
        undo.push(() -> f.records.put(key, previous));
        return NORMAL;
    }

    int delete(String name, String key) {
        FileDef[] fh = new FileDef[1];
        int r = check(name, fh);
        if (r != NORMAL) return r;
        FileDef f = fh[0];
        if (key == null) {
            if (f.held == null) return INVREQ;
            key = f.held;
        } else if (key.length() != f.keyLength) {
            return LENGERR;
        }
        String previous = f.records.get(key);
        if (previous == null) return NOTFND;
        f.records.remove(key);
        if (key.equals(f.held)) f.held = null;
        final String k = key;
        undo.push(() -> f.records.put(k, previous));
        return NORMAL;
    }

    int startbr(String name, String key, boolean equal) {
        FileDef[] fh = new FileDef[1];
        int r = check(name, fh);
        if (r != NORMAL) return r;
        FileDef f = fh[0];
        if (key.length() != f.keyLength) return LENGERR;
        if (f.browsing) return INVREQ;
        String start;
        if (equal) {
            if (!f.records.containsKey(key)) return NOTFND;
            start = key;
        } else {
            start = f.records.ceilingKey(key);
            if (start == null) return NOTFND;
        }
        f.browsing = true; f.position = start; f.cursor = null;
        return NORMAL;
    }

    Out readnext(String name) {
        FileDef[] fh = new FileDef[1];
        int r = check(name, fh);
        if (r != NORMAL) return new Out(r);
        FileDef f = fh[0];
        if (!f.browsing) return new Out(INVREQ);
        String k = f.cursor == null ? f.records.ceilingKey(f.position) : f.records.higherKey(f.cursor);
        if (k == null) return new Out(ENDFILE);
        f.cursor = k;
        Out o = new Out(NORMAL); o.data = f.records.get(k); return o;
    }

    Out readprev(String name) {
        FileDef[] fh = new FileDef[1];
        int r = check(name, fh);
        if (r != NORMAL) return new Out(r);
        FileDef f = fh[0];
        if (!f.browsing) return new Out(INVREQ);
        String k = f.cursor == null ? f.records.lowerKey(f.position) : f.records.lowerKey(f.cursor);
        if (k == null) return new Out(ENDFILE);
        f.cursor = k;
        Out o = new Out(NORMAL); o.data = f.records.get(k); return o;
    }

    int endbr(String name) {
        FileDef[] fh = new FileDef[1];
        int r = check(name, fh);
        if (r != NORMAL) return r;
        FileDef f = fh[0];
        if (!f.browsing) return INVREQ;
        f.browsing = false; f.cursor = null; f.position = null;
        return NORMAL;
    }

    Out writeq(String queue, String data) {
        List<String> items = queues.computeIfAbsent(queue, q -> new ArrayList<>());
        items.add(data);
        undo.push(() -> {
            List<String> list = queues.get(queue);
            if (list == null) return;
            list.remove(list.size() - 1);
            if (list.isEmpty()) queues.remove(queue);
        });
        Out o = new Out(NORMAL); o.item = items.size(); return o;
    }

    Out readq(String queue, Integer item) {
        List<String> items = queues.get(queue);
        if (items == null) return new Out(QIDERR);
        int n = item == null ? nextCursor.getOrDefault(queue, 0) + 1 : item;
        if (n < 1 || n > items.size()) return new Out(ITEMERR);
        nextCursor.put(queue, n);
        Out o = new Out(NORMAL); o.item = n; o.data = items.get(n - 1); return o;
    }

    int deleteq(String queue) {
        List<String> items = queues.get(queue);
        if (items == null) return QIDERR;
        queues.remove(queue);
        nextCursor.remove(queue);
        undo.push(() -> queues.put(queue, items));
        return NORMAL;
    }

    int syncpoint(boolean rollback) {
        if (rollback) while (!undo.isEmpty()) undo.pop().run();
        undo.clear();
        for (FileDef f : files.values()) f.held = null;
        return NORMAL;
    }

    // ---- scripts and the canonical trace -------------------------------------------------

    static String withData(Out o) {
        return o.resp != NORMAL ? name(o.resp) : name(o.resp) + " data=" + o.data;
    }

    static String step(SimCics c, String op, String[] a) {
        switch (op) {
            case "READ": return withData(c.read(a[0], a[1], a.length > 2 && a[2].equals("UPDATE")));
            case "WRITE": return name(c.write(a[0], a[1], a[2]));
            case "REWRITE": return name(c.rewrite(a[0], a[1]));
            case "DELETE": return name(c.delete(a[0], a.length > 1 ? a[1] : null));
            case "STARTBR": return name(c.startbr(a[0], a[1], a[2].equals("EQUAL")));
            case "READNEXT": return withData(c.readnext(a[0]));
            case "READPREV": return withData(c.readprev(a[0]));
            case "ENDBR": return name(c.endbr(a[0]));
            case "WRITEQ": { Out o = c.writeq(a[0], a[1]); return name(o.resp) + " item=" + o.item; }
            case "READQ": { Out o = c.readq(a[0], a[1].equals("NEXT") ? null : Integer.valueOf(a[1]));
                return o.resp != NORMAL ? name(o.resp) : name(o.resp) + " item=" + o.item + " data=" + o.data; }
            case "DELETEQ": return name(c.deleteq(a[0]));
            case "SYNCPOINT": return name(c.syncpoint(a.length > 0 && a[0].equals("ROLLBACK")));
            default: return "INVREQ";
        }
    }

    static List<String> runScript(String script) {
        SimCics c = new SimCics();
        List<String> trace = new ArrayList<>();
        for (String raw : script.split("\\\\n")) {
            String line = raw.strip();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] parts = line.split(" ");
            String op = parts[0];
            String[] args = Arrays.copyOfRange(parts, 1, parts.length);
            if (op.equals("FILE")) {
                c.define(args[0], Integer.parseInt(args[1]), Integer.parseInt(args[2]), args[3].equals("open"));
                trace.add(line + " -> " + SPEC_VERSION);
            } else if (op.equals("LOAD")) {
                c.load(args[0], args[1]);
                trace.add(line + " -> loaded");
            } else {
                trace.add(line + " -> " + step(c, op, args));
            }
        }
        return trace;
    }

    public static void main(String[] args) throws Exception {
        String script = new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(args[0])),
            java.nio.charset.StandardCharsets.UTF_8);
        for (String line : runScript(script)) System.out.println(line);
    }
}
'''
