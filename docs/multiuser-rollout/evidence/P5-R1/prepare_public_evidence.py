"""Redact local profile paths and validate the explicit public evidence set."""
import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).parent
for path in root.rglob('*'):
    if not path.is_file() or path.suffix not in {'.json', '.txt'} or path.name == 'SHA256SUMS.json':
        continue
    content = path.read_text(encoding='utf-8')
    # JSON raw strings use double slashes; logs and embedded paths may use one.
    content = re.sub(r'C:(?:\\\\|\\|/)Users(?:\\\\|\\|/)[^\\/\s"]+', '[LOCAL_USER]', content, flags=re.I)
    for forbidden in ['P5-browser-isolated-only!', 'Integration-test-only!', 'postgresql://', 'postgresql+psycopg://']:
        if forbidden in content:
            raise SystemExit(f'Forbidden literal in {path.name}: {forbidden.split(":")[0]}')
    if re.search(r'\+861390000000[1-4]', content):
        raise SystemExit(f'Unredacted test login in {path.name}')
    path.write_text(content, encoding='utf-8')
checksums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS.json' and '__pycache__' not in p.parts}
(root / 'SHA256SUMS.json').write_text(json.dumps(checksums, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'files_hashed': len(checksums), 'known_sensitive_literals': 0}))
