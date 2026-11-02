"""Independent re-check of VERIFIED end-to-end apps.

Usage (Docker required)::

    E2E_IN=out.jsonl VERIFY_OUT=verify.jsonl [VERIFY_APPS=a,b] \
        python scripts/e2e/verify_independent.py

Shares no code with the platform's adapters or comparators.  For every
VERIFIED app in $E2E_IN:

* GnuCOBOL: copy ``fixtures/<app>/cobol`` to a scratch dir, ``cobc -x`` the
  entry module plus every other module (entry = the single program no other
  module CALLs, resolved here by its own regex), run it in an empty working
  directory;
* Java: copy the generated project, ``mvn -o package`` in the offline Maven
  image, run ``java -jar`` in an empty working directory.

Both runs collect stdout, stderr, exit code and EVERY file left anywhere in
their working directory; the record is AGREE only when all of them are
identical.  Results go to $VERIFY_OUT.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

RESULTS = Path(os.environ.get("E2E_IN", "e2e_results.jsonl")).resolve()
OUT = Path(os.environ.get("VERIFY_OUT", "verify_results.jsonl")).resolve()
REPO = Path(__file__).resolve().parents[2]
ORACLE = "gnucobol-ocesql:latest"
MAVEN = "maven-offline-springboot:latest"
JRE = "eclipse-temurin:21-jdk"


#: Sandbox flags for every container this script starts (its own copy: the
#: script shares no code with the platform).  The programs are untrusted.
HARDENING = ["--security-opt", "no-new-privileges=true", "--cap-drop", "ALL",
             "--user", "10001:10001", "--network", "none",
             "--memory", "1g", "--cpus", "2", "--pids-limit", "512",
             "--ulimit", "fsize=134217728"]


def docker(args, stdin=b"", timeout=600):
    """``docker run --rm`` with the sandbox flags; removed on timeout."""
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    name = f"verify-{uuid.uuid4().hex[:12]}"
    try:
        return subprocess.run(
            ["docker", "run", "--rm", "--name", name, *HARDENING, *args],
            input=stdin, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, env=env)
        raise


def entry_module(cobol_dir: Path) -> tuple[str, list[str]]:
    mods = sorted(f.name for f in cobol_dir.iterdir()
                  if f.is_file() and f.suffix.lower() in (".cob", ".cbl"))
    pid = {}
    called = set()
    for m in mods:
        t = (cobol_dir / m).read_text(encoding="utf-8", errors="ignore")
        g = re.search(r"PROGRAM-ID\.\s*([A-Za-z0-9][\w-]*)", t, re.I)
        pid[m] = g.group(1).upper() if g else ""
        called |= {c.upper() for c in re.findall(r"CALL\s+['\"]([\w-]+)['\"]", t, re.I)}
    roots = [m for m in mods if pid[m] not in called]
    if len(roots) != 1:
        raise RuntimeError(f"no unique entry: {roots}")
    return roots[0], [m for m in mods if m != roots[0]]


def is_free(text: str) -> bool:
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip() or line[:1] in "*/" or (len(line) > 6 and line[6] in "*/"):
            continue
        if any(ch not in "0123456789 " for ch in line[:6]):
            return True
    return False


def _bdb_records(image: bytes) -> list[bytes] | None:
    """Records of a Berkeley DB B-tree (GnuCOBOL INDEXED file), or None.

    Deliberately not the platform's algorithm: every leaf page is scanned
    linearly and the live key/data pairs are sorted by key, instead of
    walking the tree from its root.  Anything but plain items -> None.
    """
    if len(image) < 512 or image[12:16] != b"\x62\x31\x05\x00":
        return None
    size = int.from_bytes(image[20:24], "little")
    if size < 512 or len(image) % size:
        return None
    pairs = []
    for start in range(size, len(image), size):
        page = image[start:start + size]
        if page[25] != 5:  # leaf
            continue
        count = int.from_bytes(page[20:22], "little")
        offs = [int.from_bytes(page[26 + 2 * i:28 + 2 * i], "little") for i in range(count)]
        for k, d in zip(offs[::2], offs[1::2]):
            if page[k + 2] & 0x80 or page[d + 2] & 0x80:
                continue  # deleted
            if page[k + 2] != 1 or page[d + 2] != 1:
                return None
            key = page[k + 3:k + 3 + int.from_bytes(page[k:k + 2], "little")]
            data = page[d + 3:d + 3 + int.from_bytes(page[d:d + 2], "little")]
            pairs.append((key, data))
    return [data for _, data in sorted(pairs)]


def _emulated_records(image: bytes) -> list[bytes] | None:
    """Records of the generated Java INDEXED emulation, or None."""
    lines = image.split(b"\n")
    if not re.fullmatch(rb"K\d+", lines[0]) or lines[-1] != b"":
        return None
    return [line.replace(b"\x01", b"", 1) for line in lines[1:-1]]


def _relative_records(image: bytes) -> list[bytes] | None:
    """``b"<rrn>:" + record`` per live slot of a GnuCOBOL RELATIVE file, or None.

    Not the platform's algorithm: every slot layout is unpacked with
    ``struct.iter_unpack`` and kept only if each slot is empty or exactly
    full; exactly one layout must survive with a live slot.
    """
    found = []
    for length in range(1, len(image)):
        if len(image) % (8 + length):
            continue
        slots = list(struct.iter_unpack(f"<Q{length}s", image))
        if all(size in (0, length) for size, _ in slots) and any(slots[i][0] for i in range(len(slots))):
            found.append([b"%d:" % (i + 1) + data for i, (size, data) in enumerate(slots) if size])
    return found[0] if len(found) == 1 else None


def _emulated_relative(image: bytes) -> list[bytes] | None:
    """``b"<rrn>:" + record`` of the generated Java RELATIVE emulation, or None."""
    lines = image.split(b"\n")
    if lines[0] != b"R" or lines[-1] != b"":
        return None
    return [line.replace(b"\x01", b":", 1) for line in lines[1:-1]]


def relative_files(cobol_dir: Path) -> frozenset[str]:
    """Upper-case ASSIGN literals of the RELATIVE SELECTs in the sources."""
    names = set()
    for f in cobol_dir.iterdir():
        if f.suffix.lower() not in (".cob", ".cbl"):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"SELECT\s.*?ASSIGN\s+(?:TO\s+)?['\"]([^'\"]+)['\"](.*?)\.(?:\s|$)",
                             text, re.I | re.S):
            if re.search(r"ORGANI[SZ]ATION\s+(?:IS\s+)?RELATIVE", m.group(2), re.I):
                names.add(m.group(1).upper())
    return frozenset(names)


def snapshot(root: Path, decoded: dict | None = None,
             relative: frozenset[str] = frozenset()) -> dict[str, str]:
    """Hash of every file; an INDEXED or RELATIVE file is represented by its
    records (GnuCOBOL's image ``X`` and the Java emulation ``X.idx`` /
    ``X.rel`` all become ``X#records``), since the physical formats differ;
    ``relative`` names the oracle files declared RELATIVE.  The decoded
    records (hex) go to ``decoded`` when given, as evidence."""
    out = {}
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        name, data = f.relative_to(root).as_posix(), f.read_bytes()
        records = _bdb_records(data)
        if records is None and name.endswith(".idx"):
            records = _emulated_records(data)
            name = name[:-4] if records is not None else name
        elif records is None and name.endswith(".rel"):
            records = _emulated_relative(data)
            name = name[:-4] if records is not None else name
        elif records is None and (
            name.upper() in relative or name.rsplit("/", 1)[-1].upper() in
            {r.rsplit("/", 1)[-1] for r in relative}
        ):
            records = _relative_records(data)
        if records is not None:
            name, data = name + "#records", b"\n".join(r.hex().encode() for r in records)
            if decoded is not None:
                decoded[name] = [r.hex() for r in records]
        out[name] = hashlib.sha256(data).hexdigest()
    return out


def run_cobol(cobol_dir: Path, work: Path) -> dict:
    entry, others = entry_module(cobol_dir)
    src = work / "src"
    shutil.copytree(cobol_dir, src)
    run = work / "run"
    (run / "output").mkdir(parents=True)
    free = all(is_free((cobol_dir / m).read_text(encoding="utf-8", errors="ignore"))
               for m in [entry, *others])
    flag = "-free " if free else ""
    units = " ".join(shlex.quote(u) for u in [entry, *others])
    script = (f"cd /src && cobc -x {flag}{units} -o /tmp/p >/dev/null 2>/tmp/cerr; "
              "rc=$?; if [ $rc -ne 0 ]; then cat /tmp/cerr >&2; exit 97; fi; "
              "cd /workspace && /tmp/p")
    for d in (run, run / "output"):
        os.chmod(d, 0o777)  # writable by the container's non-root user
    p = docker(["-i", "-e", "HOME=/tmp",
                "-v", f"{src.as_posix()}:/src:ro", "-v", f"{run.as_posix()}:/workspace",
                "--workdir", "/workspace", ORACLE, "sh", "-c", script])
    records: dict = {}
    return {"stdout": p.stdout, "stderr": p.stderr, "exit": p.returncode,
            "files": snapshot(run, records, relative_files(cobol_dir)),
            "records": records}


def run_java(project: Path, work: Path) -> dict:
    proj = work / "proj"
    shutil.copytree(project, proj, ignore=shutil.ignore_patterns("target"))
    jars = work / "jars"
    jars.mkdir()
    for d in [proj, jars, *[x for x in proj.rglob("*") if x.is_dir()]]:
        os.chmod(d, 0o777)  # Maven runs as the non-root sandbox user
    b = docker(["-e", "HOME=/tmp",
                "-v", f"{proj.as_posix()}:/p", "-v", f"{jars.as_posix()}:/out",
                "--workdir", "/p", MAVEN, "sh", "-c",
                "mvn -o -B -q -Dmaven.test.skip=true package && cp target/*.jar /out/"],
               timeout=900)
    if b.returncode != 0:
        return {"build_error": (b.stdout + b.stderr)[-1500:].decode(errors="replace")}
    jar = next(jars.glob("*.jar")).name
    run = work / "jrun"
    (run / "output").mkdir(parents=True)
    for d in (run, run / "output"):
        os.chmod(d, 0o777)
    p = docker(["-i", "-e", "HOME=/tmp",
                "-v", f"{run.as_posix()}:/workspace", "-v", f"{jars.as_posix()}:/jars:ro",
                "--workdir", "/workspace", JRE, "sh", "-c",
                f"java -jar {shlex.quote('/jars/' + jar)}"])
    records: dict = {}
    return {"stdout": p.stdout, "stderr": p.stderr, "exit": p.returncode,
            "files": snapshot(run, records), "records": records}


def _summary(side: dict) -> dict:
    return {"stdout": side["stdout"].decode(errors="replace")[:600],
            "stderr": side["stderr"].decode(errors="replace")[:300],
            "exit": side["exit"], "files": side["files"], "records": side["records"]}


def _release(work: Path) -> None:
    """Remove a work tree, best effort; never raises.

    The sandbox user (uid 10001) owns what its containers created (Maven's
    target/, program output). On a Linux host the invoking user may not be
    able to delete those, which crashed the run in CI (2026-11-02, twice).
    The same uid, in a hardened container, deletes what it owns first; any
    remainder is left in the temporary directory - cleanup can never abort
    a re-check, and no evidence depends on it.
    """
    if work.is_dir() and any(work.iterdir()):
        p = docker(["-v", f"{work.as_posix()}:/w", JRE, "sh", "-c",
                    "chmod -R a+rwX /w; find /w -mindepth 1 -delete"], timeout=300)
        if p.returncode != 0:
            print(f"cleanup container exit {p.returncode}: "
                  f"{p.stderr.decode(errors='replace')[-300:]}", file=sys.stderr)
    shutil.rmtree(work, ignore_errors=True)


def main() -> None:
    done = set()
    if OUT.exists():
        done = {json.loads(line)["app"] for line in OUT.read_text().splitlines() if line.strip()}
    wanted = [s for s in os.environ.get("VERIFY_APPS", "").split(",") if s]
    for line in RESULTS.read_text().splitlines():
        r = json.loads(line)
        app = r["app"]
        if r.get("verdict") != "VERIFIED" or app in done or (wanted and app not in wanted):
            continue
        rec = {"app": app}
        tmp = tempfile.mkdtemp()
        try:
            o = run_cobol(REPO / "fixtures" / app / "cobol", Path(tmp))
            j = run_java(Path(r["generated_app_path"]), Path(tmp))
            if "build_error" in j:
                rec["verdict"] = "JAVA_BUILD_ERROR"
                rec["detail"] = j["build_error"]
            else:
                diffs = [k for k in ("stdout", "stderr", "exit", "files") if o[k] != j[k]]
                rec["verdict"] = "AGREE" if not diffs else "DISAGREE"
                rec["diffs"] = diffs
                rec["oracle"] = _summary(o)
                rec["java"] = _summary(j)
        except Exception as exc:  # noqa: BLE001
            rec["verdict"] = "HARNESS_ERROR"
            rec["detail"] = repr(exc)[:500]
        finally:
            _release(Path(tmp))
        with OUT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(app, rec["verdict"], rec.get("diffs", ""), flush=True)


if __name__ == "__main__":
    sys.exit(main())
