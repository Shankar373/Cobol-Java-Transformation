# Discovery test coverage (measured 2026-11-18)

Command: `coverage run --rcfile=/dev/null --source=enterprise/discovery,api/discovery_routes.py -m pytest tests/discovery`
(667 passed, 6 skipped: symlink creation needs privilege on this Windows machine, and zipfile rewrites backslashes when reading on Windows; both run on Linux CI).

| Scope | Statements | Missed | Line coverage |
|---|---|---|---|
| `enterprise/discovery/` (33 modules, measured before deleting the unused `pathsafe.py`, 77 statements at 0%) | 4688 | 408 | 91% (92% without `pathsafe.py`) |
| `api/discovery_routes.py` (measured in a separate run) | 87 | 5 | 94% |
| `frontend/src/pages/Discovery.tsx` | not measured | | 5 Vitest tests cover submit, polling, refusal, validation, 401, verify |

Lowest modules: `errors.py` 70% (diagnostic formatting helpers), `model.py` 78%, `checkpoint_verify.py` 87%, `zipsource.py` 87%, `cobol_text.py` 88%.
Line coverage says which code ran, not that the behaviour is right; COBOL scanner behaviour is covered by assertions on exact findings and positions, not by coverage alone.
The repository-wide floor in CI (`coverage report --fail-under=88` over `api`, `engine`, `tools`) does not include `enterprise/`.
