import sys
import subprocess

result = subprocess.run([
    sys.executable, '-c', '''
from engine.transformation.cobol_parser import CobolParser
from pathlib import Path

parser = CobolParser()
with open("fixtures/workload-claims/cobol/CLAIMS.cob") as f:
    source = f.read()

program = parser.parse(source)
print("Number of paragraphs:", len(program.paragraphs))
for p in program.paragraphs:
    print(f"  {p.name}: {len(p.statements)} statements")
'''
], capture_output=True, text=True)

print('STDOUT:', result.stdout)
print('STDERR:', result.stderr)
print('Return code:', result.returncode)