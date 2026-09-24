"""Java Application IR → Spring Boot Application IR mapper.

Transforms a domain-neutral JavaApplication into a Spring Boot
application architecture. This is a one-way transformation:

    JavaApplication → SpringBootApplication

Rules:
    - No COBOL IR imports
    - No domain-specific naming
    - Deterministic mapping
    - Controllers only when explicit API boundary exists
    - All names derived from JavaApplication metadata
"""

from __future__ import annotations

from engine.transformation.java_ir import (
    JavaApplication,
    JavaBasicType,
    JavaBlock,
    JavaClass,
    JavaDependencyType,
    JavaDoWhile,
    JavaFor,
    JavaIf,
    JavaMethodCall,
    JavaMethodCallStatement,
    JavaStatement,
    JavaSwitch,
    JavaTransactionType,
    JavaTryCatch,
    JavaType,
    JavaVariableRef,
    JavaWhile,
)
from engine.transformation.spring_boot_ir import (
    DataAccessStrategy,
    FileAccessStrategy,
    SpringBootApplication,
    SpringBootAdapter,
    SpringBootAdapterImplementation,
    SpringBootAdapterMethod,
    SpringBootConfiguration,
    SpringBootDatabaseOperationType,
    SpringBootDependency,
    SpringBootDependencyType,
    SpringBootEntryPoint,
    SpringBootFileOperationType,
    SpringBootModel,
    SpringBootPackage,
    SpringBootRepository,
    SpringBootRepositoryImplementation,
    SpringBootRepositoryMethod,
    SpringBootService,
    SpringBootServiceMethod,
    SpringBootTransactionBoundary,
    SpringBootTransactionType,
)


def map_java_application_to_spring_boot(
    application: JavaApplication,
    base_package: str = "com.generated.app",
    entry_program: str = "",
    copybook_models=(),
) -> SpringBootApplication:
    """Map a JavaApplication to a SpringBootApplication.

    This is the primary mapping function. It is deterministic,
    domain-neutral, and free from COBOL IR dependencies.

    Architecture derivation rules:
    - Each JavaProgram with business logic → SpringBootService
    - Each unique JavaDatabaseResource → SpringBootRepository
    - Each unique JavaFileResource → SpringBootAdapter
    - Each JavaTransactionBoundary → SpringBootTransactionBoundary
    - Framework dependencies derived from resource capabilities
    - Controllers only if explicit API boundary present (not assumed)
    - Repository/Adapter implementations derived from strategy + operations
    - entry_program selects the single service the entry point runs
    - copybook_models are carried as SpringBootModel data holders
    """
    # Map services from programs
    services = _map_services(application, base_package)

    # Map repositories from database resources
    repositories = _map_repositories(application, base_package)

    # Map adapters from file resources
    adapters = _map_adapters(application, base_package)

    # Map transaction boundaries
    transaction_boundaries = _map_transactions(application, base_package, services)

    # Derive configuration
    configuration = _derive_configuration(application, base_package, repositories, adapters, transaction_boundaries)

    # Map repository implementations
    repo_implementations = _map_repository_implementations(repositories, configuration, base_package)

    # Map adapter implementations
    adapter_implementations = _map_adapter_implementations(adapters, configuration, base_package)

    # Create entry point (selected service from entry_program)
    entry_point = _derive_entry_point(application, base_package, entry_program)

    # Carry shared copybook models (data holders)
    models = tuple(_to_spring_model(m) for m in copybook_models)

    # Derive framework dependencies
    dependencies = _derive_dependencies(repositories, adapters, transaction_boundaries)

    # Derive package structure
    packages = _derive_packages(base_package, services, repositories, adapters)

    return SpringBootApplication(
        application_id=application.application_id,
        base_package=base_package,
        services=tuple(services),
        repositories=tuple(repositories),
        adapters=tuple(adapters),
        transaction_boundaries=tuple(transaction_boundaries),
        repository_implementations=tuple(repo_implementations),
        adapter_implementations=tuple(adapter_implementations),
        configuration=configuration,
        entry_point=entry_point,
        models=models,
        dependencies=tuple(dependencies),
        packages=tuple(packages),
        source_application_id=application.application_id,
    )


