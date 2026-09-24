"""Multi-program workload definition."""

from engine.workload import WorkloadDefinition, WorkloadInput, WorkloadArtifact

WORKLOAD_MULTIPROG = WorkloadDefinition(
    workload_id="multiprog",
    cobol_sources=(
        "fixtures/workload-multiprog/cobol/MAINPROG.cob",
        "fixtures/workload-multiprog/cobol/CALCULATE.cob",
    ),
    inputs=(
        WorkloadInput(
            name="multiprog.dat",
            source_path="fixtures/workload-multiprog/input/multiprog.dat",
            destination_path="/workspace/input/multiprog.dat",
        ),
    ),
    artifacts=(
        WorkloadArtifact(
            name="output.txt",
            path="/workspace/output.txt",
            comparator="TEXT_FILE",
        ),
    ),
)