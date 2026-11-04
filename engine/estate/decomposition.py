"""Decomposition planner: propose service boundaries from the estate graph, for human review.

The planner is deterministic and conservative.  Programs that **must** stay together are merged into one
candidate service:

* a static ``CALLS`` edge between programs in the upload (an in-process call cannot cross a service
  boundary without a redesign);
* two programs bound to the same dataset (``BINDS``): a dataset has one owner, so its readers and writers
  stay with it;
* two programs using the same DB2 table (``USES_DB2``), for the same reason.

Everything else is *coupling* between services and is reported, never silently cut: shared copybooks
(a shared-library candidate), programs run by the same JCL job (an orchestration dependency), and
dataset flows between steps.  A group that holds a blocked edge (an external call, an unbound ddname, an
MQ/IMS/CICS reference) is marked ``blocked`` with the edges that block it.

What this is not: a decision.  The plan always has ``review_required: true``; it generates no code,
artifacts or containers (the multi-artifact and multi-container generation of the roadmap is not
implemented), and it proves nothing about a split's behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.estate.model import BLOCKED, Estate


@dataclass(frozen=True)
class Service:
    name: str
    programs: tuple[str, ...]
    datasets: tuple[str, ...]
    db2_tables: tuple[str, ...]
    entry_steps: tuple[str, ...]  # job steps that run one of the programs
    blocked: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class Coupling:
    source: str  # service name
    target: str
    kind: str  # SHARED_COPYBOOK | SAME_JOB | DATASET_FLOW
    detail: str


@dataclass
class DecompositionPlan:
    services: list[Service] = field(default_factory=list)
    couplings: list[Coupling] = field(default_factory=list)
    unassigned: tuple[str, ...] = ()  # programs that are not in any group (cannot happen) -- kept for audit
    review_required: bool = True

    def to_dict(self) -> dict:
        return {
            "review_required": self.review_required,
            "service_count": len(self.services),
            "services": [s.__dict__ | {"programs": list(s.programs), "datasets": list(s.datasets),
                                       "db2_tables": list(s.db2_tables), "entry_steps": list(s.entry_steps),
                                       "blockers": list(s.blockers)} for s in self.services],
            "couplings": [c.__dict__ for c in self.couplings],
            "unassigned": list(self.unassigned),
            "notes": [
                "A proposal for review: no code, artifact or container is generated.",
                "Programs sharing a call, a dataset or a DB2 table are kept together by rule.",
            ],
        }


class _Groups:
    def __init__(self, items: list[str]) -> None:
        self.parent = {i: i for i in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # the lexicographically smaller root wins, so the grouping does not depend on edge order
            self.parent[max(ra, rb)] = min(ra, rb)


def plan_decomposition(estate: Estate) -> DecompositionPlan:
    programs = sorted(n.id for n in estate.nodes if n.kind == "PROGRAM")
    groups = _Groups(programs)
    program_set = set(programs)

    by_resource: dict[tuple[str, str], list[str]] = {}
    for edge in estate.edges:
        if edge.relation == "CALLS" and edge.source in program_set and edge.target in program_set:
            groups.union(edge.source, edge.target)
        elif edge.relation in ("BINDS", "USES_DB2") and edge.source in program_set:
            by_resource.setdefault((edge.relation, edge.target), []).append(edge.source)
    for members in by_resource.values():
        for other in members[1:]:
            groups.union(members[0], other)

    members_of: dict[str, list[str]] = {}
    for program in programs:
        members_of.setdefault(groups.find(program), []).append(program)

    service_of: dict[str, str] = {}
    services: list[Service] = []
    for root in sorted(members_of):
        members = sorted(members_of[root])
        name = "svc-" + members[0].split(":", 1)[1].lower()
        for program in members:
            service_of[program] = name
        member_set = set(members)
        datasets = sorted({e.target.split(":", 1)[1] for e in estate.edges
                           if e.relation == "BINDS" and e.source in member_set
                           and not e.target.split(":", 1)[1].startswith("<")})
        tables = sorted({e.target.split(":", 1)[1].split("=", 1)[-1] for e in estate.edges
                         if e.relation == "USES_DB2" and e.source in member_set})
        steps = sorted({e.source.split(":", 1)[1] for e in estate.edges
                        if e.relation == "EXECUTES" and e.target in member_set})
        blockers = sorted({f"{e.source} -[{e.relation}]-> {e.target}" for e in estate.edges
                           if e.proof_state == BLOCKED and e.source in member_set})
        services.append(Service(name, tuple(members), tuple(datasets), tuple(tables), tuple(steps),
                                bool(blockers), tuple(blockers)))

    couplings: list[Coupling] = []
    copybook_users: dict[str, set[str]] = {}
    for edge in estate.edges:
        if edge.relation == "INCLUDES" and edge.source in service_of:
            copybook_users.setdefault(edge.target, set()).add(service_of[edge.source])
    for copybook, users in sorted(copybook_users.items()):
        ordered = sorted(users)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                couplings.append(Coupling(a, b, "SHARED_COPYBOOK", copybook.split(":", 1)[1]))

    step_services: dict[str, set[str]] = {}
    for edge in estate.edges:
        if edge.relation == "EXECUTES" and edge.target in service_of:
            step_services.setdefault(edge.source, set()).add(service_of[edge.target])
    jobs: dict[str, set[str]] = {}
    for step, svcs in step_services.items():
        jobs.setdefault(step.split(":", 1)[1].split(".")[0], set()).update(svcs)
    for job, svcs in sorted(jobs.items()):
        ordered = sorted(svcs)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                couplings.append(Coupling(a, b, "SAME_JOB", job))

    for edge in estate.edges:
        if edge.relation == "FLOWS_TO":
            left = step_services.get(edge.source, set())
            right = step_services.get(edge.target, set())
            for a in sorted(left):
                for b in sorted(right):
                    if a != b:
                        couplings.append(Coupling(a, b, "DATASET_FLOW", edge.evidence))

    couplings = sorted(set(couplings), key=lambda c: (c.source, c.target, c.kind, c.detail))
    return DecompositionPlan(services=services, couplings=couplings)
