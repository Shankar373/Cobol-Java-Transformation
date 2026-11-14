"""Disk-backed read-only index of the generated Java file runtime.

Large INPUT-opened indexed and relative images are read through a sparse
on-disk index instead of being loaded into a TreeMap. These tests prove the
disk-backed map answers exactly like the in-memory one (differential), that a
dataset far larger than the Java heap can be scanned and probed, and that
generated-runtime behavior is unchanged when disk mode is forced on small
files. They need a JDK: skipped on the hermetic lane, failures on the Docker
lane (same rule as ``tests.oracle_java_helpers``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.transformation.file_io_support_template import COBOL_FILE_IO_JAVA
from enterprise.vsam import migrate_export
from tests.enterprise.vsam_support import (
    fixed_export,
    ksds_records,
    make_manifest,
    rrds_export,
    write_export,
)

DIFF_JAVA = r"""
import java.io.*;
import java.util.*;

public class Diff {
    static int checks = 0;
    static void same(String what, Object a, Object b) {
        checks++;
        if (!Objects.equals(a, b)) throw new AssertionError(what + ": expected " + a + " got " + b);
    }
    static String show(Map.Entry<String, String> e) { return e == null ? null : e.getKey() + "=" + e.getValue(); }

    public static void main(String[] args) throws Exception {
        File f = new File(args[0]);
        Random rnd = new Random(7);
        if (args[1].equals("idx")) {
            TreeMap<String, String> ref = new TreeMap<>();
            try (BufferedReader r = new BufferedReader(new InputStreamReader(new FileInputStream(f), "UTF-8"))) {
                r.readLine();
                String l;
                while ((l = r.readLine()) != null) { int s = l.indexOf('\u0001'); ref.put(l.substring(0, s), l.substring(s + 1)); }
            }
            CobolFileIo.DiskIndex d = new CobolFileIo.DiskIndex(f);
            List<String> keys = new ArrayList<>(ref.keySet());
            same("size", ref.size(), d.size());
            same("empty", ref.isEmpty(), d.isEmpty());
            same("firstKey", ref.firstKey(), d.firstKey());
            same("firstEntry", show(ref.firstEntry()), show(d.firstEntry()));
            List<String> probes = new ArrayList<>(Arrays.asList("", "0", "~~~~~", "0000", "zzzz"));
            for (int i = 0; i < 6000; i++) {
                String k = keys.get(rnd.nextInt(keys.size()));
                probes.add(k);
                probes.add(k + "~");
                probes.add(k.substring(0, k.length() - 1));
            }
            for (String p : probes) {
                same("floor " + p, show(ref.floorEntry(p)), show(d.floorEntry(p)));
                same("lower " + p, show(ref.lowerEntry(p)), show(d.lowerEntry(p)));
                same("ceiling " + p, show(ref.ceilingEntry(p)), show(d.ceilingEntry(p)));
                same("higher " + p, show(ref.higherEntry(p)), show(d.higherEntry(p)));
                same("get " + p, ref.get(p), d.get(p));
                same("contains " + p, ref.containsKey(p), d.containsKey(p));
            }
            String cursor = null;
            for (Map.Entry<String, String> e : ref.entrySet()) {
                Map.Entry<String, String> got = cursor == null ? d.firstEntry() : d.higherEntry(cursor);
                same("chain", show(e), show(got));
                cursor = e.getKey();
            }
            same("chain end", null, show(d.higherEntry(cursor)));
        } else {
            TreeMap<Integer, String> ref = new TreeMap<>();
            try (BufferedReader r = new BufferedReader(new InputStreamReader(new FileInputStream(f), "UTF-8"))) {
                r.readLine();
                String l;
                while ((l = r.readLine()) != null) { int s = l.indexOf('\u0001'); ref.put(Integer.parseInt(l.substring(0, s)), l.substring(s + 1)); }
            }
            CobolFileIo.DiskRel d = new CobolFileIo.DiskRel(f);
            same("size", ref.size(), d.size());
            int max = ref.lastKey() + 20;
            for (int i = 0; i < 8000; i++) {
                int n = rnd.nextInt(max + 1);
                same("get " + n, ref.get(n), d.get(n));
                same("contains " + n, ref.containsKey(n), d.containsKey(n));
            }
        }
        System.out.println("OK " + checks);
    }
}
"""

SCAN_JAVA = r"""
import java.util.*;

