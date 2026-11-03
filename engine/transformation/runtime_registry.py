"""The single table of Java runtime targets.

Every place that needs to know which runtimes exist, which are certified,
what plan output type each produces and which build/execute lane validates
it reads this table: the assembly adapters (``runtime_adapters``), the
candidate-lane factory (``engine.candidate.factory``), the control-plane API
(``POST /applications`` rejects an uncertified target; ``GET /runtimes``
lists the table) and the frontend selector (fed by ``GET /runtimes``).

``certified`` means the target passes the 54-application corpus certification
(``.github/workflows/certification.yml``): a deterministic generation, an
offline build, hardened execution and a comparison with GnuCOBOL, with every
VERIFIED application independently re-checked.  ``jakarta_ee`` is generated
(a dependency-free jar under a Jakarta-marked pom) but is *not* certified and
is therefore not accepted by the API.

Adding a runtime means adding one row here and its assembly adapter; the
certification workflow matrix and ``docs/RUNTIME_ADAPTERS.md`` must follow.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Candidate (build + execute) lanes.
LANE_SPRING_BOOT = "spring_boot"  # DockerSpringBootCandidateAdapter
LANE_MAVEN = "maven"  # MavenProjectCandidateAdapter (one runnable jar)


@dataclass(frozen=True)
class RuntimeTarget:
    key: str
    label: str
    plan_output_type: str
    lane: str
    certified: bool
    note: str


RUNTIME_TARGETS: tuple[RuntimeTarget, ...] = (
    RuntimeTarget(
        "spring_boot", "Spring Boot", "SPRING_BOOT", LANE_SPRING_BOOT, True,
        "Spring Boot application (default)",
    ),
    RuntimeTarget(
        "plain_java", "Plain Java", "NATIVE_JAVA", LANE_MAVEN, True,
        "Maven project building one runnable jar, no framework",
    ),
    RuntimeTarget(
        "jakarta_ee", "Jakarta EE (generation profile)", "JAKARTA_EE", LANE_MAVEN, False,
        "Dependency-free jar under a Jakarta-marked pom; no application server; not certified",
    ),
    RuntimeTarget(
        "quarkus", "Quarkus (command mode)", "QUARKUS", LANE_MAVEN, True,
        "Command-mode application; no HTTP endpoints, no native image",
    ),
    RuntimeTarget(
        "micronaut", "Micronaut (command mode)", "MICRONAUT", LANE_MAVEN, True,
        "Command-mode application; no HTTP endpoints, no native image",
    ),
)

_BY_KEY = {t.key: t for t in RUNTIME_TARGETS}

RUNTIME_KEYS: tuple[str, ...] = tuple(t.key for t in RUNTIME_TARGETS)
CERTIFIED_RUNTIME_KEYS: tuple[str, ...] = tuple(t.key for t in RUNTIME_TARGETS if t.certified)


def runtime_target(key: str) -> RuntimeTarget:
    """The registry row for ``key``; ``ValueError`` naming the known keys otherwise."""
    try:
        return _BY_KEY[key]
    except (KeyError, TypeError):
        raise ValueError(
            f"invalid target_runtime: {key!r} - supported target_runtime values: "
            f"{', '.join(repr(k) for k in RUNTIME_KEYS)}"
        ) from None


def require_certified(key: str) -> RuntimeTarget:
    """``runtime_target`` that also refuses a target outside the certified set."""
    target = runtime_target(key)
    if not target.certified:
        raise ValueError(
            f"target_runtime {key!r} is not certified; certified runtimes: "
            f"{', '.join(repr(k) for k in CERTIFIED_RUNTIME_KEYS)}"
        )
    return target
