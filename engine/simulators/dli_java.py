"""Java implementation of SIMDLI-1 (``engine.simulators.dli`` is the reference).

``SIMDLI_JAVA`` is one self-contained source file (class ``SimDli``); its ``main`` runs a script file and
prints the canonical trace.  ``tests/integration/test_simdli_conformance.py`` holds it equal to the model.
"""

from __future__ import annotations

SIMDLI_JAVA = '''import java.util.*;
import java.util.regex.*;

public final class SimDli {
    static final String SPEC_VERSION = "SIMDLI-1.0";
    static final String OK = "  ";
    static final Pattern SSA = Pattern.compile("^([A-Za-z0-9]+)(?:\\\\(=([^)]*)\\\\))?$");

    static final class Type {
        final String name, parent; final int keyLength, dataLength;
        Type(String name, String parent, int keyLength, int dataLength) {
            this.name = name; this.parent = parent; this.keyLength = keyLength; this.dataLength = dataLength;
        }
    }

    static final class Node {
        final Type type; String data; final List<Node> children = new ArrayList<>(); Node parent;
        Node(Type type, String data, Node parent) { this.type = type; this.data = data; this.parent = parent; }
        String key() { return data.substring(0, type.keyLength); }
    }

    static final class Result {
        final String status; final Node node;
        Result(String status, Node node) { this.status = status; this.node = node; }
    }

    static final class Ssa {
        final String name, key;
        Ssa(String name, String key) { this.name = name; this.key = key; }
    }

    final Map<String, Type> types = new LinkedHashMap<>();
    final Map<String, Integer> order = new HashMap<>();
    final List<Node> roots = new ArrayList<>();
    int index = -1;
    Node current, parent;

    SimDli(List<Type> list) {
        if (list.isEmpty() || !list.get(0).parent.isEmpty()) throw new IllegalArgumentException("the first segment type is the root");
        for (int i = 0; i < list.size(); i++) { types.put(list.get(i).name, list.get(i)); order.put(list.get(i).name, i); }
    }

    List<Node> sequence() { List<Node> out = new ArrayList<>(); walk(roots, out); return out; }
    void walk(List<Node> nodes, List<Node> out) { for (Node n : nodes) { out.add(n); walk(n.children, out); } }

    List<Node> siblings(Node p) { return p == null ? roots : p.children; }

    Ssa parse(String ssa) {
        Matcher m = SSA.matcher(ssa);
        if (!m.matches()) return null;
        return new Ssa(m.group(1).toUpperCase(), m.group(2));
    }

    boolean matches(Node n, String name, String key) { return n.type.name.equals(name) && (key == null || n.key().equals(key)); }

    List<Ssa> parseAll(List<String> ssas) {
        List<Ssa> out = new ArrayList<>();
        for (String s : ssas) {
            Ssa p = parse(s);
            if (p == null || !types.containsKey(p.name)) return null;
            out.add(p);
        }
        return out;
    }

    boolean pathOk(List<Ssa> parsed) {
        String expected = "";
        for (Ssa p : parsed) {
            if (!types.get(p.name).parent.equals(expected)) return false;
            expected = p.name;
        }
        return true;
    }

    Result gu(List<String> ssas) {
        if (ssas.isEmpty()) return new Result("AK", null);
        List<Ssa> parsed = parseAll(ssas);
        if (parsed == null || !pathOk(parsed)) return new Result("AK", null);
        List<Node> sibs = roots;
        Node node = null;
        for (Ssa p : parsed) {
            node = null;
            for (Node n : sibs) if (matches(n, p.name, p.key)) { node = n; break; }
            if (node == null) return new Result("GE", null);
            sibs = node.children;
        }
        setPosition(node, true);
        return new Result(OK, node);
    }

    Result gn(List<String> ssas) {
        if (ssas.size() > 1) return new Result("AK", null);
        Ssa target = null;
        if (!ssas.isEmpty()) {
            target = parse(ssas.get(0));
            if (target == null || !types.containsKey(target.name)) return new Result("AK", null);
        }
        List<Node> seq = sequence();
        for (int i = index + 1; i < seq.size(); i++) {
            Node n = seq.get(i);
            if (target == null || matches(n, target.name, target.key)) {
                index = i; current = n; parent = n;
                return new Result(OK, n);
            }
        }
        current = null;
        return new Result("GB", null);
    }

    boolean isDescendant(Node node, Node ancestor) {
        for (Node c = node.parent; c != null; c = c.parent) if (c == ancestor) return true;
        return false;
    }

    Result gnp(List<String> ssas) {
        if (ssas.size() > 1) return new Result("AK", null);
        if (parent == null) return new Result("GP", null);
        Ssa target = null;
        if (!ssas.isEmpty()) {
            target = parse(ssas.get(0));
            if (target == null || !types.containsKey(target.name)) return new Result("AK", null);
        }
        List<Node> seq = sequence();
        for (int i = index + 1; i < seq.size(); i++) {
            Node n = seq.get(i);
            if (!isDescendant(n, parent)) break;
            if (target == null || matches(n, target.name, target.key)) {
                index = i; current = n;
                return new Result(OK, n);
            }
        }
        current = null;
        return new Result("GE", null);
    }

    Result isrt(List<String> ssas, String data) {
        if (ssas.isEmpty()) return new Result("AK", null);
        List<Ssa> parsed = parseAll(ssas);
        if (parsed == null || !pathOk(parsed)) return new Result("AK", null);
        Ssa last = parsed.get(parsed.size() - 1);
        if (last.key != null) return new Result("AK", null);
        Type segType = types.get(last.name);
        if (data.length() != segType.dataLength) return new Result("AK", null);
        Node par = null;
        List<Node> sibs = roots;
        for (int i = 0; i < parsed.size() - 1; i++) {
            Ssa p = parsed.get(i);
            if (p.key == null) return new Result("AK", null);
            Node found = null;
            for (Node n : sibs) if (matches(n, p.name, p.key)) { found = n; break; }
            if (found == null) return new Result("GE", null);
            par = found;
            sibs = found.children;
        }
        Node node = new Node(segType, data, par);
        for (Node s : sibs) if (s.type == segType && s.key().equals(node.key())) return new Result("II", null);
        sibs.add(node);
        sibs.sort((a, b) -> {
            int c = Integer.compare(order.get(a.type.name), order.get(b.type.name));
            return c != 0 ? c : a.key().compareTo(b.key());
        });
        setPosition(node, false);
        return new Result(OK, node);
    }

    String dlet() {
        if (current == null) return "DJ";
        Node node = current;
        int idx = sequence().indexOf(node);
        siblings(node.parent).remove(node);
        index = idx - 1;
        current = null;
        if (parent == node || (parent != null && isDescendant(parent, node))) parent = null;
        return OK;
    }

    Result repl(String data) {
        if (current == null) return new Result("DJ", null);
        Node node = current;
        if (data.length() != node.type.dataLength) return new Result("AK", null);
        if (!data.substring(0, node.type.keyLength).equals(node.key())) return new Result("DA", null);
        node.data = data;
        return new Result(OK, node);
    }

    void setPosition(Node node, boolean establishParent) {
        index = sequence().indexOf(node);
        current = node;
        if (establishParent) parent = node;
    }

    // ---- scripts and the canonical trace -------------------------------------------------

    static String show(Result r) {
        String shown = r.status.equals(OK) ? "OK" : r.status;
        return r.node == null ? shown : shown + " seg=" + r.node.type.name + " data=" + r.node.data;
    }

    static String step(SimDli d, String op, String[] a) {
        List<String> ssas = new ArrayList<>();
        if (a.length > 0) for (String s : a[0].split("/")) if (!s.isEmpty()) ssas.add(s);
        switch (op) {
            case "GU": return show(d.gu(ssas));
            case "GN": return show(d.gn(ssas));
            case "GNP": return show(d.gnp(ssas));
            case "ISRT": return show(d.isrt(ssas, a.length > 1 ? a[1] : ""));
            case "DLET": return show(new Result(d.dlet(), null));
            case "REPL": return show(d.repl(a.length > 0 ? a[0] : ""));
            default: return show(new Result("AD", null));
        }
    }

    static List<String> runScript(String script) {
        SimDli dli = null;
        List<String> trace = new ArrayList<>();
        for (String raw : script.split("\\\\n")) {
            String line = raw.strip();
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] parts = line.split(" ");
            String op = parts[0];
            String[] args = Arrays.copyOfRange(parts, 1, parts.length);
            if (op.equals("DBD")) {
                List<Type> list = new ArrayList<>();
                for (String spec : args) {
                    String[] f = spec.split(":", -1);
                    list.add(new Type(f[0].toUpperCase(), f[1].toUpperCase(), Integer.parseInt(f[2]), Integer.parseInt(f[3])));
                }
                dli = new SimDli(list);
                trace.add(line + " -> " + SPEC_VERSION);
                continue;
            }
            if (dli == null) throw new IllegalStateException("a script starts with DBD");
            trace.add(line + " -> " + step(dli, op, args));
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