def _to_spring_model(java_class: JavaClass | object) -> SpringBootModel:
    """Wrap a copybook model JavaClass as a SpringBootModel."""
    name = getattr(java_class, "name", "")
    package = getattr(java_class, "package", "")
    source_copybook = getattr(java_class, "source_copybook", "")
    cls = java_class if isinstance(java_class, JavaClass) else None
    return SpringBootModel(
        name=name,
        package=package,
        source_copybook=source_copybook,
        java_class=cls,
    )


def _map_services(
    application: JavaApplication,
    base_package: str,
) -> list[SpringBootService]:
    """Map JavaPrograms to SpringBootServices.

    Each program with a class becomes a service.
    CALL dependencies become service dependency edges.
    Methods from JavaClass are mapped to SpringBootServiceMethod.
    Static CALL statements targeting dependencies become bean calls.
    """
    services: list[SpringBootService] = []
    service_package = f"{base_package}.service"

    for program in application.programs:
        if program.java_class is None:
            continue

        # Determine service name from program ID
        service_name = _to_class_name(program.program_id)

        # Find CALL dependencies to other programs
        depends_on: list[str] = []
        for dep in application.dependencies:
            if (dep.source == program.program_id
                    and dep.dependency_type in (
                        JavaDependencyType.METHOD_CALL,
                        JavaDependencyType.INTERFACE_CALL,
                        JavaDependencyType.SERVICE_CALL,
                    )):
                target_name = _to_class_name(dep.target)
                if target_name not in depends_on:
                    depends_on.append(target_name)

        # Check capabilities
        has_file_ops = len(program.file_resources) > 0
        has_db_ops = len(program.database_resources) > 0
        has_transactions = len(program.transaction_boundaries) > 0

        # Map methods from JavaClass; rewrite static CALL → bean reference
        methods = _map_methods(program.java_class, depends_on)

        # Map fields from JavaClass
        fields = tuple(program.java_class.fields) if program.java_class.fields else ()

        services.append(SpringBootService(
            name=service_name,
            package=service_package,
            source_program=program.program_id,
            depends_on=tuple(depends_on),
            is_transactional=has_transactions,
            has_file_operations=has_file_ops,
            has_database_operations=has_db_ops,
            methods=tuple(methods),
            fields=fields,
        ))

    return services


def _rewrite_static_calls(stmt: JavaStatement, beans: dict[str, str]) -> JavaStatement:
    """Rewrite static class calls into instance bean calls.

    ``beans`` maps service class name → injected field name
    (e.g. {"Claims": "claims"}). Nested control-flow bodies are walked.
    """
    if isinstance(stmt, JavaMethodCallStatement):
        call = stmt.call
        if call.is_static and call.class_name in beans:
            return JavaMethodCallStatement(
                call=JavaMethodCall(
                    object_ref=JavaVariableRef(name=beans[call.class_name]),
                    method_name=call.method_name,
                    arguments=call.arguments,
                    is_static=False,
                )
            )
        return stmt
    if isinstance(stmt, JavaIf):
        return JavaIf(
            condition=stmt.condition,
            then_body=tuple(_rewrite_static_calls(s, beans) for s in stmt.then_body),
            else_body=tuple(_rewrite_static_calls(s, beans) for s in stmt.else_body),
        )
    if isinstance(stmt, JavaWhile):
        return JavaWhile(
            condition=stmt.condition,
            body=tuple(_rewrite_static_calls(s, beans) for s in stmt.body),
        )
    if isinstance(stmt, JavaDoWhile):
        return JavaDoWhile(
            condition=stmt.condition,
            body=tuple(_rewrite_static_calls(s, beans) for s in stmt.body),
        )
    if isinstance(stmt, JavaFor):
        return JavaFor(
            init=_rewrite_static_calls(stmt.init, beans) if stmt.init else None,
            condition=stmt.condition,
            update=_rewrite_static_calls(stmt.update, beans) if stmt.update else None,
            body=tuple(_rewrite_static_calls(s, beans) for s in stmt.body),
        )
    if isinstance(stmt, JavaBlock):
        return JavaBlock(
            statements=tuple(_rewrite_static_calls(s, beans) for s in stmt.statements),
        )
    if isinstance(stmt, JavaTryCatch):
        return JavaTryCatch(
            try_body=tuple(_rewrite_static_calls(s, beans) for s in stmt.try_body),
            catch_type=stmt.catch_type,
            catch_var=stmt.catch_var,
            catch_body=tuple(_rewrite_static_calls(s, beans) for s in stmt.catch_body),
            finally_body=tuple(_rewrite_static_calls(s, beans) for s in stmt.finally_body),
        )
    if isinstance(stmt, JavaSwitch):
        return JavaSwitch(
            expression=stmt.expression,
            cases=tuple(
                (case, tuple(_rewrite_static_calls(s, beans) for s in body))
                for case, body in stmt.cases
            ),
            default_body=tuple(_rewrite_static_calls(s, beans) for s in stmt.default_body),
        )
    return stmt


