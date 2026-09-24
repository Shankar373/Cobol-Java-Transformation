"""Java repository / service representation for DB2 SQL.

Maps the lane-owned ``Db2SqlModel`` into a generator-agnostic Java
repository/service representation.  This is NOT the Spring IR (which is
owned elsewhere and out of scope); it is the SQL mapping surface that a
future generator integration can consume through the documented hook.

Determinism: method names, parameter order, return types and status
outcomes are derived purely from the semantic model in a fixed order.

Type resolution: host variable Java types originate in COBOL data
definitions, which live outside this lane.  A ``java_type_resolver``
callable may supply exact types; the default resolver returns ``String``
and flags the caveat instead of inventing types.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from engine.sql.model import (
    Db2BindingDirection,
    Db2SqlModel,
)
from engine.transformation.ir import SqlStatementType

#: Default Java type when no resolver is supplied (documented caveat).
DEFAULT_JAVA_TYPE = "String"

_VERBS = {
    SqlStatementType.SELECT.value: "find",
    SqlStatementType.INSERT.value: "insert",
    SqlStatementType.UPDATE.value: "update",
    SqlStatementType.DELETE.value: "delete",
    "OPEN_CURSOR": "open",
    "FETCH_CURSOR": "fetch",
    "CLOSE_CURSOR": "close",
    "COMMIT": "commit",
    "ROLLBACK": "rollback",
}


@dataclass(frozen=True)
class RepositoryMethodParameter:
    name: str
    type_name: str
    direction: Db2BindingDirection
    nullable: bool = False


@dataclass(frozen=True)
class RepositoryMethod:
    """One SQL statement mapped to a repository method."""

    name: str
    operation: str                          # SqlStatementType.value
    table_name: str
    sql: str                                # original embedded SQL text
    parameters: tuple[RepositoryMethodParameter, ...] = ()
    return_type: str = "void"
    status_outcomes: tuple[str, ...] = ()   # deterministic status labels
    is_cursor_operation: bool = False
    cursor_name: str = ""


@dataclass(frozen=True)
class RepositoryClass:
    table_name: str
    class_name: str
    package_name: str
    methods: tuple[RepositoryMethod, ...] = ()


@dataclass(frozen=True)
class ServiceMethod:
    name: str
    return_type: str = "void"
    delegated_method: str = ""              # repository method name
    transaction_boundary: str = ""          # COMMIT / ROLLBACK / ""


@dataclass(frozen=True)
class ServiceClass:
    """Program-scoped service: repository delegation + transaction control."""

    class_name: str
    package_name: str
    package: str = ""
    methods: tuple[ServiceMethod, ...] = ()


@dataclass(frozen=True)
class SqlRepositoryMapping:
    """Complete repository/service mapping of a DB2 SQL program."""

    program_id: str
    repositories: tuple[RepositoryClass, ...] = ()
    service: ServiceClass | None = None
    host_variables: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


_TypeResolver = Callable[[str], str] | None


def _to_method_name(verb: str, subject: str) -> str:
    if not subject:
        return verb
    return verb + subject[0].upper() + subject[1:]


def _to_camel(name: str) -> str:
    words = re.split(r"[^A-Za-z0-9]+", name.lower())
    if not words or not words[0]:
        return "entity"
    result = words[0]
    for word in words[1:]:
        if word:
            result += word[0].upper() + word[1:]
    return result


def _to_class_name(table_name: str) -> str:
    camel = _to_camel(table_name)
    return camel[0].upper() + camel[1:] + "Repository"


def _status_outcomes(stmt) -> tuple[str, ...]:
    outcomes: list[str] = []
    for status in stmt.possible_statuses:
        if status.sqlcode == 0:
            outcomes.append("SUCCESS")
        elif status.sqlcode == 100:
            outcomes.append("NO_DATA")
        elif status.sqlcode == -811:
            outcomes.append("TOO_MANY_ROWS")
        elif status.sqlcode == -803:
            outcomes.append("DUPLICATE_KEY")
    return tuple(outcomes)


def _return_type(stmt) -> str:
    if stmt.statement_type in ("INSERT", "UPDATE", "DELETE"):
        return "int"
    if stmt.statement_type == "SELECT" and stmt.output_host_variables:
        return "Row"
    if stmt.statement_type == "SELECT":
        return "List<Row>"
    if stmt.statement_type == "FETCH_CURSOR":
        return "Row"
    if stmt.statement_type in ("OPEN_CURSOR", "CLOSE_CURSOR"):
        return "void"
    return "void"


def map_db2_model_to_repository(
    model: Db2SqlModel,
    package: str = "com.acme.db2",
    java_type_resolver: _TypeResolver = None,
) -> SqlRepositoryMapping:
    """Deterministically map a DB2 semantic model to repository/service IR.

    ``java_type_resolver`` receives a host variable name and returns the
    Java type name.  If None, ``DEFAULT_JAVA_TYPE`` is used for every
    parameter and a note records the caveat.
    """
    resolver = java_type_resolver or (lambda name: DEFAULT_JAVA_TYPE)

    # Group repository methods by table.
    table_statements: dict[str, list] = {}
    service_boundaries: list[str] = []          # COMMIT / ROLLBACK in order
    host_variables: list[str] = []
    notes: list[str] = []
    counters: dict[str, int] = {}

    def resolve_parameter(
        hv,
    ) -> RepositoryMethodParameter:
        """Resolve a per-statement host variable into a method parameter.

        Direction comes from the per-statement occurrence (not the program
        aggregate); Java type comes from the resolver hook.
        """
        return RepositoryMethodParameter(
            name=hv.name,
            type_name=resolver(hv.name),
            direction=hv.direction,
            nullable=hv.uses_indicator,
        )

    for stmt in model.statements:
        cursor_name = stmt.cursor_name
        table_name = ""
        if stmt.table_refs:
            table_name = stmt.table_refs[0].table_name
        elif stmt.is_cursor_operation:
            table_name = "cursor"
        elif stmt.is_transaction_boundary:
            table_name = "txn"

        if stmt.is_transaction_boundary:
            boundary = "COMMIT" if stmt.statement_type == "COMMIT" else "ROLLBACK"
            service_boundaries.append(boundary)
            continue

        subject = _to_camel(table_name)
        verb = _VERBS.get(stmt.statement_type, "execute")
        if stmt.is_cursor_operation and stmt.cursor_name:
            subject = _to_camel(stmt.cursor_name)
        if stmt.statement_type == SqlStatementType.SELECT.value and not stmt.output_host_variables:
            verb = "query"

        key = f"{verb}:{subject}"
        counter = counters.get(key, 0) + 1
        counters[key] = counter
        method_name = _to_method_name(verb, subject)
        if counter > 1:
            method_name = f"{method_name}{counter}"

        operation = stmt.statement_type
        if operation == SqlStatementType.SELECT.value and stmt.output_host_variables:
            operation = "SELECT_INTO"

        params: list[RepositoryMethodParameter] = []
        for hv in stmt.host_variables:
            if hv.name not in host_variables:
                host_variables.append(hv.name)
            # Pure outputs are returns, not call parameters.
            if hv.direction == Db2BindingDirection.OUTPUT:
                continue
            params.append(resolve_parameter(hv))

        method = RepositoryMethod(
            name=method_name,
            operation=operation,
            table_name=table_name,
            sql=stmt.raw_sql.strip(),
            parameters=tuple(params),
            return_type=_return_type(stmt),
            status_outcomes=_status_outcomes(stmt),
            is_cursor_operation=stmt.is_cursor_operation,
            cursor_name=cursor_name,
        )
        table_statements.setdefault(table_name, []).append(method)

    repositories: list[RepositoryClass] = []
    for table_name in sorted(table_statements):
        class_name = _to_class_name(table_name)
        repositories.append(
            RepositoryClass(
                table_name=table_name,
                class_name=class_name,
                package_name=package,
                methods=tuple(table_statements[table_name]),
            )
        )

    service_methods: list[ServiceMethod] = []
    for table_name in sorted(table_statements):
        for method in table_statements[table_name]:
            service_methods.append(
                ServiceMethod(
                    name=method.name,
                    return_type=method.return_type,
                    delegated_method=method.name,
                )
            )
    for boundary in service_boundaries:
        service_methods.append(
            ServiceMethod(
                name="commit" if boundary == "COMMIT" else "rollback",
                return_type="void",
                transaction_boundary=boundary,
            )
        )

    service = ServiceClass(
        class_name=f"{_to_class_name(model.program_id).removesuffix('Repository')}Service",
        package_name=package,
        package=package,
        methods=tuple(service_methods),
    )

    notes.append(
        f"host variable Java types defaulted to {DEFAULT_JAVA_TYPE}; COBOL "
        "PIC resolution lives outside the SQL lane (integration hook required)"
    )

    return SqlRepositoryMapping(
        program_id=model.program_id,
        repositories=tuple(repositories),
        service=service,
        host_variables=tuple(host_variables),
        notes=tuple(notes),
    )