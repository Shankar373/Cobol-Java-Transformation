import sys
import os
import shutil

# Clear all pycache
for root, dirs, files in os.walk('C:\\Users\\bandi\\Desktop\\SystemaOps\\Cobol-Java-Transformation\\engine'):
    for f in files:
        if f.endswith('.pyc'):
            os.remove(os.path.join(root, f))
    for d in dirs:
        if d == '__pycache__':
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)

# Monkey-patch _parse_read with detailed debug
import engine.transformation.cobol_parser as cp_module
original_parse_read = cp_module.CobolParser._parse_read

def debug_parse_read(self, lines, start):
    print(f'  _parse_read ENTER: start={start}, line={lines[start].strip()[:60]}')
    result, new_i = original_parse_read(self, lines, start)
    print(f'  _parse_read EXIT: start={start}, returned new_i={new_i} (len={len(lines)})')
    if new_i < len(lines):
        print(f'  Next line: {lines[new_i].strip()[:80]}')
    else:
        print(f'  _parse_read returned END OF FILE')
    return result, new_i

import engine.transformation.cobol_parser as cp_module
cp_module.CobolParser._parse_read = debug_parse_read

from engine.transformation.cobol_parser import CobolParser
from pathlib import Path

parser = CobolParser()
with open('fixtures/workload-claims/cobol/CLAIMS.cob') as f:
    source = f.read()

program = parser.parse(source)
print('Number of paragraphs:', len(program.paragraphs))
for p in program.paragraphs:
    print(f'  {p.name}: {len(p.statements)} statements')