def _map_methods(java_class, depends_on=()) -> list[SpringBootServiceMethod]:
    """Map JavaClass methods to SpringBootServiceMethod instances.

    Skips the 'main' method — Spring Boot services don't have main.
    Skips constructors — handled separately.
    Static CALL statements targeting depends_on services are rewritten
    to instance bean calls (object_ref = camelCase field name).
    """
    beans = {name: _to_field_name(name) for name in depends_on}
    methods: list[SpringBootServiceMethod] = []
    for method in java_class.methods:
        # Skip main and constructors
        if method.name == "main":
            continue
        # Convert JavaParameter tuples to (JavaType, name) tuples
        params = tuple((p.java_type, p.name) for p in method.parameters)
        body = tuple(_rewrite_static_calls(s, beans) for s in method.body_statements)
        methods.append(SpringBootServiceMethod(
            name=method.name,
            return_type=method.return_type,
            parameters=params,
            body_statements=body,
            is_static=method.is_static,
            exceptions=method.exceptions,
        ))
    return methods


def _to_field_name(class_name: str) -> str:
    """Convert PascalCase class name to camelCase field name."""
    if not class_name:
        return ""
    return class_name[0].lower() + class_name[1:]


def _map_repositories(
    application: JavaApplication,
    base_package: str,
) -> list[SpringBootRepository]:
    """Map JavaDatabaseResources to SpringBootRepositories.

    Each unique database resource becomes a repository.
    """
    repositories: list[SpringBootRepository] = []
    repo_package = f"{base_package}.repository"
    seen: set[str] = set()

    # Collect from shared resources
    for res in application.shared_database_resources:
        if res.name not in seen:
            seen.add(res.name)
            repo_name = _to_class_name(res.name) + "Repository"
            operations = (res.operation.value,)
            repositories.append(SpringBootRepository(
                name=repo_name,
                package=repo_package,
                source_resource=res.name,
                table_name=res.name,
                operations=operations,
            ))

    # Collect from per-program resources
    for program in application.programs:
        for res in program.database_resources:
            if res.name not in seen:
                seen.add(res.name)
                repo_name = _to_class_name(res.name) + "Repository"
                operations = (res.operation.value,)
                repositories.append(SpringBootRepository(
                    name=repo_name,
                    package=repo_package,
                    source_resource=res.name,
                    table_name=res.name,
                    operations=operations,
                ))

    return repositories


