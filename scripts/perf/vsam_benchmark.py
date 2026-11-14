"""Benchmark the streaming VSAM migration at a chosen size.

Generates a deterministic KSDS export as a stream (never held in memory),
migrates it, and records wall time, throughput, peak memory and the output
SHA-256. Run each size in its own process so peak memory is comparable:

    python scripts/perf/vsam_benchmark.py --mib 64 --work /tmp/bench
    python scripts/perf/vsam_benchmark.py --mib 1024 --work /tmp/bench --interrupt-resume

Results are written to ``test-artifacts/benchmarks/vsam-<mib>MiB.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from enterprise.contracts import VsamExportManifest, VsamRecordLayout  # noqa: E402
from enterprise.quotas import VsamQuotas  # noqa: E402
from enterprise.vsam import VsamRefusal, migrate_export  # noqa: E402

RECORD_BYTES = 100
KEY_BYTES = 8
MIB = 1024 * 1024


def peak_memory_bytes() -> int:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return int(counters.PeakWorkingSetSize)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def generate(path: Path, records: int) -> str:
    h = hashlib.sha256()
    pad = b"X" * (RECORD_BYTES - KEY_BYTES - 6)
    with path.open("wb") as f:
        batch = []
        for i in range(1, records + 1):
            batch.append(b"%08d" % i + b"REC%03d" % (i % 1000) + pad)
            if len(batch) == 8192:
                block = b"".join(batch)
                f.write(block)
                h.update(block)
                batch.clear()
        if batch:
            block = b"".join(batch)
            f.write(block)
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mib", type=int, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--interrupt-resume", action="store_true")
    args = parser.parse_args()

    records = args.mib * MIB // RECORD_BYTES
    args.work.mkdir(parents=True, exist_ok=True)
    src, out = args.work / f"export-{args.mib}.dat", args.work / f"out-{args.mib}.idx"
    for stale in (out, out.with_name(out.name + ".part"), out.with_name(out.name + ".ckpt")):
        stale.unlink(missing_ok=True)

    started = time.perf_counter()
    digest = generate(src, records)
    generate_seconds = time.perf_counter() - started
    manifest = VsamExportManifest(
        dataset_name="BENCH.KSDS", organization="KSDS",
        layout=VsamRecordLayout(record_format="FIXED", min_record_length=RECORD_BYTES,
                                max_record_length=RECORD_BYTES, key_length=KEY_BYTES, code_page="ascii"),
        record_count=records, dataset_bytes=src.stat().st_size, sha256=digest)
    quotas = VsamQuotas()
    result_note = {}

    if args.interrupt_resume:
        try:
            migrate_export(src, manifest, out, quotas=quotas, checkpoint_every=250_000,
                           stop_after_records=records // 2)
        except KeyboardInterrupt:
            result_note["interrupted_at_records"] = records // 2

    started = time.perf_counter()
    try:
        result = migrate_export(src, manifest, out, quotas=quotas, checkpoint_every=250_000)
    except VsamRefusal as refusal:
        print(f"REFUSED {refusal}")
        return 1
    seconds = time.perf_counter() - started

    report = {
        "dataset_mib": args.mib, "records": result.records, "input_bytes": result.input_bytes,
        "output_bytes": result.output_bytes, "migrate_seconds": round(seconds, 2),
        "records_per_second": int(result.records / seconds), "mib_per_second": round(args.mib / seconds, 1),
        "peak_memory_mib": round(peak_memory_bytes() / MIB, 1),
        "resumed_from_records": result.resumed_from_records,
        "input_sha256": result.input_sha256, "output_sha256": result.output_sha256,
        "generate_seconds": round(generate_seconds, 2), "platform": sys.platform,
        "python": sys.version.split()[0], **result_note,
    }
    target = Path("test-artifacts/benchmarks")
    target.mkdir(parents=True, exist_ok=True)
    suffix = "-resume" if args.interrupt_resume else ""
    (target / f"vsam-{args.mib}MiB{suffix}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if os.environ.get("BENCH_CLEANUP"):
        shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
