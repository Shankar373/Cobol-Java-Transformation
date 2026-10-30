# WSL / CI Failure Root Cause

Date: 2026-10-30
SHA: `92c51e52629f7dcb8b9dce18f412bd957897f6eb`
Affected test: `tests/test_ci_deployment_security.py::TestVerifyProductionPropagatesProbeFailure::test_fixed_idiom_propagates_grep_status`

## 1. Reproduction

Native Windows invocation of the test:

```text
python -m pytest tests/test_ci_deployment_security.py::...::test_fixed_idiom_propagates_grep_status -q
```

Result: 1 failed, 1 passed.

Failing case:
`echo nope | grep -q probe` expected to fail (`expect_fail=True`), but
`subprocess.run(["bash", "-c", script])` returned exit code 0.

Direct diagnostic:

```text
python -c "import subprocess; r=subprocess.run(['bash','-c','echo nope | grep -q probe; echo status=$?'], ...)"
# stdout: status=True
```

## 2. Root cause

The failure is **environment/launcher-specific**, not a security regression.

On this Windows host, `bash` resolves to:

`C:\Windows\System32\bash.exe` (Microsoft Bash Launcher / WSL launcher).

When invoked as `bash -c '...'`, the launcher does not preserve normal GNU Bash
semantics for `$?` and `$BASH_VERSION`; observed output is `status=True` and
`$BASH_VERSION` is empty. This is an interop/launcher artifact of invoking
WSL through the `bash.exe` shim.

The same command executed through the actual WSL GNU Bash works correctly:

```text
wsl.exe -e bash -c 'echo nope | grep -q probe; echo status=$?'
# status=1
```

Likewise, running the test's script from a file through `wsl` returns the
expected exit code 1.

The production script under test
(`scripts/deploy/verify-production.sh`) and workflow
(`.github/workflows/supply-chain.yml`) were not changed by this investigation.

## 3. Classification

- Shell portability: **Yes** (Windows `bash.exe` shim vs. real GNU Bash).
- Environment variables: No.
- File permissions: No.
- Path conversion: Contributing factor (WSL launcher path/command translation).
- Docker availability: No.
- Test assumptions: The test assumes `bash` on PATH is a POSIX Bash; that is
  true on Linux CI but not on this Windows/WSL interop host.
- Actual security regression: **No**. The BL-143/BL-144 source-level assertions
  pass.

## 4. Linux CI expectation

On GitHub Actions Linux runners, `bash` is GNU Bash and the test passes. No
source fix is required for CI. The local Windows failure should be treated as
an environment caveat, not as a blocker, and should be documented in CI notes.

## 5. Recommended action

1. Keep the test unchanged for Linux CI.
2. In local Windows validation, invoke tests that require real Bash through
   `wsl.exe -e bash` or a Linux container.
3. If cross-platform local validation is required, add a helper that selects
   `wsl.exe -e bash` on Windows and `bash` elsewhere, without changing the
   assertions.
4. Do not suppress or weaken the BL-143/BL-144 assertions.
