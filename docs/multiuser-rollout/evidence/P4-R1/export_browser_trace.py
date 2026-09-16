"""Export the bounded, actual browser tool transcript; never reconstruct UI output.

Usage: python export_browser_trace.py SESSION_JSONL OUTPUT_JSON
Only the P4-R1 focused UI window is exported. Exact synthetic inputs are redacted.
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def constant(relative, name):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(name)


redactions = [constant('tests/p4_browser_harness.py', 'CANARY'),
              constant('tests/auth_helpers.py', 'ADMIN_PASSWORD')]
calls, rows = set(), []
with Path(sys.argv[1]).open(encoding='utf-8') as stream:
    for line in stream:
        item = json.loads(line)
        timestamp = item.get('timestamp', '')
        if not ('2026-09-16T17:51:30' <= timestamp < '2026-09-16T17:54:40'):
            continue
        if item.get('type') != 'response_item':
            continue
        payload = item['payload']
        if payload.get('type') == 'function_call' and payload.get('name') == 'js':
            calls.add(payload['call_id'])
        elif payload.get('type') != 'function_call_output' or payload.get('call_id') not in calls:
            continue
        rows.append({'utc': timestamp, 'payload': payload})
text = json.dumps({'source': 'Actual Codex browser calls and returned output',
                   'business_sha': 'e6c3edd95830d4c778fee357b8807d1443920a04',
                   'redaction': 'Exact synthetic key and test password only',
                   'calls': len(calls), 'results': sum(r['payload']['type'] == 'function_call_output' for r in rows),
                   'entries': rows}, ensure_ascii=False, indent=2)
for value in redactions:
    text = text.replace(value, '[REDACTED_SYNTHETIC_INPUT]')
Path(sys.argv[2]).write_text(text + '\n', encoding='utf-8')
print(json.dumps({'calls': len(calls), 'entries': len(rows), 'exported_bytes': len(text.encode())}))