def _map_adapters(
    application: JavaApplication,
    base_package: str,
) -> list[SpringBootAdapter]:
    """Map JavaFileResources to SpringBootAdapters.

    Each unique file resource becomes an adapter.
    """
    adapters: list[SpringBootAdapter] = []
    adapter_package = f"{base_package}.adapter"
    seen: set[str] = set()

    # Collect from shared resources
    for res in application.shared_file_resources:
        if res.name not in seen:
            seen.add(res.name)
            adapter_name = _to_class_name(res.name) + "Adapter"
            adapters.append(SpringBootAdapter(
                name=adapter_name,
                package=adapter_package,
                source_resource=res.name,
                access_mode=res.access_mode.value,
                is_text=res.is_text,
            ))

    # Collect from per-program resources
    for program in application.programs:
        for res in program.file_resources:
            if res.name not in seen:
                seen.add(res.name)
                adapter_name = _to_class_name(res.name) + "Adapter"
                adapters.append(SpringBootAdapter(
                    name=adapter_name,
                    package=adapter_package,
                    source_resource=res.name,
                    access_mode=res.access_mode.value,
                    is_text=res.is_text,
                ))

    return adapters


def _map_transactions(
    application: JavaApplication,
    base_package: str,
    services: list[SpringBootService],
) -> list[SpringBootTransactionBoundary]:
    """Map JavaTransactionBoundaries to SpringBootTransactionBoundaries."""
    boundaries: list[SpringBootTransactionBoundary] = []
    tx_package = f"{base_package}.config"
    seen: set[str] = set()

    for res in application.shared_transaction_boundaries:
        if res.name not in seen:
            seen.add(res.name)
            tx_type = _map_transaction_type(res.transaction_type)
            participating = _find_participating_services(res.name, application, services)
            boundaries.append(SpringBootTransactionBoundary(
                name=res.name,
                package=tx_package,
                source_boundary=res.name,
                transaction_type=tx_type,
                participating_services=tuple(participating),
            ))

    for program in application.programs:
        for res in program.transaction_boundaries:
            if res.name not in seen:
                seen.add(res.name)
                tx_type = _map_transaction_type(res.transaction_type)
                participating = _find_participating_services(res.name, application, services)
                boundaries.append(SpringBootTransactionBoundary(
                    name=res.name,
                    package=tx_package,
                    source_boundary=res.name,
                    transaction_type=tx_type,
                    participating_services=tuple(participating),
                ))

    return boundaries


def _derive_configuration(
    application: JavaApplication,
    base_package: str,
    repositories: list[SpringBootRepository],
    adapters: list[SpringBootAdapter],
    transactions: list[SpringBootTransactionBoundary],
) -> SpringBootConfiguration:
    """Derive Spring Boot configuration from application capabilities."""
    return SpringBootConfiguration(
        application_name=application.application_id,
        base_package=base_package,
        has_database=len(repositories) > 0,
        has_file_resources=len(adapters) > 0,
        has_transactions=len(transactions) > 0,
        has_web=False,  # Never assumed — requires explicit API boundary
    )


def _derive_entry_point(
    application: JavaApplication,
    base_package: str,
    entry_program: str = "",
) -> SpringBootEntryPoint:
    """Derive Spring Boot entry point from application.

    ``entry_program`` is the selected service (COBOL program-id or class
    name); when empty, the entry point invokes all services.
    """
    selected = _to_class_name(entry_program) if entry_program else ""
    return SpringBootEntryPoint(
        class_name="Application",
        package=base_package,
        application_name=application.application_id,
        selected_service=selected,
    )