public class Scan {
    public static void main(String[] args) {
        int total = Integer.parseInt(args[0]);
        String p = "big.dat";
        if (!CobolFileIo.open(p, "INPUT", 8).equals("00")) throw new AssertionError("open failed");
        long n = 0;
        String r, prev = null;
        while ((r = CobolFileIo.readNext(p)) != null) {
            String k = r.substring(0, 8);
            if (prev != null && k.compareTo(prev) <= 0) throw new AssertionError("order " + prev + " " + k);
            prev = k;
            n++;
        }
        if (n != total) throw new AssertionError("scanned " + n + " of " + total);
        Random rnd = new Random(1);
        for (int i = 0; i < 2000; i++) {
            int id = 1 + rnd.nextInt(total);
            String key = String.format("%08d", id);
            String expected = key + String.format("REC%03d", id % 1000) + "X".repeat(86);
            String got = CobolFileIo.readKey(p, key);
            if (!expected.equals(got)) throw new AssertionError("key " + key + " -> " + got);
        }
        if (CobolFileIo.readKey(p, "99999999") != null) throw new AssertionError("phantom key");
        CobolFileIo.close(p);
        System.out.println("SCAN " + n);
    }
}
"""


@pytest.fixture(scope="module")
def jdk():
    if not (shutil.which("javac") and shutil.which("java")):
        if os.environ.get("RUN_DOCKER_TESTS") == "1":
            pytest.fail("javac/java not on PATH: the Docker lane requires a JDK")
        pytest.skip("javac/java not on PATH")


def _compile(workdir: Path, **sources: str) -> None:
    (workdir / "CobolFileIo.java").write_text(COBOL_FILE_IO_JAVA, encoding="utf-8")
    names = ["CobolFileIo.java"]
    for cls, text in sources.items():
        (workdir / f"{cls}.java").write_text(text, encoding="utf-8")
        names.append(f"{cls}.java")
    proc = subprocess.run(["javac", "-nowarn", "-encoding", "UTF-8", "-d", ".", *names],
                          cwd=workdir, capture_output=True, text=True, timeout=180, check=False)
    assert proc.returncode == 0, proc.stderr


def _java(workdir: Path, cls: str, *args: str, heap: str = "-Xmx256m", props: tuple[str, ...] = ()) -> str:
    proc = subprocess.run(
        ["java", heap, "-Dfile.encoding=UTF-8", "-Dline.separator=\n", *props, "-cp", ".", cls, *args],
        cwd=workdir, capture_output=True, text=True, timeout=600, check=False)
    assert proc.returncode == 0, proc.stdout[-500:] + proc.stderr[-1500:]
    return proc.stdout


def test_disk_index_matches_treemap_for_ksds(jdk, tmp_path):
    blob = fixed_export(ksds_records(9000))
    idx = tmp_path / "ks.dat.idx"
    migrate_export(write_export(tmp_path, blob), make_manifest(blob, 9000), idx)
    _compile(tmp_path, Diff=DIFF_JAVA)
    assert _java(tmp_path, "Diff", str(idx), "idx").startswith("OK ")


def test_disk_index_matches_treemap_for_rrds(jdk, tmp_path):
    slots = [(n, f"R{n:09d}".encode()) for n in range(1, 30000, 3)]
    blob = rrds_export(slots)
    rel = tmp_path / "rs.dat.rel"
    migrate_export(write_export(tmp_path, blob), make_manifest(blob, len(slots), organization="RRDS"), rel)
    _compile(tmp_path, Diff=DIFF_JAVA)
    assert _java(tmp_path, "Diff", str(rel), "rel").startswith("OK ")


def test_dataset_far_larger_than_the_java_heap_can_be_scanned(jdk, tmp_path):
    total = 1_500_000  # 150 MB of records, about 165 MB of .idx
    pad = b"X" * 86
    blob_path = tmp_path / "export.dat"
    import hashlib
    h = hashlib.sha256()
    with blob_path.open("wb") as f:
        for start in range(1, total + 1, 50_000):
            chunk = b"".join(b"%08d" % i + b"REC%03d" % (i % 1000) + pad
                             for i in range(start, min(start + 50_000, total + 1)))
            f.write(chunk)
            h.update(chunk)
    manifest = make_manifest(b"", total, min_len=100, max_len=100, key_length=8).model_copy(
        update={"dataset_bytes": blob_path.stat().st_size, "sha256": h.hexdigest()})
    migrate_export(blob_path, manifest, tmp_path / "big.dat.idx")
    blob_path.unlink()
    assert (tmp_path / "big.dat.idx").stat().st_size > 150_000_000
    _compile(tmp_path, Scan=SCAN_JAVA)
    # 48 MB heap: the in-memory map for this image needs several hundred MB.
    assert _java(tmp_path, "Scan", str(total), heap="-Xmx48m").strip() == f"SCAN {total}"
    assert (tmp_path / "big.dat.idx").stat().st_size > 150_000_000  # INPUT never rewrote it
