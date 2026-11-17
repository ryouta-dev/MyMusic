"""Checks the documentation package, not application behaviour."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
paths = [root / 'README.md'] + [root / 'docs' / name for name in (
    '01-product.md', '02-architecture.md',
    '03-sources-decisions.md', '04-agent-handoff.md')]
errors = []
links = 0
for path in paths:
    text = path.read_text(encoding='utf-8-sig')
    if len(text) < 500 or not text.startswith('# '):
        errors.append(f'{path.name}: missing document content')
    if '\ufffd' in text:
        errors.append(f'{path.name}: replacement character')
    for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
        if target.startswith(('https://', 'http://', '#')):
            continue
        links += 1
        if not (path.parent / target.split('#')[0]).is_file():
            errors.append(f'{path.name}: broken link {target}')
    if any(marker in text for marker in ('TODO', 'Lorem ipsum', '[74 lines', '[60 lines')):
        errors.append(f'{path.name}: unfinished or transport placeholder')
if errors:
    raise SystemExit('\n'.join(errors))
print(f'PASS: {len(paths)} UTF-8 documents; {links} local links resolved; no placeholder markers.')
print('Scope: document structure only; no playback or performance tests were run.')
