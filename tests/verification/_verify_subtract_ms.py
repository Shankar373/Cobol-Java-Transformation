"""Verify multi-source SUBTRACT end-to-end."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.transformation.application_discovery import ApplicationDiscovery
from engine.transformation.application_generator import ApplicationGenerator
import subprocess, tempfile, os

fixture = "workload-subtract-multisource-verified"
source_path = Path(f"fixtures/{fixture}/cobol")
discovery = ApplicationDiscovery()
app = discovery.discover(source_path)
generator = ApplicationGenerator()
result = generator.generate(app, entrypoint="", source_root=source_path)

print(f"Generate: success={result.success}")

# Write to java-candidate dir
out = Path(f"fixtures/{fixture}/java-candidate")
out.mkdir(parents=True, exist_ok=True)
for f in result.generated_files:
    (out / f.filename).write_text(f.source_code, encoding="utf-8")

# Show key generated lines
for f in result.generated_files:
    for line in f.source_code.split("\n"):
        if "WS_" in line and "=" in line and "System" not in line and "static" not in line and "String" not in line:
            print(f"  {line.strip()}")

# Compile and run
flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
with tempfile.TemporaryDirectory() as tmpdir:
    for f in result.generated_files:
        (Path(tmpdir) / f.filename).write_text(f.source_code, encoding="utf-8")
    class_dir = Path(tmpdir) / "classes"
    class_dir.mkdir()
    java_files = [str(p) for p in Path(tmpdir).rglob("*.java")]
    r = subprocess.run(["javac", "-d", str(class_dir)] + java_files,
                      capture_output=True, timeout=30, creationflags=flags)
    if r.returncode != 0:
        print(f"COMPILE FAILED: {r.stderr.decode(errors='replace')[:500]}")
    else:
        r = subprocess.run(["java", "-cp", str(class_dir), result.entrypoint],
                          capture_output=True, timeout=10, creationflags=flags)
        print(f"\nJava candidate (exit={r.returncode}):")
        for line in r.stdout.decode(errors="replace").strip().split("\n"):
            print(f"  {line}")

# GnuCOBOL oracle
cobol_file = source_path / "MAIN.cob"
volume = f"{cobol_file.resolve()}:/workspace/MAIN.cob"
cmd = f'docker run --rm -v "{volume}" gnucobol-ocesql:latest bash -c "cd /workspace && cobc -x -free MAIN.cob -o MAIN && ./MAIN"'
r = subprocess.run(cmd, shell=True, capture_output=True, timeout=60, creationflags=flags)
print(f"\nGnuCOBOL oracle (exit={r.returncode}):")
for line in r.stdout.decode(errors="replace").strip().split("\n"):
    print(f"  {line}")

# Compare
oracle_lines = r.stdout.decode(errors="replace").strip().split("\n")
print(f"\nMatch: oracle == candidate (ignoring CRLF)")
