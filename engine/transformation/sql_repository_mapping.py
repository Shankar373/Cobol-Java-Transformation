"""SQL mapping facade: DB2 semantic model → Java repository/service.

This module is the lane-owned integration surface between the DB2 SQL
semantic layer (``engine.sql``) and the Java generation layer.

The mapping itself lives in ``engine.sql.repository_model``; this facade is
the stable entry point for the rest of the platform.

Spring integration hook (documented, NOT implemented here):
    ``spring_boot_ir`` owns SpringBoot IR and ``spring_boot_generator``
    owns source emission.  Both are off-limits to this lane.  To render the
    mapped repositories, a future integration should:

    1. consume ``SqlRepositoryMapping`` (repositories + service) produced by
       ``map_sql_model_to_repository``;
    2. translate ``RepositoryMethod.operation`` / ``status_outcomes`` into
       the SpringBoot repository strategy (JPA/JDBC) already supported by
       ``spring_boot_generator``;
    3. map ``ServiceClass`` transaction boundaries (COMMIT/ROLLBACK) onto
       the existing transaction semantics.

    That adapter belongs to the Spring lane and is intentionally not
    implemented here.
"""

from __future__ import annotations

from engine.sql.analyzer import Db2SemanticAnalyzer
from engine.sql.model import Db2SqlModel
from engine.sql.repository_model import (
    DEFAULT_JAVA_TYPE,
    RepositoryClass,
    RepositoryMethod,
    RepositoryMethodParameter,
    ServiceClass,
    ServiceMethod,
    SqlRepositoryMapping,
    map_db2_model_to_repository,
)

__all__ = [
    "DEFAULT_JAVA_TYPE",
    "Db2SemanticAnalyzer",
    "Db2SqlModel",
    "RepositoryClass",
    "RepositoryMethod",
    "RepositoryMethodParameter",
    "ServiceClass",
    "ServiceMethod",
    "SqlRepositoryMapping",
    "map_db2_model_to_repository",
]


def map_sql_model_to_repository(
    model: Db2SqlModel,
    package: str = "com.acme.db2",
    java_type_resolver=None,
) -> SqlRepositoryMapping:
    """Lane-owned facade for semantic model → repository/service mapping."""
    return map_db2_model_to_repository(
        model,
        package=package,
        java_type_resolver=java_type_resolver,
    )