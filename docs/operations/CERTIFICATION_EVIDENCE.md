# Stage 1 VSAM Streaming Benchmark Evidence

All numbers below were measured on 2026-11-14 by `scripts/perf/vsam_benchmark.py`
and copied from the JSON files it wrote to `test-artifacts/benchmarks/` (git-ignored).
Nothing here is estimated.

Host: Windows 11, Python 3.11.9, 15.7 GB RAM, local NVMe disk, single process.
Workload: KSDS export, 100-byte fixed records, 10-digit keys at offset 0.
Peak memory is the process peak working set read from the OS (`K32GetProcessMemoryInfo`).

| Dataset | Records | Input bytes | Output bytes | Seconds | Records/s | MiB/s | Peak memory (MiB) |
|---|---|---|---|---|---|---|---|
| 16 MiB | 167,772 | 16,777,200 | 17,112,748 | 1.25 | 133,893 | 12.8 | 32.5 |
| 128 MiB | 1,342,177 | 134,217,700 | 136,902,058 | 7.90 | 169,916 | 16.2 | 32.3 |
| 1 GiB | 10,737,418 | 1,073,741,800 | 1,095,216,640 | 70.74 | 151,785 | 14.5 | 32.8 |
| 10 GiB | 107,374,182 | 10,737,418,200 | 10,952,166,568 | 608.63 | 176,418 | 16.8 | 33.3 |

Peak memory stays at about 33 MiB from 16 MiB to 10 GiB of input, so memory does not grow with input size.
Throughput varied between runs because other processes were using the CPU at the same time.

## Interrupt and resume (1 GiB)

The migration was interrupted at record 5,368,709 and resumed from the last checkpoint at record 5,250,000.

| Run | Input SHA-256 | Output SHA-256 |
|---|---|---|
| Uninterrupted | `a7c7f79fd131e4247b621ba911f1941adfc94e7733339c2725a4a3062b010877` | `cc23087ebf29cdb4fd098a065bd3499fa00f9481a216ed293e7893034147b76d` |
| Interrupted, then resumed | `a7c7f79fd131e4247b621ba911f1941adfc94e7733339c2725a4a3062b010877` | `cc23087ebf29cdb4fd098a065bd3499fa00f9481a216ed293e7893034147b76d` |

Both hashes are identical, so resuming produced a byte-identical artifact. The resumed leg peaked at 33.2 MiB.

## 10 GiB hashes

- Input SHA-256: `a4772bb112545d01c6cc6ce083002b4d4fb15b2b02ece036d0f2428cff21d536`
- Output SHA-256: `b1518b8ba40b0d3c8c4680915fa5f1d99d33459c755f5c43d80e604dde5412c1`

## What this does not show

- It measures the Python migration engine only. The generated Java runtime opens large read-only KSDS/RRDS images through a disk-backed sparse index (tested under a 48 MB heap on a 165 MB file). Small images and any `OUTPUT`, `I-O` or `EXTEND` open still load into memory.
- It was a single local run per size on one Windows host. It is not a multi-node or CI measurement.
- The benchmark does not use real IBM VSAM data. No `IBM_RUNTIME_VERIFIED` claim is made.
- An earlier set of runs used 8-digit keys. The 10 GiB run was refused with `KEYS_OUT_OF_ORDER` because the generator's keys overflowed at record 100,000,000. The generator was fixed to 10 digits and all sizes were rerun. The figures above are from the fixed script.
