"""Run full pipeline for DIVIDE INTO fixture."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.pipeline import PipelineConfig, VerticalSlicePipeline

cobol_dir = str(Path("fixtures/workload-divide-into-verified/cobol").resolve())
java_dir = str(Path("fixtures/workload-divide-into-verified/java-candidate").resolve())

config = PipelineConfig(
    workload_id="divide-into-verified",
    cobol_source_path=cobol_dir,
    java_candidate_path=java_dir,
    java_entrypoint="Div_Into",
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
print(f"Oracle stdout preview: {result.oracle_stdout[:300].decode(errors='replace')}")
print(f"Candidate stdout preview: {result.candidate_stdout[:300].decode(errors='replace')}")
