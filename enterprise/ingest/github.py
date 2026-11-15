"""GitHub ingestion of a public repository, pinned to an exact commit.

Flow: validate the URL (github.com only) -> read repository metadata -> resolve the requested branch, tag or SHA to a 40-hex
commit -> download that commit's ZIP snapshot under a byte limit -> extract it with ``safe_extract`` (symlinks skipped) ->
build the deterministic manifest. Nothing from the repository is ever executed.

Network safety: the only user-supplied input is the repository URL, matched against a strict ``https://github.com/owner/repo``
pattern. API and archive hosts are fixed server-side configuration, and every redirect must stay on those hosts over HTTPS (or
the explicitly allowed test host). A token, if configured through ``SYSTEMAOPS_GITHUB_TOKEN``, is only sent to those hosts and
is never put in an error message or log line.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from enterprise.contracts import SourceSnapshot
from enterprise.ingest.manifest import build_manifest, common_root, prune_ignored
from enterprise.ingest.safe_extract import ArchiveRefusal, ExtractLimits, extract_zip
from enterprise.quotas import IngestionQuotas

_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9._-]{1,100}?)"
    r"(?:\.git)?(?:/tree/(?P<ref>[^?#]+))?/?$")
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
CHUNK = 1 << 20
MAX_RATE_LIMIT_WAIT = 60.0


class IngestRefusal(Exception):
    """Ingestion cannot proceed; ``code`` is stable and ``retryable`` says whether trying again later may help."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str
    ref: str | None = None

    @property
    def canonical_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


def parse_repository_url(url: str) -> RepoRef:
    match = _URL.match(url.strip()) if isinstance(url, str) else None
    if match is None or match["repo"] in (".", "..") or match["repo"].endswith(".git"):
        raise IngestRefusal("INVALID_REPO_URL", "expected https://github.com/<owner>/<repo>[/tree/<ref>]")
    ref = match["ref"]
    if ref is not None and (not _REF.match(ref) or ".." in ref or ref.startswith("/") or ref.endswith("/")
                            or "//" in ref or ref.endswith(".lock")):
        raise IngestRefusal("INVALID_REPO_URL", "the branch or tag in the URL is not a valid reference name")
    return RepoRef(match["owner"], match["repo"], ref)


