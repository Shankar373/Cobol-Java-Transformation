# ARCHITECTURE_AND_DEPENDENCY_MAP

- Report date: 2026-10-31
- Branch: codex/universal-core

## Pipeline
Universal Ingestion -> Application Discovery -> Semantic Analysis -> Capability Graph -> Modernization Plan -> Transformation Execution -> Validation -> Release Evidence.

## Modules
- Ingestion: api/ingestion.py, api/service.py
- Discovery: engine/transformation/application_discovery.py
- Parser/IR: engine/transformation/cobol_parser.py, ir.py
- Mapping: engine/transformation/cobol_to_java_mapping.py
- Generation: engine/transformation/java_generator.py, spring_boot_generator.py, spring_boot_ir.py
- Runtime: engine/candidate/*.py, engine/execution/*
- Oracle: engine/oracle/*.py
- Verdict: engine/verdict/derivation.py
- API: api/app.py, api/service.py, api/store.py
- Frontend: frontend/src

## Dependencies
- Python 3.11, requirements.lock
- Docker images: gnucobol-ocesql, maven-offline-springboot, eclipse-temurin:21-jdk
- Node 20 for frontend

## Data flow
COBOL source -> parser -> IR -> mapping -> Java IR -> Spring Boot generator -> Maven build -> Docker execution -> verdict derivation against GnuCOBOL oracle.