"""G-17: published certification numbers must match the evidence (and reject drift).

The committed ``certification_summary.json`` is recomputed from the evidence
files on every run, and the README's corpus counts are validated against it.
Dependency-free (pytest only) so it can sit in the hermetic suite.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from tools import certification_summary as cs

REPO = cs.REPO
SUMMARY = REPO / cs.DEFAULT_SUMMARY


@pytest.fixture(scope="module")
def committed() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def _evidence_copy(tmp_path: Path) -> Path:
    for rel in (cs.CORPUS_DIR, cs.SUMMARIES_DIR):
        shutil.copytree(REPO / rel, tmp_path / rel, ignore=shutil.ignore_patterns("samples", "*.md"))
    return tmp_path


def test_committed_summary_matches_the_evidence_it_was_derived_from(committed):
    assert cs.check_summary(committed) == []


def test_summary_identifies_the_exact_commit_run_and_runtimes(committed):
    source = committed["source"]
    assert len(source["commit_sha"]) == 40 and source["workflow_run_id"].isdigit()
    assert source["workflow_run_url"].endswith(source["workflow_run_id"])
    assert set(committed["runtimes"]) == set(cs.RUNTIMES)
    assert len(committed["fixtures"]["manifest_sha256"]) == 64
    for block in committed["runtimes"].values():
        assert block["evidence_sha256"] and all(len(h) == 64 for h in block["evidence_sha256"].values())


def test_readme_corpus_counts_are_validated_against_the_evidence(committed):
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert cs.check_documentation(committed, text, "README.md") == []
    claim = cs.corpus_claim(committed)
    assert claim and f"{claim['verified']} of {claim['applications']} fixture applications VERIFIED" in text


@pytest.mark.parametrize("text", [
    "46 of 55 fixture applications VERIFIED on each runtime",
    "45 of 54 applications VERIFIED",
    "independent AGREE 44/45",
    "10 refused by name",
])
def test_documentation_with_a_count_the_evidence_does_not_support_is_rejected(committed, text):
    assert cs.check_documentation(committed, text, "doc.md")


def test_documentation_with_the_supported_counts_is_accepted(committed):
    claim = cs.corpus_claim(committed)
    text = (f"{claim['verified']} of {claim['applications']} applications VERIFIED; "
            f"AGREE {claim['independent_agree']}/{claim['verified']}; "
            f"{claim['refused_by_name']} refused by name")
    assert cs.check_documentation(committed, text, "doc.md") == []


@pytest.mark.parametrize("path,value", [
    (("runtimes", "plain_java", "totals", "verified"), 46),
    (("runtimes", "quarkus", "independent", "agree"), 44),
    (("runtimes", "micronaut", "totals", "refused_by_name"), 8),
    (("fixtures", "manifest_sha256"), "0" * 64),
])
def test_a_tampered_summary_is_rejected(committed, path, value):
    tampered = copy.deepcopy(committed)
    node = tampered
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    assert cs.check_summary(tampered)


def test_changed_evidence_is_detected_by_hash_and_totals(tmp_path):
    repo = _evidence_copy(tmp_path)
    good = cs.build_summary(commit_sha="a" * 40, run_id="1", repo=repo)
    corpus = repo / cs.CORPUS_DIR / "runtime_corpus_plain_java.jsonl"
    rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
    victim = next(r for r in rows if r.get("verdict") == "VERIFIED")
    victim["verdict"] = "FAILED"
    corpus.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8", newline="\n")
    problems = cs.check_summary(good, repo)
    assert any("plain_java.totals" in p for p in problems)
    assert any("plain_java.evidence_sha256" in p for p in problems)
    # the independent re-check no longer covers exactly the VERIFIED applications
    assert any("independent_covers_exactly_the_verified" in p for p in problems)


def test_independent_recheck_disagreement_blocks_certification(tmp_path):
    repo = _evidence_copy(tmp_path)
    path = repo / cs.CORPUS_DIR / "runtime_corpus_spring_boot_independent.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[0]["verdict"] = "DISAGREE"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8", newline="\n")
    summary = cs.build_summary(commit_sha="b" * 40, run_id="2", repo=repo)
    block = summary["runtimes"]["spring_boot"]
    assert block["status"] == "NOT_CERTIFIED" and block["independent"]["other"] == {"DISAGREE": 1}
    assert cs.check_summary(summary, repo)  # a non-certifying runtime is a reported problem


def test_missing_evidence_is_a_problem_not_a_pass(tmp_path, committed):
    problems = cs.check_summary(committed, tmp_path)
    assert problems and "cannot recompute" in problems[0]


@pytest.mark.parametrize("sha,run", [("abc", "1"), ("A" * 40, "1"), ("a" * 40, "x"), ("a" * 40, "")])
def test_malformed_commit_or_run_id_is_refused(sha, run):
    with pytest.raises(ValueError):
        cs.build_summary(commit_sha=sha, run_id=run)


def test_unknown_schema_is_rejected(committed):
    other = {**committed, "schema_version": 99}
    assert cs.check_summary(other) and "unsupported schema" in cs.check_summary(other)[0]


def test_hash_is_line_ending_independent(tmp_path):
    lf, crlf = tmp_path / "a", tmp_path / "b"
    lf.write_bytes(b"x\ny\n")
    crlf.write_bytes(b"x\r\ny\r\n")
    assert cs.sha256_normalised(lf) == cs.sha256_normalised(crlf)


def test_missing_toolchain_identity_is_stated_not_invented(committed):
    toolchain = committed["toolchain"]
    assert toolchain["reference_runtime"] == "GnuCOBOL 3.1.2"
    assert toolchain["image_identities"] is None and toolchain["image_identities_note"]


def test_a_missing_or_empty_fixture_directory_is_a_problem_not_a_hash_of_nothing(tmp_path, committed):
    repo = _evidence_copy(tmp_path)
    good = cs.build_summary(commit_sha="c" * 40, run_id="3", repo=repo)
    problems = cs.check_summary(good, repo)
    assert any("directory is missing or empty" in p for p in problems)


def test_commit_and_run_id_are_asserted_not_recomputable_and_the_summary_says_so(committed):
    """No evidence file records the commit or run id, so ``check`` cannot detect an edit to them;
    the summary states that they must be verified against GitHub instead of implying otherwise."""
    assert "gh run view" in committed["source"]["assertion_note"]
    with pytest.raises(ValueError):
        cs.build_summary(commit_sha="not-a-sha", run_id="1")


def test_edited_not_proven_or_toolchain_is_detected(committed):
    for edit in (
        lambda s: s.__setitem__("not_proven", []),
        lambda s: s["toolchain"].__setitem__("reference_runtime", "IBM Enterprise COBOL"),
    ):
        tampered = copy.deepcopy(committed)
        edit(tampered)
        assert cs.check_summary(tampered), edit


def test_documentation_that_states_no_corpus_count_validates_nothing_and_is_reported(committed):
    problems = cs.check_documentation(committed, "A readme with no certification numbers at all.", "doc.md")
    assert problems and "nothing was validated" in problems[0]


def test_fixture_manifest_depends_only_on_sorted_posix_path_strings(tmp_path):
    """Windows and POSIX ``Path`` orderings differ ('a/b' before 'a-b' by component, after it by
    string), which once made the same files hash differently on Linux CI."""
    for rel, text in (("fixtures/app/a/b.txt", "1"), ("fixtures/app/a-b/c.txt", "2"),
                      ("fixtures/app/B.txt", "3"), ("fixtures/app/a.txt", "4")):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    import hashlib

    def digest(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    names = sorted(["app/a/b.txt", "app/a-b/c.txt", "app/B.txt", "app/a.txt"])  # plain string order
    contents = {"app/a/b.txt": "1", "app/a-b/c.txt": "2", "app/B.txt": "3", "app/a.txt": "4"}
    lines = ["app\0<dir:present>"] + [f"{n}\0{digest(contents[n])}" for n in names]
    expected = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    assert cs.fixture_manifest(tmp_path, ["app"])["manifest_sha256"] == expected
