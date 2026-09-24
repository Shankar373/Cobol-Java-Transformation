"""Spring Boot application IR — architecture boundary above Java Application IR.

Defines the intermediate representation for a Spring Boot application
architecture derived from a generic JavaApplication. This model is
domain-neutral: it represents Spring Boot structure independently of
any particular business domain.

Architecture:

    JavaApplication
        ↓
    SpringBootApplication
        ├── SpringBootService (one per JavaProgram with business logic)
        ├── SpringBootRepository (one per unique database resource)
        ├── SpringBootAdapter (one per unique file resource)
        ├── SpringBootTransactionBoundary (per transaction boundary)
        ├── SpringBootConfiguration (application configuration)
        ├── SpringBootEntryPoint (main class)
        └── SpringBootDependency (framework dependencies)

    Spring Boot is an OUTPUT architecture layer.
    It MUST NOT leak backward into COBOL IR or Java IR.

Rules:
    - No COBOL IR imports
    - No domain-specific component naming
    - Controllers only when JavaApplication has explicit API boundary
    - All names derived from JavaApplication metadata
    - Deterministic mapping
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.transformation.java_ir import (
    JavaClass,
    JavaStatement,
    JavaType,
)


# ---------------------------------------------------------------------------
# Spring Boot component types
# ---------------------------------------------------------------------------

class SpringBootComponentType(Enum):
    """Type of Spring Boot component."""
    SERVICE = "SERVICE"
    REPOSITORY = "REPOSITORY"
    ADAPTER = "ADAPTER"
    CONFIGURATION = "CONFIGURATION"
    CONTROLLER = "CONTROLLER"
    COMPONENT = "COMPONENT"


class SpringBootDependencyType(Enum):
    """Type of Spring Boot framework dependency."""
    CORE = "CORE"
    CONTEXT = "CONTEXT"
    WEB = "WEB"
    DATA = "DATA"
    FILE_IO = "FILE_IO"
    TRANSACTION = "TRANSACTION"
    TEST = "TEST"


class SpringBootTransactionType(Enum):
    """Spring Boot transaction boundary type."""
    SERVICE_TRANSACTION = "SERVICE_TRANSACTION"
    REPOSITORY_TRANSACTION = "REPOSITORY_TRANSACTION"
    BATCH_STEP = "BATCH_STEP"
    METHOD_BOUNDARY = "METHOD_BOUNDARY"


class DataAccessStrategy(Enum):
    """Persistence implementation strategy.

    Selected based on explicit JavaApplication evidence.
    Default is UNSPECIFIED — never inferred from capability alone.
    """
    UNSPECIFIED = "UNSPECIFIED"
    JDBC = "JDBC"
    JPA = "JPA"
    MYBATIS = "MYBATIS"
    CUSTOM = "CUSTOM"


class FileAccessStrategy(Enum):
    """File access implementation strategy.

    Selected based on explicit JavaApplication evidence.
    Default is UNSPECIFIED — never inferred from capability alone.
    """
    UNSPECIFIED = "UNSPECIFIED"
    JAVA_IO = "JAVA_IO"
    NIO = "NIO"
    SPRING_RESOURCE = "SPRING_RESOURCE"
    SPRING_INTEGRATION = "SPRING_INTEGRATION"
    CUSTOM = "CUSTOM"


# ---------------------------------------------------------------------------
# Core IR types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpringBootComponent:
    """A Spring Boot component (service, repository, adapter, etc.)."""
    name: str  # component class name (source-derived)
    component_type: SpringBootComponentType = SpringBootComponentType.COMPONENT
    package: str = ""  # target package
    source_program: str = ""  # originating JavaProgram program_id
    source_resource: str = ""  # originating resource name (for adapters/repos)
    implements_interface: bool = False
    is_transactional: bool = False


@dataclass(frozen=True)
class SpringBootServiceMethod:
    """A method implementation within a Spring Boot service.

    Contains structured IR for the method body — not source text.
    All fields are source-derived through Java IR.
    """
    name: str  # method name (source-derived)
    return_type: JavaType  # return type from Java IR
    parameters: tuple[tuple[JavaType, str], ...] = ()  # (type, name) pairs
    body_statements: tuple[JavaStatement, ...] = ()  # structured IR statements
    is_static: bool = False
    exceptions: tuple[str, ...] = ()  # checked exceptions


@dataclass(frozen=True)
class SpringBootService:
    """A Spring Boot service component.

    Maps from a JavaProgram that has business logic, CALL dependencies,
    or file/database resources.
    """
    name: str  # service class name
    package: str = ""  # target package
    source_program: str = ""  # originating JavaProgram program_id
    depends_on: tuple[str, ...] = ()  # service names this depends on
    is_transactional: bool = False
    has_file_operations: bool = False
    has_database_operations: bool = False
    methods: tuple[SpringBootServiceMethod, ...] = ()
    fields: tuple = ()  # tuple of JavaField instances from JavaClass


@dataclass(frozen=True)
class SpringBootRepository:
    """A Spring Boot repository/data-access component.

    Maps from a JavaDatabaseResource. Represents the persistence
    boundary without prescribing JPA/JDBC implementation.
    """
    name: str  # repository class name
    package: str = ""  # target package
    source_resource: str = ""  # originating JavaDatabaseResource name
    table_name: str = ""  # logical table name
    operations: tuple[str, ...] = ()  # SELECT, INSERT, UPDATE, DELETE


@dataclass(frozen=True)
class SpringBootAdapter:
    """A Spring Boot file/resource adapter.

    Maps from a JavaFileResource. Represents the file access
    boundary without prescribing implementation.
    """
    name: str  # adapter class name
    package: str = ""  # target package
    source_resource: str = ""  # originating JavaFileResource name
    access_mode: str = ""  # READ, WRITE, READ_WRITE, APPEND
    is_text: bool = True


@dataclass(frozen=True)
class SpringBootModel:
    """A shared data-model component materialized from a COBOL COPYBOOK.

    Carries the generated model ``JavaClass`` (data holders only: fields
    plus accessors, no business-logic methods, no ``main``). A model is
    NOT a service, repository, or adapter: it never becomes an executable
    entrypoint and never appears in the service dependency graph.
    """
    name: str  # model class name (e.g. "CommonRecord")
    package: str = ""  # target package (e.g. "com.generated.app.model")
    source_copybook: str = ""  # originating COPYBOOK name (upper-cased stem)
    java_class: JavaClass | None = None  # data-holder class IR


@dataclass(frozen=True)
class SpringBootTransactionBoundary:
    """A Spring Boot transaction boundary.

    Maps from JavaTransactionBoundary. Represents the transaction
    scope without prescribing runtime implementation.
    """
    name: str  # transaction identifier
    package: str = ""  # target package
    source_boundary: str = ""  # originating JavaTransactionBoundary name
    transaction_type: SpringBootTransactionType = SpringBootTransactionType.SERVICE_TRANSACTION
    participating_services: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpringBootConfiguration:
    """Spring Boot application configuration.

    Derived from JavaApplication metadata. Domain-neutral.
    Capabilities describe WHAT the application needs.
    Strategies describe HOW it will be implemented.
    They are never inferred from capability alone.
    """
    application_name: str = ""  # from JavaApplication.application_id
    base_package: str = "com.generated.app"  # configurable namespace
    # Capabilities (WHAT)
    has_database: bool = False
    has_file_resources: bool = False
    has_transactions: bool = False
    has_web: bool = False  # only if explicit API boundary exists
    # Implementation strategies (HOW) — default UNSPECIFIED
    data_access_strategy: DataAccessStrategy = DataAccessStrategy.UNSPECIFIED
    file_access_strategy: FileAccessStrategy = FileAccessStrategy.UNSPECIFIED


@dataclass(frozen=True)
class SpringBootEntryPoint:
    """Spring Boot application entry point.

    The main class with @SpringBootApplication annotation.
    """
    class_name: str = "Application"
    package: str = ""  # target package
    application_name: str = ""  # from JavaApplication.application_id
    # Selected service executed by the runner. Empty means legacy behaviour
    # (invoke every service's first method). When set to a known service,
    # the runner invokes ONLY that service; callees run via service calls.
    selected_service: str = ""


@dataclass(frozen=True)
class SpringBootDependency:
    """A Spring Boot framework dependency."""
    name: str  # dependency artifact name
    dependency_type: SpringBootDependencyType = SpringBootDependencyType.CORE
    version: str = ""  # optional version constraint


@dataclass(frozen=True)
class SpringBootPackage:
    """A package in the generated Spring Boot project."""
    name: str  # full package name
    purpose: str = ""  # description of package purpose


# ---------------------------------------------------------------------------
# Database implementation IR
# ---------------------------------------------------------------------------

class SpringBootDatabaseOperationType(Enum):
    """Database operation type — maps from JavaSqlOperationType."""
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    CURSOR_OPEN = "CURSOR_OPEN"
    CURSOR_FETCH = "CURSOR_FETCH"
    CURSOR_CLOSE = "CURSOR_CLOSE"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"


@dataclass(frozen=True)
class SpringBootRepositoryMethod:
    """A method within a repository implementation.

    Represents a single database operation.
    All fields are source-derived — not invented.
    """
    name: str  # method name (source-derived)
    operation_type: SpringBootDatabaseOperationType
    return_type: JavaType  # return type from Java IR
    parameters: tuple[tuple[JavaType, str], ...] = ()  # (type, name) pairs
    table_name: str = ""  # target table/resource
    columns: tuple[str, ...] = ()  # columns involved
    is_static: bool = False


@dataclass(frozen=True)
class SpringBootRepositoryImplementation:
    """A repository implementation with strategy-specific details.

    Maps from SpringBootRepository + DataAccessStrategy.
    Represents WHAT operations are needed and HOW they will be implemented.
    """
    name: str  # implementation class name
    package: str = ""  # target package
    source_repository: str = ""  # originating SpringBootRepository name
    strategy: DataAccessStrategy = DataAccessStrategy.UNSPECIFIED
    methods: tuple[SpringBootRepositoryMethod, ...] = ()
    table_name: str = ""  # logical table name
    implements_interface: bool = True  # whether to implement a repository interface


# ---------------------------------------------------------------------------
# File implementation IR
# ---------------------------------------------------------------------------

class SpringBootFileOperationType(Enum):
    """File operation type — derived from COBOL file operations."""
    OPEN = "OPEN"
    READ = "READ"
    WRITE = "WRITE"
    CLOSE = "CLOSE"
    REWRITE = "REWRITE"
    DELETE = "DELETE"


@dataclass(frozen=True)
class SpringBootAdapterMethod:
    """A method within a file adapter implementation.

    Represents a single file operation.
    All fields are source-derived — not invented.
    """
    name: str  # method name (source-derived)
    operation_type: SpringBootFileOperationType
    return_type: JavaType  # return type from Java IR
    parameters: tuple[tuple[JavaType, str], ...] = ()  # (type, name) pairs
    is_static: bool = False


@dataclass(frozen=True)
class SpringBootAdapterImplementation:
    """A file adapter implementation with strategy-specific details.

    Maps from SpringBootAdapter + FileAccessStrategy.
    Represents WHAT operations are needed and HOW they will be implemented.
    """
    name: str  # implementation class name
    package: str = ""  # target package
    source_adapter: str = ""  # originating SpringBootAdapter name
    strategy: FileAccessStrategy = FileAccessStrategy.UNSPECIFIED
    methods: tuple[SpringBootAdapterMethod, ...] = ()
    source_resource: str = ""  # logical resource name
    access_mode: str = ""  # READ, WRITE, READ_WRITE, APPEND
    record_delimiter: str | None = None  # delimiter from IR
    record_width: int | None = None  # RECORD CONTAINS n CHARACTERS
    file_organization: str = "SEQUENTIAL"  # SEQUENTIAL, INDEXED, RELATIVE
    record_key: str = ""  # RECORD KEY IS field
    implements_interface: bool = True  # whether to implement an adapter interface


# ---------------------------------------------------------------------------
# Top-level application
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpringBootApplication:
    """A complete Spring Boot application architecture model.

    Derived from a JavaApplication. Represents the architectural
    boundary of a Spring Boot application without implementation details.

    This is the top-level container that a Spring Boot source generator consumes.
    """
    application_id: str  # derived from JavaApplication.application_id
    base_package: str = "com.generated.app"
    # Components
    services: tuple[SpringBootService, ...] = ()
    repositories: tuple[SpringBootRepository, ...] = ()
    adapters: tuple[SpringBootAdapter, ...] = ()
    # Shared copybook data models (M7). Data holders only — never services,
    # never entrypoints. Defaults to empty: existing callers are unaffected.
    models: tuple[SpringBootModel, ...] = ()
    transaction_boundaries: tuple[SpringBootTransactionBoundary, ...] = ()
    # Implementations (derived from repositories/adapters + strategy)
    repository_implementations: tuple[SpringBootRepositoryImplementation, ...] = ()
    adapter_implementations: tuple[SpringBootAdapterImplementation, ...] = ()
    # Configuration
    configuration: SpringBootConfiguration | None = None
    entry_point: SpringBootEntryPoint | None = None
    # Dependencies
    dependencies: tuple[SpringBootDependency, ...] = ()
    # Package structure
    packages: tuple[SpringBootPackage, ...] = ()
    # Source traceability
    source_application_id: str = ""  # JavaApplication.application_id

    def get_service(self, name: str) -> SpringBootService | None:
        """Find a service by name."""
        for s in self.services:
            if s.name == name:
                return s
        return None

    def get_repository(self, name: str) -> SpringBootRepository | None:
        """Find a repository by name."""
        for r in self.repositories:
            if r.name == name:
                return r
        return None

    def get_adapter(self, name: str) -> SpringBootAdapter | None:
        """Find an adapter by name."""
        for a in self.adapters:
            if a.name == name:
                return a
        return None

    def get_all_components(self) -> list[SpringBootComponent]:
        """Get all components as a unified list."""
        components: list[SpringBootComponent] = []
        for s in self.services:
            components.append(SpringBootComponent(
                name=s.name,
                component_type=SpringBootComponentType.SERVICE,
                package=s.package,
                source_program=s.source_program,
                is_transactional=s.is_transactional,
            ))
        for r in self.repositories:
            components.append(SpringBootComponent(
                name=r.name,
                component_type=SpringBootComponentType.REPOSITORY,
                package=r.package,
                source_resource=r.source_resource,
            ))
        for a in self.adapters:
            components.append(SpringBootComponent(
                name=a.name,
                component_type=SpringBootComponentType.ADAPTER,
                package=a.package,
                source_resource=a.source_resource,
            ))
        return components

    def validate(self) -> list[str]:
        """Validate the Spring Boot application architecture.

        Returns list of validation errors.
        """
        errors: list[str] = []

        # Check for duplicate component names
        seen_names: set[str] = set()
        for s in self.services:
            if s.name in seen_names:
                errors.append(f"Duplicate service name: {s.name}")
            seen_names.add(s.name)
        for r in self.repositories:
            if r.name in seen_names:
                errors.append(f"Duplicate repository name: {r.name}")
            seen_names.add(r.name)
        for a in self.adapters:
            if a.name in seen_names:
                errors.append(f"Duplicate adapter name: {a.name}")
            seen_names.add(a.name)
        for m in self.models:
            if m.name in seen_names:
                errors.append(f"Duplicate model name: {m.name}")
            seen_names.add(m.name)

        # Models must be data holders, never executable components.
        for m in self.models:
            if m.java_class is not None and any(
                method.name.lower() == "main"
                for method in m.java_class.methods
            ):
                errors.append(f"Model must not define main: {m.name}")

        # Check for unresolved service dependencies
        service_names = {s.name for s in self.services}
        for s in self.services:
            for dep in s.depends_on:
                if dep not in service_names:
                    errors.append(f"Unresolved service dependency: {s.name} -> {dep}")

        # Check entry point
        if self.entry_point is None:
            errors.append("Missing entry point")

        # Check configuration
        if self.configuration is None:
            errors.append("Missing configuration")

        return errors

    def detect_cycles(self) -> list[list[str]]:
        """Detect cycles in the service dependency graph.

        Returns list of cycles found. Empty list means no cycles.
        """
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []

        # Build adjacency from services
        adj: dict[str, list[str]] = {}
        for s in self.services:
            adj[s.name] = list(s.depends_on)

        def _dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for target in adj.get(node, []):
                if target not in visited:
                    _dfs(target)
                elif target in rec_stack:
                    cycle_start = path.index(target)
                    cycles.append(path[cycle_start:] + [target])

            path.pop()
            rec_stack.discard(node)

        for s in self.services:
            if s.name not in visited:
                _dfs(s.name)

        return cycles