def _derive_dependencies(
    repositories: list[SpringBootRepository],
    adapters: list[SpringBootAdapter],
    transactions: list[SpringBootTransactionBoundary],
) -> list[SpringBootDependency]:
    """Derive framework dependencies from capabilities.

    Dependencies are capability-driven, not assumed.
    No specific persistence or file framework is selected.
    The strategy is UNSPECIFIED — implementation chosen later.
    """
    deps: list[SpringBootDependency] = []

    # Core always present
    deps.append(SpringBootDependency(
        name="spring-boot-starter",
        dependency_type=SpringBootDependencyType.CORE,
    ))
    deps.append(SpringBootDependency(
        name="spring-context",
        dependency_type=SpringBootDependencyType.CONTEXT,
    ))

    # Database → generic persistence boundary (NOT JPA)
    if repositories:
        deps.append(SpringBootDependency(
            name="spring-persistence",
            dependency_type=SpringBootDependencyType.DATA,
        ))

    # File I/O → generic file boundary (NOT Spring Integration)
    if adapters:
        deps.append(SpringBootDependency(
            name="spring-file-io",
            dependency_type=SpringBootDependencyType.FILE_IO,
        ))

    # Transactions → spring-tx
    if transactions:
        deps.append(SpringBootDependency(
            name="spring-tx",
            dependency_type=SpringBootDependencyType.TRANSACTION,
        ))

    return deps


def _derive_packages(
    base_package: str,
    services: list[SpringBootService],
    repositories: list[SpringBootRepository],
    adapters: list[SpringBootAdapter],
) -> list[SpringBootPackage]:
    """Derive package structure from components."""
    packages: list[SpringBootPackage] = []

    packages.append(SpringBootPackage(
        name=base_package,
        purpose="Application root",
    ))

    if services:
        packages.append(SpringBootPackage(
            name=f"{base_package}.service",
            purpose="Business logic services",
        ))

    if repositories:
        packages.append(SpringBootPackage(
            name=f"{base_package}.repository",
            purpose="Data access repositories",
        ))

    if adapters:
        packages.append(SpringBootPackage(
            name=f"{base_package}.adapter",
            purpose="File/resource adapters",
        ))

    packages.append(SpringBootPackage(
        name=f"{base_package}.config",
        purpose="Configuration classes",
    ))

    packages.append(SpringBootPackage(
        name=f"{base_package}.model",
        purpose="Domain model",
    ))

    return packages


# ---------------------------------------------------------------------------
# Implementation mapping
# ---------------------------------------------------------------------------

def _map_repository_implementations(
    repositories: list[SpringBootRepository],
    configuration: SpringBootConfiguration,
    base_package: str,
) -> list[SpringBootRepositoryImplementation]:
    """Map repositories to implementation IR based on strategy.

    For UNSPECIFIED strategy: generate abstract boundary.
    For explicit strategies: generate corresponding implementation.
    """
    impl_package = f"{base_package}.repository.impl"
    implementations: list[SpringBootRepositoryImplementation] = []

    strategy = configuration.data_access_strategy if configuration else DataAccessStrategy.UNSPECIFIED

    for repo in repositories:
        # Map operations to methods
        methods = _derive_repository_methods(repo)

        impl_name = f"{repo.name}Impl" if strategy != DataAccessStrategy.UNSPECIFIED else f"Abstract{repo.name}"

        implementations.append(SpringBootRepositoryImplementation(
            name=impl_name,
            package=impl_package if strategy != DataAccessStrategy.UNSPECIFIED else repo.package,
            source_repository=repo.name,
            strategy=strategy,
            methods=tuple(methods),
            table_name=repo.table_name,
            implements_interface=True,
        ))

    return implementations


def _derive_repository_methods(
    repo: SpringBootRepository,
) -> list[SpringBootRepositoryMethod]:
    """Derive repository methods from operations."""
    methods: list[SpringBootRepositoryMethod] = []

    op_type_map = {
        "SELECT": SpringBootDatabaseOperationType.SELECT,
        "INSERT": SpringBootDatabaseOperationType.INSERT,
        "UPDATE": SpringBootDatabaseOperationType.UPDATE,
        "DELETE": SpringBootDatabaseOperationType.DELETE,
    }

    for op in repo.operations:
        op_type = op_type_map.get(op.upper(), SpringBootDatabaseOperationType.SELECT)
        method_name = f"{op.lower()}By{repo.table_name.title().replace('_', '')}"
        methods.append(SpringBootRepositoryMethod(
            name=method_name,
            operation_type=op_type,
            return_type=JavaType(basic_type=JavaBasicType.OBJECT),
            table_name=repo.table_name,
            columns=(),
        ))

    return methods


