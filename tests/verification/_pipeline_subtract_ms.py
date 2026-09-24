"""Run full pipeline for multi-source SUBTRACT."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.pipeline import PipelineConfig, VerticalSlicePipeline

fixture = "workload-subtract-multisource-verified"
cobol_dir = str(Path(f"fixtures/{fixture}/cobol").resolve())
java_dir = str(Path(f"fixtures/{fixture}/java-candidate").resolve())

config = PipelineConfig(
    workload_id=fixture,
    cobol_source_path=cobol_dir,
    java_candidate_path=java_dir,
    java_entrypoint="Sub_Ms",
    use_docker_java=True,
    timeout_seconds=30,
)
pipeline = VerticalSlicePipeline(config)
result = pipeline.run()

print(f"Verdict: {result.verdict.state.value}")
print(f"Oracle exit: {result.oracle_exit_code}")
print(f"Candidate exit: {result.candidate_exit_code}")
print(f"Comparisons: {[c.result for c in result.comparison_evidence]}")
print(f"Differences: {list(result.verdict.differences)}")
