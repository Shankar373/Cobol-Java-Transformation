"""OCESQL + PostgreSQL reference runner (roadmap unit 12).

Runs an embedded-SQL COBOL program in the ``ocesql-pg`` image (``Dockerfile.ocesql-pg``: GnuCOBOL
3.1.2, OCESQL v1.4 pinned by commit, PostgreSQL 14) against a database seeded from a SQL script,
with no network, and returns the program's standard output and a canonical dump of the final
database state with its SHA-256.  Two runs of the same program against the same seed give the same
hash, so the state of a migrated program's database can be compared with the reference's.

What this reference is, and is not.  It is the behaviour of embedded SQL compiled by OCESQL on
PostgreSQL.  It is **not** a DB2 oracle: OCESQL reports its own SQLCODEs (for example -403 for a
duplicate key where DB2 reports -803, and -400 for most other errors) and leaves the PostgreSQL
transaction aborted after an error (SQLSTATE 25P02 on every later statement until ROLLBACK), where
DB2 rolls back only the failing statement.  Comparisons are therefore made on the success and
no-data paths (SQLCODE 0 / 100), on SQLSTATE of the first failing statement, and on database
state; the evidence level is ``SIMULATOR_VERIFIED``-style and never ``DB2_RUNTIME_VERIFIED``.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

ORACLE_PG_IMAGE = "ocesql-pg:latest"
STATE_MARK = "==STATE=="
_PG = "/usr/lib/postgresql/14/bin"

# OCESQL emits its statement constants only when a line sits between the end of the declarations
# and PROCEDURE DIVISION (observed with v1.4); a fixed-format comment line is inserted when absent.
_PROCEDURE = re.compile(r"^(\s*)PROCEDURE\s+DIVISION\b", re.IGNORECASE | re.MULTILINE)

_DRIVER = """set -e
install -d -o postgres -g postgres /tmp/pg
su postgres -c "{pg}/initdb -D /tmp/pg/data -A trust >/dev/null"
su postgres -c "{pg}/pg_ctl -D /tmp/pg/data -l /tmp/pg/log -o '-c listen_addresses=localhost' -w start >/dev/null"
su postgres -c "{pg}/psql -q -v ON_ERROR_STOP=1 -c 'create database testdb'"
su postgres -c "{pg}/psql -q -v ON_ERROR_STOP=1 -d testdb -f /w/seed.sql"
cd /w
ocesql prog.cbl prog.cob >/dev/null
cobc -x -I /usr/local/share/open-cobol-esql/copy -o prog prog.cob -Q -Wl,--no-as-needed -L/usr/local/lib -locesql
export LD_LIBRARY_PATH=/usr/local/lib
set +e
./prog
echo "rc=$?"
set -e
echo "{mark}"
{dump}
"""


@dataclass(frozen=True)
class OraclePgResult:
    stdout: tuple[str, ...]
    returncode: int
    state: tuple[str, ...]  # canonical dump of the final tables, one row per line
    state_hash: str


def with_banner(source: str) -> str:
    """Insert the comment line OCESQL needs before PROCEDURE DIVISION when none is there."""
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if _PROCEDURE.match(line):
            if index > 0 and lines[index - 1].strip().startswith("*"):
                return source
            lines.insert(index, "      *")
            return "\n".join(lines) + "\n"
    return source


def state_hash(state: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(state).encode("utf-8")).hexdigest()


def dump_command(tables: tuple[str, ...]) -> str:
    """psql commands that print every row of every table as text, in a canonical order."""
    parts = []
    for table in tables:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise ValueError(f"table name {table!r} is not a plain identifier")
        parts.append(
            f"echo '--{table}'; su postgres -c \"{_PG}/psql -At -d testdb -c "
            f"'select t::text from {table} t order by t::text'\""
        )
    return "\n".join(parts)


def run_cobol(
    source: str, seed_sql: str, tables: tuple[str, ...], *, timeout: int = 300,
    image: str = ORACLE_PG_IMAGE,
) -> OraclePgResult:
    """Compile and run ``source`` through OCESQL against a database seeded with ``seed_sql``."""
    work = Path(tempfile.mkdtemp(prefix="ocesql-pg-"))
    try:
        (work / "prog.cbl").write_text(with_banner(source), encoding="utf-8", newline="\n")
        (work / "seed.sql").write_text(seed_sql, encoding="utf-8", newline="\n")
        (work / "run.sh").write_text(
            _DRIVER.format(pg=_PG, mark=STATE_MARK, dump=dump_command(tables)),
            encoding="utf-8", newline="\n")
        done = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "-v", f"{work}:/w", image,
             "bash", "/w/run.sh"],
            capture_output=True, timeout=timeout, check=False,
            env=_no_path_conversion(),
        )
        if done.returncode != 0:
            raise RuntimeError(
                "ocesql-pg run failed: " + done.stderr.decode("utf-8", "replace")[-2000:])
        lines = done.stdout.decode("utf-8", "replace").splitlines()
        cut = lines.index(STATE_MARK)
        out, state = lines[:cut], tuple(lines[cut + 1:])
        rc = 0
        if out and out[-1].startswith("rc="):
            rc = int(out.pop()[3:])
        return OraclePgResult(tuple(out), rc, state, state_hash(state))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _no_path_conversion() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"  # Git Bash must not rewrite the container paths
    return env
