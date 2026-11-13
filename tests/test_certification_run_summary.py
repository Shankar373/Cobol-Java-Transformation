"""G-25: each certification run emits its own machine-checked summary, bound to trusted run identity.

``tools/certification_run_summary.py`` aggregates the four runtime artifacts of one workflow
run.  Identity comes from the workflow environment (``GITHUB_SHA``, ``GITHUB_RUN_ID``), never
from a typed argument; every runtime must have uploaded complete, consistent evidence for the
same commit, the same fixture manifest and the expected application set.

The artifact trees here are synthetic but built from the real committed evidence, then broken
one way at a time.  Dependency-free (pytest only).
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from tools import certification_run_summary as crs
from tools import certification_summary as cs

REPO = cs.REPO
SHA = "a" * 40
RUN_ID = "4242"
ENV = {"GITHUB_SHA": SHA, "GITHUB_RUN_ID": RUN_ID, "GITHUB_RUN_NUMBER": "17", "GITHUB_RUN_ATTEMPT": "1",
       "GITHUB_WORKFLOW": "Corpus certification (GnuCOBOL, all runtimes)",
       "GITHUB_REPOSITORY": "Shankar373/Cobol-Java-Transformation"}
PROVENANCE = {
    "build_identity": "maven-offline-springboot@sha256:" + "1" * 64, "build_image_id": "sha256:" + "1" * 64,
    "runtime_identity": "eclipse-temurin@sha256:" + "2" * 64, "runtime_image_id": "sha256:" + "2" * 64,
    "runtime_image": "eclipse-temurin:21-jdk", "build_image": "maven-offline-springboot:latest",
}
ORACLE = {"image": "gnucobol-ocesql:latest", "id": "sha256:" + "3" * 64}


@pytest.fixture(scope="module")
def manifest() -> dict:
    apps = [r["app"] for r in cs._load(REPO / cs.CORPUS_DIR / "runtime_corpus_plain_java.jsonl")]
    return cs.fixture_manifest(REPO, apps)


def make_artifacts(root: Path, manifest: dict, env: dict = ENV) -> Path:
    for runtime in cs.RUNTIMES:
        d = root / f"certification-{runtime}"
        (d / "evidence").mkdir(parents=True)
        (d / "provenance").mkdir()
        corpus = REPO / cs.CORPUS_DIR
        shutil.copy(corpus / f"runtime_corpus_{runtime}.jsonl", d / "evidence" / f"certification_corpus_{runtime}.jsonl")
        shutil.copy(corpus / f"runtime_corpus_{runtime}_independent.jsonl",
                    d / "evidence" / f"certification_corpus_{runtime}_independent.jsonl")
        shutil.copy(REPO / cs.SUMMARIES_DIR / f"validation_summaries_{runtime}.jsonl",
                    d / "evidence" / f"validation_summaries_{runtime}.jsonl")
        shutil.copy(corpus / f"runtime_corpus_{runtime}.jsonl", d / "e2e.jsonl")
        shutil.copy(corpus / f"runtime_corpus_{runtime}_independent.jsonl", d / "independent.jsonl")
        (d / "summary.txt").write_text(f"{runtime}: 55 apps; independent AGREE 45/45; CERTIFIED\n", encoding="utf-8")
        (d / "provenance" / "docker-image-provenance.json").write_text(json.dumps(PROVENANCE), encoding="utf-8")
        (d / "oracle_image.json").write_text(json.dumps(ORACLE), encoding="utf-8")
        (d / "run_identity.json").write_text(json.dumps({
            "runtime": runtime, "commit_sha": env["GITHUB_SHA"], "run_id": env["GITHUB_RUN_ID"],
            "run_attempt": env["GITHUB_RUN_ATTEMPT"], "fixture_manifest": manifest}), encoding="utf-8")
    return root


def rewrite_jsonl(path: Path, edit) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = edit(rows)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")


def build(tmp_path, manifest, env=ENV, mutate=None):
    root = make_artifacts(tmp_path / "artifacts", manifest)
    if mutate:
        mutate(root)
    return crs.build_run_summary(root, env, REPO), root


# --- the good path ---------------------------------------------------------------------------

def test_a_complete_consistent_run_is_certified_with_full_identity(tmp_path, manifest):
    summary, _ = build(tmp_path, manifest)
    assert summary["certified"] is True and summary["problems"] == []
    assert summary["schema"] == crs.SCHEMA and summary["schema_version"] == crs.SCHEMA_VERSION
    assert summary["identity"]["commit_sha"] == SHA and summary["identity"]["run_id"] == RUN_ID
    assert summary["identity"]["run_number"] == "17"
    assert summary["fixtures"]["manifest_sha256"] == manifest["manifest_sha256"]
    assert summary["toolchain_provenance_complete"] is True
    for runtime in cs.RUNTIMES:
        block = summary["runtimes"][runtime]
        assert block["totals"]["verified"] == 45 and block["independent"]["agree"] == 45
        assert block["toolchain"]["oracle_image_id"] == ORACLE["id"]
        assert block["toolchain"]["build_identity"] == PROVENANCE["build_identity"]
        assert block["toolchain"]["runtime_identity"] == PROVENANCE["runtime_identity"]
        assert block["toolchain"]["jdk"].startswith("openjdk version")
        assert len(block["evidence_sha256"]) == 3 and all(len(h) == 64 for h in block["evidence_sha256"].values())


def test_the_summary_is_deterministic_and_verifiable(tmp_path, manifest):
    a, root = build(tmp_path, manifest)
    b = crs.build_run_summary(root, ENV, REPO)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert crs.verify_run_summary(a, root, ENV, REPO) == []


# --- identity comes from the workflow environment only ----------------------------------------------

@pytest.mark.parametrize("env", [
    {}, {"GITHUB_SHA": SHA}, {"GITHUB_RUN_ID": RUN_ID},
    {**ENV, "GITHUB_SHA": "abc"}, {**ENV, "GITHUB_SHA": "A" * 40}, {**ENV, "GITHUB_RUN_ID": "run-1"},
    {k: v for k, v in ENV.items() if k != "GITHUB_RUN_ATTEMPT"}, {**ENV, "GITHUB_RUN_ATTEMPT": "first"},
])
def test_missing_or_malformed_workflow_identity_is_refused(tmp_path, manifest, env):
    root = make_artifacts(tmp_path / "artifacts", manifest)
    with pytest.raises(crs.IdentityError):
        crs.build_run_summary(root, env, REPO)


def test_a_runtime_artifact_for_a_different_commit_is_a_problem(tmp_path, manifest):
    def mutate(root):
        p = root / "certification-quarkus" / "run_identity.json"
        data = json.loads(p.read_text())
        data["commit_sha"] = "b" * 40
        p.write_text(json.dumps(data))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert summary["certified"] is False
    assert any("quarkus" in p and "commit" in p for p in summary["problems"])


def test_a_runtime_artifact_from_a_different_run_is_a_problem(tmp_path, manifest):
    def mutate(root):
        p = root / "certification-micronaut" / "run_identity.json"
        data = json.loads(p.read_text())
        data["run_id"] = "999"
        p.write_text(json.dumps(data))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("micronaut" in p and "run id" in p for p in summary["problems"])


def test_a_runtime_artifact_that_names_another_runtime_is_a_problem(tmp_path, manifest):
    def mutate(root):
        p = root / "certification-quarkus" / "run_identity.json"
        data = json.loads(p.read_text())
        data["runtime"] = "plain_java"
        p.write_text(json.dumps(data))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("quarkus" in p and "runtime" in p for p in summary["problems"])


# --- completeness of the upload --------------------------------------------------------------------------

def test_a_missing_runtime_artifact_is_never_summarised_as_certified(tmp_path, manifest):
    summary, _ = build(tmp_path, manifest, mutate=lambda r: shutil.rmtree(r / "certification-spring_boot"))
    assert not summary["certified"]
    assert any("spring_boot" in p and "artifact is missing" in p for p in summary["problems"])
    assert summary["runtimes"]["spring_boot"] is None


@pytest.mark.parametrize("relative", [
    "summary.txt", "independent.jsonl", "e2e.jsonl", "run_identity.json", "oracle_image.json",
    "provenance/docker-image-provenance.json",
    "evidence/certification_corpus_plain_java.jsonl",
    "evidence/certification_corpus_plain_java_independent.jsonl",
    "evidence/validation_summaries_plain_java.jsonl",
])
def test_a_partial_upload_is_a_problem_naming_the_missing_file(tmp_path, manifest, relative):
    summary, _ = build(tmp_path, manifest, mutate=lambda r: (r / "certification-plain_java" / relative).unlink())
    assert not summary["certified"]
    assert any("plain_java" in p and "partial upload" in p and relative in p for p in summary["problems"])


# --- the runtime result ------------------------------------------------------------------------------------

def test_a_runtime_job_that_did_not_certify_blocks_the_summary(tmp_path, manifest):
    def mutate(root):
        (root / "certification-quarkus" / "summary.txt").write_text(
            "quarkus: 55 apps; independent AGREE 44/45; NOT CERTIFIED\n", encoding="utf-8")
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("quarkus" in p and "did not certify" in p for p in summary["problems"])


def test_an_independent_disagreement_blocks_the_summary(tmp_path, manifest):
    def mutate(root):
        rewrite_jsonl(root / "certification-plain_java" / "evidence" / "certification_corpus_plain_java_independent.jsonl",
                      lambda rows: [{**rows[0], "verdict": "DISAGREE"}, *rows[1:]])
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"]
    assert any("plain_java" in p and "independent" in p for p in summary["problems"])


def test_a_missing_independent_verdict_for_a_verified_app_blocks_the_summary(tmp_path, manifest):
    def mutate(root):
        rewrite_jsonl(root / "certification-micronaut" / "evidence" / "certification_corpus_micronaut_independent.jsonl",
                      lambda rows: rows[1:])
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("micronaut" in p and "independent" in p for p in summary["problems"])


# --- the application set and the fixtures ---------------------------------------------------------------------

def test_a_duplicate_application_row_is_a_problem(tmp_path, manifest):
    def mutate(root):
        rewrite_jsonl(root / "certification-plain_java" / "evidence" / "certification_corpus_plain_java.jsonl",
                      lambda rows: [*rows, rows[0]])
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("plain_java" in p and "duplicate" in p for p in summary["problems"])


def test_a_missing_application_is_a_problem(tmp_path, manifest):
    def mutate(root):
        rewrite_jsonl(root / "certification-spring_boot" / "evidence" / "certification_corpus_spring_boot.jsonl",
                      lambda rows: rows[1:])
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("spring_boot" in p and "application set" in p for p in summary["problems"])


def test_a_verdict_that_differs_from_the_accepted_evidence_is_stale_or_regressed(tmp_path, manifest):
    def mutate(root):
        def edit(rows):
            victim = next(r for r in rows if r.get("verdict") == "VERIFIED")
            victim["verdict"] = "FAILED"
            return rows
        rewrite_jsonl(root / "certification-quarkus" / "evidence" / "certification_corpus_quarkus.jsonl", edit)
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("quarkus" in p and "accepted evidence" in p for p in summary["problems"])


def test_a_fixture_manifest_that_differs_between_runtimes_is_a_problem(tmp_path, manifest):
    def mutate(root):
        p = root / "certification-micronaut" / "run_identity.json"
        data = json.loads(p.read_text())
        data["fixture_manifest"] = {**manifest, "manifest_sha256": "0" * 64}
        p.write_text(json.dumps(data))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("micronaut" in p and "fixture manifest" in p for p in summary["problems"])


def test_a_manifest_that_differs_from_the_checkout_being_certified_is_a_problem(tmp_path, manifest):
    # all four artifacts agree with each other but not with the source tree of this commit
    def mutate(root):
        for runtime in cs.RUNTIMES:
            p = root / f"certification-{runtime}" / "run_identity.json"
            data = json.loads(p.read_text())
            data["fixture_manifest"] = {**manifest, "manifest_sha256": "f" * 64}
            p.write_text(json.dumps(data))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"]
    assert sum("fixture manifest" in p for p in summary["problems"]) == 4


# --- toolchain provenance --------------------------------------------------------------------------------------

def test_missing_image_provenance_fields_are_named_and_provenance_is_not_complete(tmp_path, manifest):
    def mutate(root):
        p = root / "certification-plain_java" / "provenance" / "docker-image-provenance.json"
        data = json.loads(p.read_text())
        del data["runtime_identity"]
        p.write_text(json.dumps(data))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert summary["toolchain_provenance_complete"] is False and not summary["certified"]
    assert any("plain_java" in p and "runtime_identity" in p for p in summary["problems"])


def test_a_missing_oracle_image_identity_is_a_problem(tmp_path, manifest):
    def mutate(root):
        (root / "certification-quarkus" / "oracle_image.json").write_text(json.dumps({"image": "gnucobol-ocesql:latest"}))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("quarkus" in p and "oracle image" in p for p in summary["problems"])


def test_a_missing_jdk_version_is_a_problem(tmp_path, manifest):
    def mutate(root):
        def edit(rows):
            for row in rows:
                (row["validation_summary"].get("compilation", {}) or {}).pop("jdk", None)
            return rows
        rewrite_jsonl(root / "certification-micronaut" / "evidence" / "validation_summaries_micronaut.jsonl", edit)
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("micronaut" in p and "JDK" in p for p in summary["problems"])


# --- the summary document itself ----------------------------------------------------------------------------------

def test_verification_rejects_an_invalid_schema(tmp_path, manifest):
    summary, root = build(tmp_path, manifest)
    for edit in (lambda s: s.__setitem__("schema", "something.else"), lambda s: s.__setitem__("schema_version", 99)):
        broken = copy.deepcopy(summary)
        edit(broken)
        assert crs.verify_run_summary(broken, root, ENV, REPO)


def test_verification_detects_a_tampered_summary_and_stale_artifacts(tmp_path, manifest):
    summary, root = build(tmp_path, manifest)
    tampered = copy.deepcopy(summary)
    tampered["runtimes"]["plain_java"]["totals"]["verified"] = 46
    assert crs.verify_run_summary(tampered, root, ENV, REPO)
    rewrite_jsonl(root / "certification-plain_java" / "evidence" / "validation_summaries_plain_java.jsonl", lambda rows: rows[1:])
    assert crs.verify_run_summary(summary, root, ENV, REPO)


def test_verification_rejects_a_summary_for_another_run(tmp_path, manifest):
    summary, root = build(tmp_path, manifest)
    other = {**ENV, "GITHUB_RUN_ID": "7"}
    assert crs.verify_run_summary(summary, root, other, REPO)


# --- the per-runtime identity file written inside each runtime job ------------------------------------------------------

def test_the_runtime_job_writes_identity_from_its_environment(tmp_path, manifest):
    out = tmp_path / "certification"
    out.mkdir()
    written = crs.write_runtime_identity(out, "quarkus", ENV, REPO)
    stored = json.loads((out / "run_identity.json").read_text())
    assert stored == written
    assert stored["runtime"] == "quarkus" and stored["commit_sha"] == SHA and stored["run_id"] == RUN_ID
    assert stored["fixture_manifest"]["manifest_sha256"] == manifest["manifest_sha256"]
    with pytest.raises(crs.IdentityError):
        crs.write_runtime_identity(out, "quarkus", {}, REPO)
    with pytest.raises(ValueError):
        crs.write_runtime_identity(out, "cobol_dream_runtime", ENV, REPO)


def test_the_command_line_refuses_to_run_without_workflow_identity(tmp_path, manifest, monkeypatch):
    root = make_artifacts(tmp_path / "artifacts", manifest)
    for var in ENV:
        monkeypatch.delenv(var, raising=False)
    assert crs.main(["run-summary", "--artifacts", str(root), "--out", str(tmp_path / "s.json")]) == 2
    assert not (tmp_path / "s.json").exists()


def test_the_command_line_writes_the_summary_and_signals_failure_with_its_exit_code(tmp_path, manifest, monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    good = make_artifacts(tmp_path / "good", manifest)
    out = tmp_path / "good.json"
    assert crs.main(["run-summary", "--artifacts", str(good), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["certified"] is True
    bad = make_artifacts(tmp_path / "bad", manifest)
    shutil.rmtree(bad / "certification-quarkus")
    bad_out = tmp_path / "bad.json"
    assert crs.main(["run-summary", "--artifacts", str(bad), "--out", str(bad_out)]) == 1
    assert json.loads(bad_out.read_text())["certified"] is False  # still written, for diagnosis


# --- the workflow wires it up safely ----------------------------------------------------------------------

WORKFLOW = REPO / ".github" / "workflows" / "certification.yml"


def _workflow() -> dict:
    import yaml  # PyYAML is already a test dependency of the workflow checks

    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_aggregates_after_every_runtime_and_publishes_only_an_artifact():
    wf = _workflow()
    job = wf["jobs"]["summarize"]
    assert job["needs"] == "certify"
    assert "needs.certify.result != 'skipped'" in job["if"]            # absent when certification is skipped by design
    assert wf["permissions"] == {"contents": "read"}                   # no write token anywhere
    assert "permissions" not in job and "permissions" not in wf["jobs"]["certify"]
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "git push" not in text and "git commit" not in text and "contents: write" not in text


def test_every_action_in_the_certification_workflow_is_pinned_to_a_full_sha():
    import re

    for step in (s for job in _workflow()["jobs"].values() for s in job["steps"]):
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def test_identity_is_never_passed_as_an_argument():
    run = [s["run"] for job in _workflow()["jobs"].values() for s in job["steps"] if "run" in s]
    joined = "\n".join(run)
    assert "--commit" not in joined and "--run-id" not in joined and "--sha" not in joined
    assert "certification_run_summary run-summary" in joined and "runtime-identity" in joined
    # identity is read inside the tool from the environment, never interpolated into a command
    assert "GITHUB_SHA" not in joined and "github.sha" not in joined and "github.run_id" not in joined


def test_each_runtime_job_keeps_its_provenance_and_identity_with_the_uploaded_evidence():
    steps = _workflow()["jobs"]["certify"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Capture toolchain identity for the evidence" in names and "Record run identity" in names
    capture = next(s for s in steps if s.get("name") == "Capture toolchain identity for the evidence")
    assert "docker-image-provenance.json" in capture["run"] and "oracle_image.json" in capture["run"]
    assert "docker image inspect" in capture["run"]
    identity = next(s for s in steps if s.get("name") == "Record run identity")
    assert identity["if"] == "always()"                                # identity is recorded even when the corpus step failed
    assert names.index("Record run identity") < names.index("Upload certification evidence")
    upload = next(s for s in steps if s.get("name") == "Upload certification evidence")
    assert upload["with"]["path"] == "certification/**"                # the provenance and identity files live under it


def test_the_summary_is_uploaded_even_when_aggregation_fails():
    steps = _workflow()["jobs"]["summarize"]["steps"]
    upload = next(s for s in steps if "upload-artifact" in s.get("uses", ""))
    assert upload["if"] == "always()" and upload["with"]["name"] == "exact-run-certification-summary"
    download = next(s for s in steps if "download-artifact" in s.get("uses", ""))
    assert download["with"]["pattern"] == "certification-*"


# --- independent review and security review ----------------------------------------------------------------------------------------

def test_an_artifact_from_another_attempt_of_the_same_run_is_a_problem(tmp_path, manifest):
    def mutate(root):
        p = root / "certification-quarkus" / "run_identity.json"
        data = json.loads(p.read_text())
        data["run_attempt"] = "2"
        p.write_text(json.dumps(data))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("quarkus" in p and "attempt" in p for p in summary["problems"])
    assert summary["identity"]["run_attempt"] == "1"


@pytest.mark.parametrize("line", [
    "plain_java: 55 apps; independent AGREE 45/45; UNCERTIFIED",
    "plain_java: 55 apps; independent AGREE 45/45; NOT FULLY CERTIFIED",
    "plain_java: 55 apps; independent AGREE 45/45; NOT CERTIFIED",
    "CERTIFIED but not really",
    "",
])
def test_only_the_exact_certified_line_shape_counts(tmp_path, manifest, line):
    def mutate(root):
        (root / "certification-plain_java" / "summary.txt").write_text(line + "\n", encoding="utf-8")
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("did not certify" in p for p in summary["problems"])


@pytest.mark.parametrize("field,value", [
    ("build_identity", "maven-offline-springboot@latest"), ("runtime_identity", "eclipse-temurin@sha256:short"),
    ("build_image_id", "not-a-digest"), ("runtime_image_id", "sha256:" + "G" * 64),
])
def test_image_provenance_must_be_real_digests_not_just_non_empty(tmp_path, manifest, field, value):
    def mutate(root):
        p = root / "certification-spring_boot" / "provenance" / "docker-image-provenance.json"
        data = json.loads(p.read_text())
        data[field] = value
        p.write_text(json.dumps(data))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("spring_boot" in p and field in p for p in summary["problems"])


def test_an_oracle_image_id_must_be_a_digest(tmp_path, manifest):
    def mutate(root):
        (root / "certification-quarkus" / "oracle_image.json").write_text(json.dumps({"image": "x", "id": "sha256:zz"}))
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert not summary["certified"] and any("quarkus" in p and "oracle image" in p for p in summary["problems"])


@pytest.mark.parametrize("name,content", [
    ("evidence/certification_corpus_plain_java.jsonl", "{not json\n"),
    ("evidence/certification_corpus_plain_java.jsonl", '{"verdict": "VERIFIED"}\n'),
    ("evidence/certification_corpus_plain_java_independent.jsonl", "[1, 2]\n"),
    ("evidence/validation_summaries_plain_java.jsonl", "oops\n"),
])
def test_malformed_evidence_is_a_problem_in_a_written_summary_not_a_crash(tmp_path, manifest, name, content):
    def mutate(root):
        (root / "certification-plain_java" / name).write_text(content, encoding="utf-8")
    summary, _ = build(tmp_path, manifest, mutate=mutate)
    assert summary["certified"] is False
    assert any("plain_java" in p and "unreadable" in p for p in summary["problems"])


def test_the_summary_states_that_its_evidence_is_self_attested(tmp_path, manifest):
    summary, _ = build(tmp_path, manifest)
    assert any("self-attested" in line for line in summary["not_proven"])
