"""Roadmap unit 40: the reference driver, the job-lane verdict rules and the JCL ledger entry (hermetic)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from engine.jcl.assembly import JobAssembly
from engine.jcl.job_lane import UNAVAILABLE, verify_job
from engine.jcl.orchestrator import plan_job
from engine.jcl.reference import ReferenceUnavailable, render_reference
from engine.modernization.integrated_proof import ProofState, jcl_ledger_entry
from engine.transformation.jcl_parser import JclParser

CLASSES = {"PROG": "Prog", "OTHER": "Other"}


def _plan(jcl: str):
    app = JclParser().parse_application({"J.jcl": jcl})
    return plan_job(app.jobs[0], CLASSES)


JOB = """//DEMO     JOB CLASS=A
//S1       EXEC PGM=PROG
//OUTDD    DD DSN=A.OUT,DISP=(NEW,CATLG)
//S2       EXEC PGM=OTHER,COND=(4,LT,S1)
//INDD     DD DSN=A.OUT,DISP=SHR
//S3       EXEC PGM=OTHER,COND=(8,LE)
//INDD     DD DSN=&&WORK,DISP=(OLD,DELETE)
"""


def test_the_reference_script_carries_the_job_semantics():
    script = render_reference(_plan(JOB))
    assert "echo \"JCL step S1 RC=$rc\"" in script and "JCL step S2 BYPASSED" in script
    assert "DD_OUTDD=" in script and '"$BIN/PROG"' in script
    assert "dataset A.OUT (DD INDD) not found" in script  # OLD/SHR must exist
    assert "dataset A.OUT (DD OUTDD) already exists" in script  # NEW,CATLG must not
    assert 'holds 4 LT "$RC_0"' in script  # COND with a step name reads that step's code
    assert 'for rc in $ALL; do if holds 8 LE' in script  # COND without a step reads every earlier code
    assert 'echo "JCL job DEMO MAXRC=$MAX"' in script


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX shell")
def test_the_reference_script_is_valid_shell():
    script = render_reference(_plan(JOB))
    assert subprocess.run(["sh", "-n"], input=script.encode(), capture_output=True).returncode == 0


def test_utilities_and_inline_data_render():
    script = render_reference(_plan(
        "//U        JOB CLASS=A\n//C1       EXEC PGM=IEBGENER\n//SYSUT1   DD *\nROW ONE\nROW TWO\n/*\n"
        "//SYSUT2   DD DSN=U.COPY,DISP=(NEW,CATLG)\n//SYSPRINT DD SYSOUT=*\n//B        EXEC PGM=IEFBR14\n"))
    assert "printf '%s" + chr(92) + "n' 'ROW ONE' 'ROW TWO'" in script
    assert 'cp -f "$F_0_0" "$F_0_1"' in script and "rc=12" in script


def test_what_the_reference_cannot_reproduce_is_refused_by_name():
    with pytest.raises(ReferenceUnavailable, match="IDCAMS"):
        render_reference(_plan(
            "//I        JOB CLASS=A\n//S1       EXEC PGM=IDCAMS\n//SYSIN    DD *\n  DELETE A.B\n/*\n"))
    with pytest.raises(ReferenceUnavailable, match="generation data groups"):
        render_reference(_plan(
            "//G        JOB CLASS=A\n//S1       EXEC PGM=PROG\n//OUTDD    DD DSN=A.GDG(+1),DISP=(NEW,CATLG)\n"))
    with pytest.raises(ValueError, match="not runnable"):
        render_reference(_plan("//X        JOB CLASS=A\n//S1       EXEC PGM=NOSUCH\n"))


def test_a_job_without_a_runner_is_unavailable_never_verified(tmp_path):
    result = verify_job(
        JobAssembly(job="DEMO", runner_class="", refusals=("IF/THEN/ELSE blocks are not evaluated",)),
        _plan(JOB), source_dir=tmp_path, project_dir=tmp_path)
    assert result.verdict == UNAVAILABLE and "no runner was generated" in result.reasons[0]


def test_the_jcl_ledger_entry_is_proven_only_with_every_job_verified():
    verified = ({"job": "A", "verdict": "VERIFIED"}, {"job": "B", "verdict": "VERIFIED"})
    entry = jcl_ledger_entry("FULL", verified)
    assert entry.proof_state is ProofState.PROVEN and "not an IBM JES result" in entry.reason
    assert jcl_ledger_entry("FULL", verified + ({"job": "C", "verdict": "UNAVAILABLE"},)).proof_state is ProofState.PARTIAL
    assert jcl_ledger_entry("FULL", ({"job": "A", "verdict": "MISMATCH"},)).proof_state is ProofState.PARTIAL
    assert jcl_ledger_entry("FULL").proof_state is ProofState.PARTIAL
    assert jcl_ledger_entry("PARTIAL", verified).proof_state is ProofState.BLOCKED



def test_container_scripts_run_under_a_permissive_umask(monkeypatch, tmp_path):
    """Files the container user creates in the staging tree must stay removable by the host user (CI run 42778068175)."""
    from engine.jcl import job_lane

    seen: list[str] = []
    monkeypatch.setattr(job_lane, "run_container", lambda command, **kw: seen.append(command[-1]))
    job_lane._run("img", tmp_path, "mkdir -p /w/bin && true", lane="oracle", name="n", seconds=1)
    assert seen == [job_lane.CONTAINER_UMASK_PREFIX + "mkdir -p /w/bin && true"]
    assert job_lane.CONTAINER_UMASK_PREFIX.startswith("umask 000")