class _SameHostsRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed: frozenset[str], allow_http: bool) -> None:
        self._allowed, self._allow_http = allowed, allow_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlparse(newurl)
        if target.hostname not in self._allowed or (target.scheme != "https" and not self._allow_http):
            raise IngestRefusal("REDIRECT_REFUSED", f"redirect to {target.hostname} is not allowed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GitHubIngestor:
    def __init__(
        self,
        api_base: str = "https://api.github.com",
        archive_base: str = "https://codeload.github.com",
        token: str | None = None,
        quotas: IngestionQuotas | None = None,
        allow_http: bool = False,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float | None = None,
    ) -> None:
        self._api, self._archive = api_base.rstrip("/"), archive_base.rstrip("/")
        self._token = token if token is not None else os.environ.get("SYSTEMAOPS_GITHUB_TOKEN") or None
        self._quotas = quotas or IngestionQuotas()
        self._allow_http = allow_http
        self._allowed = frozenset(urlparse(base).hostname for base in (self._api, self._archive, "https://github.com"))
        self._attempts = max_attempts
        self._sleep = sleep
        self._timeout = timeout or float(self._quotas.git_timeout_seconds)
        self._opener = urllib.request.build_opener(_SameHostsRedirect(self._allowed, allow_http))

    # -- HTTP --------------------------------------------------------------
    def _open(self, url: str):
        host = urlparse(url).hostname
        if host not in self._allowed:
            raise IngestRefusal("HOST_NOT_ALLOWED", f"{host} is not an allowed GitHub host")
        headers = {"User-Agent": "systemaops-ingest", "Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return self._opener.open(urllib.request.Request(url, headers=headers), timeout=self._timeout)

    def _request(self, url: str, reader: Callable):
        """Open ``url`` and pass the response to ``reader``; retry transient failures with bounded backoff."""
        last: IngestRefusal | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                with self._open(url) as response:
                    return reader(response)
            except urllib.error.HTTPError as exc:
                last = self._http_refusal(exc)
                if not last.retryable:
                    raise last from None
                wait = self._wait_seconds(exc, attempt)
                if wait > MAX_RATE_LIMIT_WAIT:
                    raise last from None
            except IngestRefusal:
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last = IngestRefusal("NETWORK_ERROR", f"{type(exc).__name__} while contacting GitHub", retryable=True)
                wait = min(2.0 ** attempt, 8.0)
            if attempt < self._attempts:
                self._sleep(wait)
        assert last is not None
        raise last

    @staticmethod
    def _wait_seconds(exc: urllib.error.HTTPError, attempt: int) -> float:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after and retry_after.isdigit():
            return float(retry_after)
        reset = exc.headers.get("X-RateLimit-Reset") if exc.headers else None
        if reset and reset.isdigit():
            return max(0.0, float(reset) - time.time())
        return min(2.0 ** attempt, 8.0)

    @staticmethod
    def _http_refusal(exc: urllib.error.HTTPError) -> IngestRefusal:
        headers = exc.headers or {}
        exhausted = headers.get("X-RateLimit-Remaining") == "0" or headers.get("Retry-After")
        if exc.code in (403, 429) and exhausted:
            return IngestRefusal("RATE_LIMITED", "GitHub rate limit reached", retryable=True)
        if exc.code == 404:
            return IngestRefusal("REPO_NOT_FOUND", "repository or reference not found (private repositories are not supported)")
        if exc.code in (401, 403):
            return IngestRefusal("REPO_FORBIDDEN", "GitHub refused access to this repository")
        if exc.code == 451:
            return IngestRefusal("REPO_UNAVAILABLE", "the repository is unavailable for legal reasons")
        if exc.code >= 500:
            return IngestRefusal("UPSTREAM_ERROR", f"GitHub answered {exc.code}", retryable=True)
        return IngestRefusal("UPSTREAM_ERROR", f"GitHub answered {exc.code}")

    def _json(self, url: str) -> dict:
        def read(response):
            raw = response.read((1 << 20) + 1)
            if len(raw) > 1 << 20:
                raise IngestRefusal("UPSTREAM_ERROR", "metadata response is unexpectedly large")
            try:
                data = json.loads(raw)
            except ValueError:
                raise IngestRefusal("UPSTREAM_ERROR", "GitHub returned invalid JSON") from None
            if not isinstance(data, dict):
                raise IngestRefusal("UPSTREAM_ERROR", "GitHub returned an unexpected document")
            return data

        return self._request(url, read)

    # -- steps -------------------------------------------------------------
    def resolve(self, repo: RepoRef) -> tuple[str, dict]:
        """``(commit_sha, repository_metadata)`` for the requested ref (the default branch when none was given)."""
        meta = self._json(f"{self._api}/repos/{repo.owner}/{repo.repo}")
        if meta.get("private"):
            raise IngestRefusal("REPO_FORBIDDEN", "private repositories are not supported")
        size_bytes = int(meta.get("size", 0)) * 1024
        if size_bytes > self._quotas.repo_transfer_bytes:
            raise IngestRefusal("REPO_TOO_LARGE", f"repository is about {size_bytes} bytes; the limit is "
                                f"{self._quotas.repo_transfer_bytes}")
        ref = repo.ref or str(meta.get("default_branch") or "")
        if not ref:
            raise IngestRefusal("REF_NOT_FOUND", "the repository reports no default branch")
        commit = self._json(f"{self._api}/repos/{repo.owner}/{repo.repo}/commits/{ref}")
        sha = str(commit.get("sha", ""))
        if not _SHA.match(sha):
            raise IngestRefusal("UPSTREAM_ERROR", "GitHub returned no valid commit SHA")
        return sha, {"default_branch": meta.get("default_branch", ""), "size_kb": meta.get("size", 0),
                     "archived": bool(meta.get("archived", False)), "resolved_ref": ref}

    def download(self, repo: RepoRef, sha: str, target: Path) -> int:
        """Stream the commit's ZIP to ``target`` under the transfer limit; returns its size."""
        if not _SHA.match(sha):
            raise IngestRefusal("INVALID_REF", "download needs a full commit SHA")
        limit = self._quotas.repo_transfer_bytes
        target.parent.mkdir(parents=True, exist_ok=True)

        def read(response) -> int:
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise IngestRefusal("REPO_TOO_LARGE", f"archive declares {declared} bytes; the limit is {limit}")
            size = 0
            with target.open("wb") as sink:
                for block in iter(lambda: response.read(CHUNK), b""):
                    size += len(block)
                    if size > limit:
                        raise IngestRefusal("REPO_TOO_LARGE", f"archive exceeds {limit} bytes")
                    sink.write(block)
            return size

        try:
            return self._request(f"{self._archive}/{repo.owner}/{repo.repo}/zip/{sha}", read)
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def ingest(self, url: str, workspace: Path, application_id: str = "", snapshot_id: str = "") -> SourceSnapshot:
        """Pin, download, extract and inventory a repository; the sources end up under ``workspace/source``."""
        repo = parse_repository_url(url)
        sha, meta = self.resolve(repo)
        workspace.mkdir(parents=True, exist_ok=True)
        archive = workspace / "snapshot.zip"
        try:
            self.download(repo, sha, archive)
            limits = ExtractLimits(
                max_files=self._quotas.repo_file_count, max_expanded_bytes=self._quotas.extracted_bytes,
                max_file_bytes=self._quotas.file_bytes, max_compression_ratio=self._quotas.compression_ratio,
                symlinks="skip")
            try:
                extracted = extract_zip(archive, workspace / "extract", limits)
            except ArchiveRefusal as refusal:
                raise IngestRefusal(refusal.code, refusal.message) from None
        finally:
            archive.unlink(missing_ok=True)
        root = common_root(extracted.files)
        manifest = build_manifest(extracted.files, root)
        source_dir = workspace / "source"
        shutil.rmtree(source_dir, ignore_errors=True)
        shutil.move(str(workspace / "extract" / root) if root else str(workspace / "extract"), str(source_dir))
        shutil.rmtree(workspace / "extract", ignore_errors=True)
        prune_ignored(source_dir, manifest)
        return SourceSnapshot(
            snapshot_id=snapshot_id or manifest.manifest_id[:32], application_id=application_id, source_type="github",
            repository=repo.canonical_url, requested_ref=repo.ref or "", resolved_commit=sha, manifest=manifest)
