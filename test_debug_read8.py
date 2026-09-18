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

# Monkey-patch _parse_read with EXTREMELY detailed debug
import engine.transformation.cobol_parser as cp_module
original_parse_read = cp_module.CobolParser._parse_read

def debug_parse_read(self, lines, start):
    print(f'  _parse_read ENTER: start={start}, line={lines[start].strip()[:60]}')
    i = start + 1
    at_end_body = []
    not_at_end_body = []
    current_section = None

    while i < len(lines):
        l = lines[i].strip()
        u = l.upper()
        print(f'    _parse_read i={i}: "{l[:80]}"')
        
        if 'AT END' in u and 'NOT AT END' not in u:
            current_section = 'at_end'
            i += 1
            continue
        if 'NOT AT END' in u:
            current_section = 'not_at_end'
            i += 1
            continue
        if u.startswith('END-READ'):
            print(f'  FOUND END-READ at i={i}, line="{lines[i].strip()}"')
            i += 1
            break
        if u.startswith(('OPEN', 'CLOSE', 'WRITE')):
            print(f'  BREAK on OPEN/CLOSE/WRITE at i={i}, line={lines[i].strip()[:60]}')
            break

        if current_section == 'at_end':
            pass
        elif current_section == 'not_at_end':
            pass
        else:
            pass
        
        i += 1

    print(f'  _parse_read EXIT: i={i}, len={len(lines)}')
    return None, i  # Return dummy for now

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