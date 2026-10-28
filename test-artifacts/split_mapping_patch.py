import subprocess
import sys

p = subprocess.run(
    ['git', 'diff', '--', 'engine/transformation/cobol_to_java_mapping.py'],
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='surrogateescape',
)
if p.returncode != 0:
    sys.exit(p.stderr)

lines = p.stdout.split('\n')
hdr, hunks, cur = [], [], None
for line in lines:
    if line.startswith('@@'):
        if cur is not None:
            hunks.append(cur)
        cur = [line]
    elif cur is None:
        hdr.append(line)
    else:
        cur.append(line)
if cur is not None:
    hunks.append(cur)

keep = [
    h for h in hunks
    if h[0].startswith('@@ -954,7') or h[0].startswith('@@ -962,17')
]
print('total hunks:', len(hunks), 'kept:', len(keep))
for h in hunks:
    print(('KEEP' if h in keep else 'DROP'), h[0])

patch = '\n'.join(hdr + [line for h in keep for line in h])
with open('test-artifacts/phaseD-mapping.patch', 'w', encoding='utf-8', newline='\n') as f:
    f.write(patch)
