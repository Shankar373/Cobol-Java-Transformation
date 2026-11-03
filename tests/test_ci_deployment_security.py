"""CI/deployment security gates (BL-143, BL-144).

Two shell-masking defects let failures report as success:

* **BL-143** — `.github/workflows/supply-chain.yml` pipes audit tools
  into ``tee`` without ``set -o pipefail``.  GitHub's default Linux
  ``run`` shell is ``bash -e`` (no ``pipefail``), so the step's exit
  status is ``tee``'s (always 0): ``pip-audit``/``npm audit`` findings
  can never fail the workflow — the documented supply-chain gate is
  advisory-only.  ``ci.yml`` already sets ``pipefail`` everywhere it
  pipes; the supply-chain workflow must match.

* **BL-144** — ``scripts/deploy/verify-production.sh`` runs its
  visibility probe as ``bash -c "... | grep -q probe; rm -f ..."``:
  the ``; rm -f`` is the *last* command, so ``bash -c`` exits with
  ``rm``'s status (0) even when ``grep`` fails — ``check()`` records
  PASS for a probe that failed (false PASS on the production gate).

These tests are red-first: they fail on the unfixed files.

Note on ``shell: bash``: GitHub's *explicit* ``shell: bash`` runs
``bash --noprofile --norc -eo pipefail``, but the *default* (no shell
key) does not — a workflow cannot rely on the default.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
SUPPLY_CHAIN = REPO / ".github" / "workflows" / "supply-chain.yml"
VERIFY_PROD = REPO / "scripts" / "deploy" / "verify-production.sh"


def _run_blocks(workflow: dict) -> list[str]:
    """Every ``run`` script string in a parsed workflow."""
    blocks: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        steps = job.get("steps") or []
        for step in steps:
            run = step.get("run")
            if isinstance(run, str):
                blocks.append(run)
    return blocks


def _explicit_shell_bash(job: dict) -> bool:
    """True when the job forces GitHub's pipefail shell for all runs."""
    return ((job.get("defaults") or {}).get("run") or {}).get("shell") == "bash"


class TestSupplyChainPipesFailClosed:
    def test_workflow_parses(self):
        workflow = yaml.safe_load(SUPPLY_CHAIN.read_text(encoding="utf-8"))
        assert isinstance(workflow, dict)
        assert "jobs" in workflow

    def test_every_tee_piped_run_sets_pipefail(self):
        """BL-143: a ``| tee`` step without pipefail can never fail."""
        workflow = yaml.safe_load(SUPPLY_CHAIN.read_text(encoding="utf-8"))
        offenders: list[str] = []
        for job_name, job in (workflow.get("jobs") or {}).items():
            if _explicit_shell_bash(job):
                continue  # GitHub's explicit bash shell has pipefail
            for step in job.get("steps") or []:
                run = step.get("run")
                if not isinstance(run, str):
                    continue
                if "| tee" not in run and "|tee" not in run:
                    continue
                if "set -o pipefail" not in run and "set -euo pipefail" not in run:
                    name = step.get("name", "<unnamed>")
                    offenders.append(f"{job_name}/{name}")
        assert not offenders, (
            "BL-143: supply-chain steps pipe into tee without pipefail —"
            f" audit failures are masked: {offenders}"
        )

    def test_pipefail_precedes_the_piped_command(self):
        """pipefail must be set *before* the pipeline runs in the block."""
        workflow = yaml.safe_load(SUPPLY_CHAIN.read_text(encoding="utf-8"))
        for job in (workflow.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                run = step.get("run")
                if not isinstance(run, str) or "| tee" not in run:
                    continue
                if "set -o pipefail" not in run and "set -euo pipefail" not in run:
                    continue
                pipefail_at = min(
                    run.find("set -o pipefail"), run.find("set -euo pipefail")
                )
                assert pipefail_at < run.find("| tee"), (
                    "BL-143: pipefail must be set before the piped command"
                )


class TestVerifyProductionPropagatesProbeFailure:
    @staticmethod
    def _executable_lines(text: str) -> list[str]:
        return [
            line for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_script_has_no_status_masking_cleanup(self):
        """BL-144: ``...; rm -f`` as the last command of a probe always
        exits 0 — the check() wrapper then records a false PASS.

        Comments are ignored; any executable line that pipes a probe into
        ``rm -f`` cleanup must capture the status first (``rc=$?``).
        """
        text = VERIFY_PROD.read_text(encoding="utf-8")
        for line in self._executable_lines(text):
            if "rm -f" not in line:
                continue
            if not ("grep" in line or "/probe" in line or "docker run" in line):
                continue
            assert (
                "rc=$?" in line
                or "rc=\\$?" in line
                or "status=$?" in line
                or "status=\\$?" in line
            ), (
                "BL-144: a probe line cleans up with `rm -f` without first"
                f" capturing the pipe status: {line.strip()!r}"
            )

    def test_probe_cleanup_captures_and_restores_status(self):
        """Any cleanup after the piped visibility probe must re-raise its
        status so check() sees the real grep result."""
        text = VERIFY_PROD.read_text(encoding="utf-8")
        for line in self._executable_lines(text):
            if "grep -q probe" in line:
                assert "exit $rc" in line or "exit $status" in line or (
                    "rc=$?" in line and line.strip().endswith('exit \\$rc"')
                ) or "rc=\\$?" in line, (
                    "BL-144: the visibility probe must capture the pipe"
                    f" status and exit with it: {line.strip()!r}"
                )
                break
        else:
            pytest.fail("visibility probe line not found in script")

    @pytest.mark.parametrize(
        "probe_cmd,expect_fail",
        [
            ("echo probe | grep -q probe", False),
            ("echo nope | grep -q probe", True),
        ],
    )
    def test_fixed_idiom_propagates_grep_status(self, probe_cmd, expect_fail):
        """Behavioural proof that the replacement idiom cannot mask."""
        script = (
            f'{probe_cmd}; rc=$?; touch /tmp/.bl144-probe;'
            " rm -f /tmp/.bl144-probe; exit $rc"
        )
        proc = subprocess.run(["bash", "-c", script], capture_output=True)
        assert (proc.returncode != 0) is expect_fail

    @pytest.mark.parametrize("probe_cmd", ["false | grep -q probe"])
    def test_old_idiom_masks_failure(self, probe_cmd):
        """Documents WHY the old pattern was a defect (red evidence)."""
        script = f'{probe_cmd}; rm -f /tmp/.bl144-never-there'
        proc = subprocess.run(["bash", "-c", script], capture_output=True)
        assert proc.returncode == 0, (
            "expected the old `; rm` tail to mask the failure"
        )