"""COBOL estate discovery: ingestion, immutable checkpoints, scanning, dependency analysis and the discovery report.

The generic ingestion, checkpoint and Git components are adapted from the Stage 1 Pascal discovery
(Shankar373/Pascal-Java-Transformation, branch feat/stage1-ingestion-discovery); every language-specific piece is
COBOL-estate specific.  Deterministic and rule-based; no LLM and no network access except an explicit remote Git fetch.
"""

__version__ = "1.0.0"
