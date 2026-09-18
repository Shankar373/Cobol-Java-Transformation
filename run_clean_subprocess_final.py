import sys
import os
import shutil
import subprocess

# Clear all pycache FIRST
for root, dirs, files in os.walk('C:\\Users\\bandi\\Desktop\\SystemaOps\\Cobol-Java-Transformation\\engine'):
    for f in files:
        if f.endswith('.pyc'):
            os.remove(os.path.join(root, f))
    for d in dirs:
        if d == '__pycache__':
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)

# Run in a completely fresh subprocess
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