def _map_adapter_implementations(
    adapters: list[SpringBootAdapter],
    configuration: SpringBootConfiguration,
    base_package: str,
) -> list[SpringBootAdapterImplementation]:
    """Map adapters to implementation IR based on strategy.

    For UNSPECIFIED strategy: generate abstract boundary.
    For explicit strategies: generate corresponding implementation.
    """
    impl_package = f"{base_package}.adapter.impl"
    implementations: list[SpringBootAdapterImplementation] = []

    strategy = configuration.file_access_strategy if configuration else FileAccessStrategy.UNSPECIFIED

    for adapter in adapters:
        # Map operations to methods
        methods = _derive_adapter_methods(adapter)

        impl_name = f"{adapter.name}Impl" if strategy != FileAccessStrategy.UNSPECIFIED else f"Abstract{adapter.name}"

        implementations.append(SpringBootAdapterImplementation(
            name=impl_name,
            package=impl_package if strategy != FileAccessStrategy.UNSPECIFIED else adapter.package,
            source_adapter=adapter.name,
            strategy=strategy,
            methods=tuple(methods),
            source_resource=adapter.source_resource,
            access_mode=adapter.access_mode,
            file_organization="SEQUENTIAL",  # default; overridden by IR
            implements_interface=True,
        ))

    return implementations


def _derive_adapter_methods(
    adapter: SpringBootAdapter,
) -> list[SpringBootAdapterMethod]:
    """Derive adapter methods from access mode."""
    methods: list[SpringBootAdapterMethod] = []

    if adapter.access_mode in ("READ", "READ_WRITE"):
        methods.append(SpringBootAdapterMethod(
            name="read",
            operation_type=SpringBootFileOperationType.READ,
            return_type=JavaType(basic_type=JavaBasicType.STRING),
        ))

    if adapter.access_mode in ("WRITE", "READ_WRITE", "APPEND"):
        methods.append(SpringBootAdapterMethod(
            name="write",
            operation_type=SpringBootFileOperationType.WRITE,
            return_type=JavaType(basic_type=JavaBasicType.VOID),
            parameters=((JavaType(basic_type=JavaBasicType.STRING), "record"),),
        ))

    methods.append(SpringBootAdapterMethod(
        name="close",
        operation_type=SpringBootFileOperationType.CLOSE,
        return_type=JavaType(basic_type=JavaBasicType.VOID),
    ))

    return methods

def _to_class_name(name: str) -> str:
    """Convert a resource/program name to PascalCase class name."""
    return name.replace("-", "_").replace(" ", "_").title().replace("_", "")


def _map_transaction_type(java_type: JavaTransactionType) -> SpringBootTransactionType:
    """Map JavaTransactionType to SpringBootTransactionType."""
    mapping = {
        JavaTransactionType.CICS_TRANSACTION: SpringBootTransactionType.SERVICE_TRANSACTION,
        JavaTransactionType.DB2_TRANSACTION: SpringBootTransactionType.REPOSITORY_TRANSACTION,
        JavaTransactionType.BATCH_STEP: SpringBootTransactionType.BATCH_STEP,
        JavaTransactionType.METHOD_BOUNDARY: SpringBootTransactionType.METHOD_BOUNDARY,
    }
    return mapping.get(java_type, SpringBootTransactionType.METHOD_BOUNDARY)


def _find_participating_services(
    tx_name: str,
    application: JavaApplication,
    services: list[SpringBootService],
) -> list[str]:
    """Find services that participate in a transaction boundary."""
    participating: list[str] = []
    for program in application.programs:
        for tb in program.transaction_boundaries:
            if tb.name == tx_name:
                service_name = _to_class_name(program.program_id)
                if service_name not in participating:
                    participating.append(service_name)
    return participating
