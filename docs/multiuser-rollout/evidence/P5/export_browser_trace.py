"""Export actual P5 formal browser calls/results, not reconstructed assertions.

Usage: python export_browser_trace.py SESSION_JSONL OUTPUT_JSON END_UTC [START_UTC SHA]
The bounded f4773f0 attempt is retained even though it found a timeline UI defect.
"""
import json
from pathlib import Path
import re
import sys

start = sys.argv[4] if len(sys.argv) > 4 else '2026-09-16T21:40:45'
sha = sys.argv[5] if len(sys.argv) > 5 else 'f4773f0075325625c6cf2e6236c5d2014d416d3f'
calls, rows = set(), []
with Path(sys.argv[1]).open(encoding='utf-8') as stream:
    for line in stream:
        item = json.loads(line)
        timestamp = item.get('timestamp', '')
        if not (start <= timestamp < sys.argv[3]):
            continue
        if item.get('type') != 'response_item':
            continue
        payload = item['payload']
        if payload.get('type') == 'function_call':
            if payload.get('name') != 'js' or 'p5formal' not in payload.get('arguments', ''):
                continue
            if 'p5Reviewer' in payload.get('arguments', ''):
                continue  # Do not include a mixed call containing review conversation text.
            calls.add(payload['call_id'])
        elif payload.get('type') != 'function_call_output' or payload.get('call_id') not in calls:
            continue
        rows.append({'utc': timestamp, 'payload': payload})
text = json.dumps({'source': 'Actual Codex browser calls and returned output',
    'business_sha': sha, 'utc_start': start, 'utc_end_exclusive': sys.argv[3],
    'scope': 'Only formal A/B/second-A tool calls in the explicit UTC interval; no cookies or network headers requested',
    'redaction': 'Synthetic test login password and phone inputs; no output reconstructed',
    'calls': len(calls), 'results': sum(r['payload']['type'] == 'function_call_output' for r in rows),
    'entries': rows}, ensure_ascii=False, indent=2)
text = text.replace('P5-browser-isolated-only!', '[REDACTED_TEST_PASSWORD]')
text = re.sub(r'\+861390000000[1-4]', '[REDACTED_TEST_LOGIN]', text)
Path(sys.argv[2]).write_text(text+'\n', encoding='utf-8')
print(json.dumps({'calls': len(calls), 'entries': len(rows), 'bytes': len(text.encode())}))
