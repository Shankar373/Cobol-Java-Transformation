"""GitHub ingestion against a real local HTTP server standing in for GitHub.

The URL, redirect, retry, rate-limit and size handling run over real sockets and real ``urllib``. This is NOT a test against
live GitHub: ``docs/execution/PHASE_2_GITHUB_INGESTION.md`` records separately whether a live fetch was performed.
"""

import io
import json
import stat
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from enterprise.ingest.github import GitHubIngestor, IngestRefusal, parse_repository_url
from enterprise.quotas import IngestionQuotas

SHA = "a" * 40
OTHER_SHA = "b" * 40


def build_zip(files: dict, symlink: dict | None = None, prefix: str = f"repo-{SHA}/") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(prefix + name, data)
        for name, target in (symlink or {}).items():
            info = zipfile.ZipInfo(prefix + name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return buffer.getvalue()


SOURCES = {
    "src/PAY001.cbl": b"       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PAY001.\n",
    "copy/CUST.cpy": b"       01 CUST-REC PIC X(10).\n",
    "jcl/RUN.jcl": b"//RUN JOB\n",
    ".git/config": b"[core]\n",
    "logo.png": b"\x89PNG....",
    "README.md": b"# demo\n",
}


class Server:
    """Scripted stand-in: ``routes[path]`` is a list of (status, headers, body); the last entry repeats."""

    def __init__(self) -> None:
        self.routes: dict[str, list] = {}
        self.requests: list[tuple[str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append((self.path, dict(self.headers)))
                queue = outer.routes.get(self.path)
                if not queue:
                    self.send_response(404)
                    self.end_headers()
                    return
                status, headers, body = queue[0] if len(queue) == 1 else queue.pop(0)
                self.send_response(status)
                chunked = headers.pop("X-Chunked", None)
                for key, value in headers.items():
                    self.send_header(key, value)
                if chunked:
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    try:
                        for start in range(0, len(body), 65536):
                            piece = body[start:start + 65536]
                            self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
                        self.wfile.write(b"0\r\n\r\n")
                    except OSError:
                        pass
                else:
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def json(self, path, payload, status=200, headers=None):
        self.routes[path] = [(status, {"Content-Type": "application/json", **(headers or {})},
                              json.dumps(payload).encode())]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server():
    srv = Server()
    yield srv
    srv.stop()


def serve_repo(srv, files=None, size_kb=10, default_branch="main", private=False, **zip_kw):
    srv.json("/repos/acme/bank", {"default_branch": default_branch, "size": size_kb, "private": private,
                                  "archived": False})
    for ref in (default_branch, "release/1.0", SHA):
        srv.json(f"/repos/acme/bank/commits/{ref}", {"sha": SHA})
    srv.routes[f"/acme/bank/zip/{SHA}"] = [(200, {"Content-Type": "application/zip"}, build_zip(files or SOURCES, **zip_kw))]


def ingestor(srv, sleeps=None, **kw):
    sleeps = sleeps if sleeps is not None else []
    return GitHubIngestor(api_base=srv.base, archive_base=srv.base, allow_http=True, sleep=sleeps.append,
                          timeout=10, **kw)


# -- URL validation -------------------------------------------------------------------------------

@pytest.mark.parametrize("url,owner,repo,ref", [
    ("https://github.com/acme/bank", "acme", "bank", None),
    ("https://github.com/acme/bank.git", "acme", "bank", None),
    ("https://github.com/acme/bank/", "acme", "bank", None),
    ("https://github.com/acme/bank/tree/release/1.0", "acme", "bank", "release/1.0"),
    ("https://github.com/a-b/c.d_e", "a-b", "c.d_e", None),
])
def test_valid_repository_urls(url, owner, repo, ref):
    parsed = parse_repository_url(url)
    assert (parsed.owner, parsed.repo, parsed.ref) == (owner, repo, ref)


@pytest.mark.parametrize("url", [
    "http://github.com/acme/bank", "https://github.com.evil.com/acme/bank", "https://evil.com/github.com/acme/bank",
    "https://user@github.com/acme/bank", "https://github.com:8443/acme/bank", "git@github.com:acme/bank.git",
    "https://github.com/acme", "https://github.com/acme/bank/blob/main/x.cbl", "https://github.com/acme/bank?x=1",
    "https://github.com/acme/bank#frag", "https://github.com/-bad/bank", "https://github.com/acme/..",
    "https://github.com/acme/bank/tree/../../etc", "https://github.com/acme/bank/tree/a//b", "file:///etc/passwd",
    "https://github.com/acme/bank/tree/x.lock", "", "https://github.com/acme/bank\nHost: evil", "ftp://github.com/a/b",
])
def test_invalid_repository_urls_are_refused(url):
    with pytest.raises(IngestRefusal) as exc:
        parse_repository_url(url)
    assert exc.value.code == "INVALID_REPO_URL"


# -- end to end -----------------------------------------------------------------------------------

def test_ingest_pins_the_commit_and_builds_the_inventory(server, tmp_path):
    serve_repo(server, symlink={"src/link": "/etc/passwd"})
    snap = ingestor(server).ingest("https://github.com/acme/bank", tmp_path / "ws", application_id="app1")
    assert snap.resolved_commit == SHA and snap.repository == "https://github.com/acme/bank"
    assert snap.requested_ref == "" and snap.source_type == "github" and snap.application_id == "app1"
    kinds = {f.path: f.file_type for f in snap.manifest.files}
    assert kinds == {"README.md": "doc", "copy/CUST.cpy": "copybook", "jcl/RUN.jcl": "jcl", "src/PAY001.cbl": "cobol"}
    assert {i.path: i.reason for i in snap.manifest.ignored}.keys() == {".git/config", "logo.png"}
    assert (tmp_path / "ws" / "source" / "src" / "PAY001.cbl").read_bytes() == SOURCES["src/PAY001.cbl"]
    assert not (tmp_path / "ws" / "source" / ".git").exists() and not (tmp_path / "ws" / "source" / "logo.png").exists()
    assert not (tmp_path / "ws" / "source" / "src" / "link").exists()  # symlinks are skipped, never followed
    assert not (tmp_path / "ws" / "snapshot.zip").exists() and not (tmp_path / "ws" / "extract").exists()
    paths = [p for p, _ in server.requests]
    assert paths == ["/repos/acme/bank", "/repos/acme/bank/commits/main", f"/acme/bank/zip/{SHA}"]


def test_the_same_commit_yields_the_same_manifest_and_a_changed_file_changes_it(server, tmp_path):
    serve_repo(server)
    first = ingestor(server).ingest("https://github.com/acme/bank", tmp_path / "w1")
    second = ingestor(server).ingest("https://github.com/acme/bank", tmp_path / "w2")
    assert first.manifest == second.manifest and first.manifest.manifest_id == second.manifest.manifest_id
    changed = dict(SOURCES, **{"src/PAY001.cbl": SOURCES["src/PAY001.cbl"] + b" "})
    serve_repo(server, files=changed)
    third = ingestor(server).ingest("https://github.com/acme/bank", tmp_path / "w3")
    assert third.manifest.manifest_id != first.manifest.manifest_id


def test_an_explicit_branch_is_resolved_instead_of_the_default(server, tmp_path):
    serve_repo(server)
    snap = ingestor(server).ingest("https://github.com/acme/bank/tree/release/1.0", tmp_path / "ws")
    assert snap.requested_ref == "release/1.0"
    assert "/repos/acme/bank/commits/release/1.0" in [p for p, _ in server.requests]


# -- failures ------------------------------------------------------------------------------------

def refusal(server, tmp_path, url="https://github.com/acme/bank", **kw) -> IngestRefusal:
    with pytest.raises(IngestRefusal) as exc:
        ingestor(server, **kw).ingest(url, tmp_path / "ws")
    return exc.value


def test_unknown_repository_and_private_repository(server, tmp_path):
    assert refusal(server, tmp_path).code == "REPO_NOT_FOUND"
    serve_repo(server, private=True)
    assert refusal(server, tmp_path).code == "REPO_FORBIDDEN"


def test_missing_ref_is_reported(server, tmp_path):
    serve_repo(server)
    err = refusal(server, tmp_path, url="https://github.com/acme/bank/tree/nope")
    assert err.code == "REPO_NOT_FOUND"


def test_rate_limit_with_a_long_reset_is_reported_without_waiting(server, tmp_path):
    server.json("/repos/acme/bank", {"message": "rate limit"}, status=403,
                headers={"X-RateLimit-Remaining": "0", "Retry-After": "3000"})
    sleeps: list[float] = []
    err = refusal(server, tmp_path, sleeps=sleeps)
    assert err.code == "RATE_LIMITED" and err.retryable and sleeps == []


def test_a_short_rate_limit_is_waited_out_and_retried(server, tmp_path):
    serve_repo(server)
    good = server.routes["/repos/acme/bank"][0]
    limited = (403, {"Content-Type": "application/json", "X-RateLimit-Remaining": "0", "Retry-After": "2"}, b"{}")
    server.routes["/repos/acme/bank"] = [limited, good]
    sleeps: list[float] = []
    snap = ingestor(server, sleeps=sleeps).ingest("https://github.com/acme/bank", tmp_path / "ws")
    assert snap.resolved_commit == SHA and sleeps == [2.0]


def test_transient_server_errors_are_retried_then_reported(server, tmp_path):
    serve_repo(server)
    good = server.routes["/repos/acme/bank"][0]
    server.routes["/repos/acme/bank"] = [(500, {}, b"oops"), (502, {}, b"oops"), good]
    snap = ingestor(server).ingest("https://github.com/acme/bank", tmp_path / "w1")
    assert snap.resolved_commit == SHA
    server.routes["/repos/acme/bank"] = [(503, {}, b"down")]
    sleeps: list[float] = []
    err = refusal(server, tmp_path, sleeps=sleeps)
    assert err.code == "UPSTREAM_ERROR" and err.retryable and len(sleeps) == 2  # three attempts, two waits


def test_an_unreachable_server_is_a_retryable_network_error(server, tmp_path):
    server.stop()
    sleeps: list[float] = []
    err = refusal(server, tmp_path, sleeps=sleeps)
    assert err.code == "NETWORK_ERROR" and err.retryable and len(sleeps) == 2
    server.httpd = None  # the fixture's stop() is then a no-op
    server.stop = lambda: None  # type: ignore[method-assign]


def test_repository_and_archive_size_limits(server, tmp_path):
    quotas = IngestionQuotas(repo_transfer_bytes=50_000)
    serve_repo(server, size_kb=100)  # metadata says about 100 KiB
    assert refusal(server, tmp_path, quotas=quotas).code == "REPO_TOO_LARGE"
    serve_repo(server, size_kb=1)  # metadata lies; the archive itself is far bigger and sent without a length
    big = build_zip({"big.bin": __import__("os").urandom(200_000)})
    server.routes[f"/acme/bank/zip/{SHA}"] = [(200, {"Content-Type": "application/zip", "X-Chunked": "1"}, big)]
    assert refusal(server, tmp_path, quotas=quotas).code == "REPO_TOO_LARGE"
    assert not (tmp_path / "ws" / "snapshot.zip").exists()
    server.routes[f"/acme/bank/zip/{SHA}"] = [(200, {"Content-Type": "application/zip"}, big)]
    assert refusal(server, tmp_path, quotas=quotas).code == "REPO_TOO_LARGE"  # declared length is checked first


def test_redirects_may_not_leave_the_allowed_hosts(server, tmp_path):
    serve_repo(server)
    server.routes[f"/acme/bank/zip/{SHA}"] = [(302, {"Location": "http://localhost:9/evil.zip"}, b"")]
    assert refusal(server, tmp_path).code == "REDIRECT_REFUSED"
    good = build_zip(SOURCES)
    server.routes["/moved"] = [(200, {"Content-Type": "application/zip"}, good)]
    server.routes[f"/acme/bank/zip/{SHA}"] = [(302, {"Location": f"{server.base}/moved"}, b"")]
    snap = ingestor(server).ingest("https://github.com/acme/bank", tmp_path / "ok")
    assert snap.resolved_commit == SHA  # a redirect that stays on the allowed host is followed


def test_a_malicious_archive_is_refused_and_leaves_nothing(server, tmp_path):
    serve_repo(server)
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr(f"repo-{SHA}/ok.cbl", b"x")
        info = zipfile.ZipInfo("placeholder")
        info.filename = f"repo-{SHA}/../../escape.txt"
        zf.writestr(info, b"evil")
    server.routes[f"/acme/bank/zip/{SHA}"] = [(200, {"Content-Type": "application/zip"}, evil.getvalue())]
    err = refusal(server, tmp_path)
    assert err.code == "ARCHIVE_BAD_PATH"
    assert not (tmp_path / "ws" / "extract").exists() and not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "ws" / "snapshot.zip").exists()


def test_the_token_goes_only_to_allowed_hosts_and_never_into_errors(server, tmp_path):
    secret = "ghp_SECRET_TOKEN_VALUE_123"
    serve_repo(server)
    ingestor(server, token=secret).ingest("https://github.com/acme/bank", tmp_path / "ok")
    assert all(h.get("Authorization") == f"Bearer {secret}" for _, h in server.requests)
    server.routes["/repos/acme/bank"] = [(500, {}, secret.encode())]
    err = refusal(server, tmp_path, token=secret)
    assert secret not in str(err) and secret not in err.message
    for url in ("http://evil.example/x", "http://169.254.169.254/latest/meta-data"):
        with pytest.raises(IngestRefusal) as exc:
            ingestor(server, token=secret)._open(url)
        assert exc.value.code == "HOST_NOT_ALLOWED"  # a token is never sent to an arbitrary host (SSRF)


def test_download_needs_a_full_commit_sha(server, tmp_path):
    with pytest.raises(IngestRefusal) as exc:
        ingestor(server).download(parse_repository_url("https://github.com/acme/bank"), "main", tmp_path / "x.zip")
    assert exc.value.code == "INVALID_REF"
