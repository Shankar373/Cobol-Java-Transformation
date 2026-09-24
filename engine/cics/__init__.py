"""CICS modernization lane — explicit Java/Spring service model.

Upgrades CICS from parser/IR extraction (``engine.transformation.cics_parser``,
``engine.transformation.ir``) toward an explicit Java/Spring service model:

- ``subset.py``   — supported-subset classification (single source of truth).
- ``model.py``    — IR-free output model (transaction boundaries, request/
                    response, program interaction, resource access).
- ``mapper.py``   — CICS IR → output model (the only IR boundary).
- ``generator.py``— output model → explicit Java/Spring source + report.
- ``naming.py``   — deterministic Java identifier derivation.

The facade ``engine.transformation.cics_java_mapping`` exposes block
extraction from real COBOL source plus map/generate entry points.

Boundaries:
- NO CICS TS runtime equivalence is claimed anywhere.
- Unsupported CICS constructs stay explicit: carried in the model, emitted
  verbatim in generated source and the mapping report, never dropped.
- The shared Spring Boot generator is NOT modified: integration is described
  only (see the generator integration contract for this package).
"""

from engine.cics.generator import CicsSpringGenerator
from engine.cics.mapper import CicsSpringMapper
from engine.cics.model import CicsGeneratedFile, CicsSpringApplication
from engine.cics.subset import SUPPORTED_SUBSET_VERSION, classify_command

__all__ = [
    "SUPPORTED_SUBSET_VERSION",
    "CicsGeneratedFile",
    "CicsSpringApplication",
    "CicsSpringGenerator",
    "CicsSpringMapper",
    "classify_command",
]