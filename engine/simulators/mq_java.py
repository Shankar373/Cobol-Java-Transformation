"""Java implementation of SIMMQ-1 (``engine.simulators.mq`` is the reference).

``SIMMQ_JAVA`` is one self-contained source file (class ``SimMq``) that a generated program can be
compiled with, and whose ``main`` runs a script file and prints the canonical trace.  The two
implementations are held equal by ``tests/integration/test_simmq_conformance.py``.
"""

from __future__ import annotations

SIMMQ_JAVA = '''import java.util.*;

public final class SimMq {
    static final String SPEC_VERSION = "SIMMQ-1.0";
    static final int CC_OK = 0, CC_WARNING = 1, CC_FAILED = 2;
    static final int RC_NONE = 0, RC_HCONN_ERROR = 2018, RC_HOBJ_ERROR = 2019, RC_GET_INHIBITED = 2016,
        RC_NO_MSG = 2033, RC_NOT_OPEN_BROWSE = 2036, RC_NOT_OPEN_INPUT = 2037, RC_NOT_OPEN_OUTPUT = 2039,
        RC_IN_USE = 2042, RC_PUT_INHIBITED = 2051, RC_Q_FULL = 2053, RC_QMGR_NAME = 2058,
        RC_TRUNC_ACCEPTED = 2079, RC_TRUNC_FAILED = 2080, RC_UNKNOWN_OBJECT = 2085, RC_OPTIONS = 2046;
    static final int OO_INPUT_SHARED = 2, OO_INPUT_EXCLUSIVE = 4, OO_BROWSE = 8, OO_OUTPUT = 16;
    static final int OPEN_BITS = 2 | 4 | 8 | 16;
    static final int OPT_WAIT = 1, OPT_SYNCPOINT = 2, OPT_NO_SYNCPOINT = 4, OPT_BROWSE_FIRST = 16,
        OPT_BROWSE_NEXT = 32, OPT_ACCEPT_TRUNCATED = 64;
    static final int GET_BITS = 1 | 2 | 4 | 16 | 32 | 64;
    static final int PUT_BITS = 2 | 4;

    static final class Message {
        byte[] data;
        Integer owner;
        Integer takenBy;
        Message(byte[] data, Integer owner) { this.data = data; this.owner = owner; }
    }

    static final class Queue {
        final String name;
        int maxDepth = 5000;
        boolean getInhibited, putInhibited, exclusiveInput;
        int sharedInputs;
        final ArrayList<Message> messages = new ArrayList<>();
        Queue(String name) { this.name = name; }
    }

    static final class Handle {
        final String queue;
        final int options;
        int cursor = -1;
        Handle(String queue, int options) { this.queue = queue; this.options = options; }
    }

    static final class Result {
        int cc, rc, length;
        byte[] data = new byte[0];
        int handle;
        Result(int cc, int rc) { this.cc = cc; this.rc = rc; }
    }

    final String qmgr;
    final Map<String, Queue> queues = new LinkedHashMap<>();
    final Map<Integer, Map<Integer, Handle>> connections = new LinkedHashMap<>();
    int nextConn = 1, nextObj = 1;

    SimMq(String qmgr, String[] names) {
        this.qmgr = qmgr;
        for (String n : names) queues.put(n, new Queue(n));
    }

    void setq(String name, int maxDepth, boolean getInh, boolean putInh) {
        Queue q = queues.computeIfAbsent(name, Queue::new);
        q.maxDepth = maxDepth;
        q.getInhibited = getInh;
        q.putInhibited = putInh;
    }

    int depth(String name) {
        int n = 0;
        for (Message m : queues.get(name).messages) if (m.owner == null && m.takenBy == null) n++;
        return n;
    }

    Result mqconn(String name) {
        String t = name.strip();
        if (!t.isEmpty() && !t.equals(qmgr)) return new Result(CC_FAILED, RC_QMGR_NAME);
        Result r = new Result(CC_OK, RC_NONE);
        r.handle = nextConn++;
        connections.put(r.handle, new LinkedHashMap<>());
        return r;
    }

    Result mqopen(int hconn, String name, int options) {
        Map<Integer, Handle> handles = connections.get(hconn);
        if (handles == null) return new Result(CC_FAILED, RC_HCONN_ERROR);
        if ((options & ~OPEN_BITS) != 0 || (options & OPEN_BITS) == 0) return new Result(CC_FAILED, RC_OPTIONS);
        if ((options & OO_INPUT_SHARED) != 0 && (options & OO_INPUT_EXCLUSIVE) != 0)
            return new Result(CC_FAILED, RC_OPTIONS);
        Queue q = queues.get(name.strip());
        if (q == null) return new Result(CC_FAILED, RC_UNKNOWN_OBJECT);
        if ((options & OO_INPUT_EXCLUSIVE) != 0 && (q.exclusiveInput || q.sharedInputs != 0))
            return new Result(CC_FAILED, RC_IN_USE);
        if ((options & OO_INPUT_SHARED) != 0 && q.exclusiveInput) return new Result(CC_FAILED, RC_IN_USE);
        if ((options & OO_INPUT_EXCLUSIVE) != 0) q.exclusiveInput = true;
        if ((options & OO_INPUT_SHARED) != 0) q.sharedInputs++;
        Result r = new Result(CC_OK, RC_NONE);
        r.handle = nextObj++;
        handles.put(r.handle, new Handle(q.name, options));
        return r;
    }

    Result lookup(int hconn, int hobj, Handle[] out) {
        Map<Integer, Handle> handles = connections.get(hconn);
        if (handles == null) return new Result(CC_FAILED, RC_HCONN_ERROR);
        Handle h = handles.get(hobj);
        if (h == null) return new Result(CC_FAILED, RC_HOBJ_ERROR);
        out[0] = h;
        return null;
    }

    Result mqput(int hconn, int hobj, byte[] data, int options) {
        Handle[] hh = new Handle[1];
        Result err = lookup(hconn, hobj, hh);
        if (err != null) return err;
        Handle h = hh[0];
        if ((options & ~PUT_BITS) != 0 || ((options & OPT_SYNCPOINT) != 0 && (options & OPT_NO_SYNCPOINT) != 0))
            return new Result(CC_FAILED, RC_OPTIONS);
        if ((h.options & OO_OUTPUT) == 0) return new Result(CC_FAILED, RC_NOT_OPEN_OUTPUT);
        Queue q = queues.get(h.queue);
        if (q.putInhibited) return new Result(CC_FAILED, RC_PUT_INHIBITED);
        if (q.messages.size() >= q.maxDepth) return new Result(CC_FAILED, RC_Q_FULL);
        q.messages.add(new Message(data.clone(), (options & OPT_SYNCPOINT) != 0 ? Integer.valueOf(hconn) : null));
        return new Result(CC_OK, RC_NONE);
    }

    Result mqget(int hconn, int hobj, int maxLength, int options) {
        Handle[] hh = new Handle[1];
        Result err = lookup(hconn, hobj, hh);
        if (err != null) return err;
        Handle h = hh[0];
        int browse = options & (OPT_BROWSE_FIRST | OPT_BROWSE_NEXT);
        boolean bad = (options & ~GET_BITS) != 0
            || ((options & OPT_SYNCPOINT) != 0 && (options & OPT_NO_SYNCPOINT) != 0)
            || ((options & OPT_BROWSE_FIRST) != 0 && (options & OPT_BROWSE_NEXT) != 0)
            || (browse != 0 && (options & OPT_SYNCPOINT) != 0);
        if (bad || maxLength < 0) return new Result(CC_FAILED, RC_OPTIONS);
        if (browse != 0 && (h.options & OO_BROWSE) == 0) return new Result(CC_FAILED, RC_NOT_OPEN_BROWSE);
        if (browse == 0 && (h.options & (OO_INPUT_SHARED | OO_INPUT_EXCLUSIVE)) == 0)
            return new Result(CC_FAILED, RC_NOT_OPEN_INPUT);
        Queue q = queues.get(h.queue);
        if (q.getInhibited) return new Result(CC_FAILED, RC_GET_INHIBITED);
        ArrayList<Message> visible = new ArrayList<>();
        for (Message m : q.messages)
            if ((m.owner == null || m.owner == hconn) && m.takenBy == null) visible.add(m);
        Message message;
        if (browse != 0) {
            h.cursor = (options & OPT_BROWSE_FIRST) != 0 ? 0 : h.cursor + 1;
            if (h.cursor >= visible.size()) {
                h.cursor = (options & OPT_BROWSE_NEXT) != 0 ? Math.max(visible.size() - 1, -1) : -1;
                return new Result(CC_FAILED, RC_NO_MSG);
            }
            message = visible.get(h.cursor);
        } else {
            if (visible.isEmpty()) return new Result(CC_FAILED, RC_NO_MSG);
            message = visible.get(0);
        }
        int length = message.data.length;
        Result r;
        if (length > maxLength && (options & OPT_ACCEPT_TRUNCATED) == 0) {
            r = new Result(CC_FAILED, RC_TRUNC_FAILED);
        } else {
            r = length > maxLength ? new Result(CC_WARNING, RC_TRUNC_ACCEPTED) : new Result(CC_OK, RC_NONE);
            if (browse == 0) {
                if ((options & OPT_SYNCPOINT) != 0) message.takenBy = hconn;
                else q.messages.remove(message);
            }
        }
        r.length = length;
        r.data = Arrays.copyOf(message.data, Math.min(length, maxLength));
        return r;
    }

    Result mqclose(int hconn, int hobj) {
        Handle[] hh = new Handle[1];
        Result err = lookup(hconn, hobj, hh);
        if (err != null) return err;
        Handle h = hh[0];
        Queue q = queues.get(h.queue);
        if ((h.options & OO_INPUT_EXCLUSIVE) != 0) q.exclusiveInput = false;
        if ((h.options & OO_INPUT_SHARED) != 0) q.sharedInputs--;
        connections.get(hconn).remove(hobj);
        return new Result(CC_OK, RC_NONE);
    }

    Result mqcmit(int hconn) {
        if (!connections.containsKey(hconn)) return new Result(CC_FAILED, RC_HCONN_ERROR);
        for (Queue q : queues.values()) {
            ArrayList<Message> kept = new ArrayList<>();
            for (Message m : q.messages) {
                if (m.takenBy != null && m.takenBy == hconn) continue;
                if (m.owner != null && m.owner == hconn) m.owner = null;
                kept.add(m);
            }
            q.messages.clear();
            q.messages.addAll(kept);
        }
        return new Result(CC_OK, RC_NONE);
    }

    Result mqback(int hconn) {
        if (!connections.containsKey(hconn)) return new Result(CC_FAILED, RC_HCONN_ERROR);
        for (Queue q : queues.values()) {
            ArrayList<Message> kept = new ArrayList<>();
            for (Message m : q.messages) {
                if (m.owner != null && m.owner == hconn) continue;
                if (m.takenBy != null && m.takenBy == hconn) m.takenBy = null;
                kept.add(m);
            }
            q.messages.clear();
            q.messages.addAll(kept);
        }
        return new Result(CC_OK, RC_NONE);
    }

    Result mqdisc(int hconn) {
        if (!connections.containsKey(hconn)) return new Result(CC_FAILED, RC_HCONN_ERROR);
        mqcmit(hconn);
        for (Integer hobj : new ArrayList<>(connections.get(hconn).keySet())) mqclose(hconn, hobj);
        connections.remove(hconn);
        return new Result(CC_OK, RC_NONE);
    }

    // ---- scripts and the canonical trace -------------------------------------------------

    static String hex(byte[] data) {
        if (data.length == 0) return "-";
        StringBuilder sb = new StringBuilder();
        for (byte b : data) sb.append(String.format("%02x", b & 0xff));
        return sb.toString();
    }

    static byte[] unhex(String s) {
        if (s.equals("-")) return new byte[0];
        byte[] out = new byte[s.length() / 2];
        for (int i = 0; i < out.length; i++) out[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        return out;
    }

    static String step(SimMq mq, String op, String[] a) {
        switch (op) {
            case "SETQ": mq.setq(a[0], Integer.parseInt(a[1]), a[2].equals("1"), a[3].equals("1")); return "ok";
            case "DEPTH": return "depth=" + mq.depth(a[0]);
            case "CONN": { Result r = mq.mqconn(a.length > 0 ? a[0] : "");
                return r.cc + " " + r.rc + " h=" + r.handle; }
            case "OPEN": { Result r = mq.mqopen(Integer.parseInt(a[0]), a[1], Integer.parseInt(a[2]));
                return r.cc + " " + r.rc + " h=" + r.handle; }
            case "PUT": { Result r = mq.mqput(Integer.parseInt(a[0]), Integer.parseInt(a[1]), unhex(a[2]),
                Integer.parseInt(a[3])); return r.cc + " " + r.rc; }
            case "GET": { Result r = mq.mqget(Integer.parseInt(a[0]), Integer.parseInt(a[1]),
                Integer.parseInt(a[2]), Integer.parseInt(a[3]));
                return r.cc + " " + r.rc + " len=" + r.length + " data=" + hex(r.data); }
            case "CLOSE": { Result r = mq.mqclose(Integer.parseInt(a[0]), Integer.parseInt(a[1]));
                return r.cc + " " + r.rc; }
            case "CMIT": { Result r = mq.mqcmit(Integer.parseInt(a[0])); return r.cc + " " + r.rc; }
            case "BACK": { Result r = mq.mqback(Integer.parseInt(a[0])); return r.cc + " " + r.rc; }
            case "DISC": { Result r = mq.mqdisc(Integer.parseInt(a[0])); return r.cc + " " + r.rc; }
            default: throw new IllegalArgumentException("unknown operation " + op);
        }
    }

    static List<String> runScript(String script) {
        SimMq mq = null;
        List<String> trace = new ArrayList<>();
        for (String raw : script.split("\\n")) {
            String line = raw.strip();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] parts = line.split(" ");
            String op = parts[0];
            String[] args = Arrays.copyOfRange(parts, 1, parts.length);
            if (op.equals("QMGR")) {
                mq = new SimMq(args[0], args[1].split(","));
                trace.add(line + " -> " + SPEC_VERSION);
                continue;
            }
            if (mq == null) throw new IllegalStateException("a script starts with QMGR");
            trace.add(line + " -> " + step(mq, op, args));
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
